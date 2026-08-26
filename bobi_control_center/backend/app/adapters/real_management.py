"""The Home Assistant management bridge.

Only declared `script.bobi_cc_*` bridge services are reachable from this module.
There is no raw Home Assistant service fallback. The management contract is the
authoritative discovery source; the application validates it against its own
closed schemas before exposing a resource or operation.

Home Assistant remains authoritative for the master write switch, validation,
stale-preview detection and read-after-write verification. The server-side
preview store in `services/manage.py` adds the five-minute, single-use,
payload-bound confirmation gate before any commit service can be reached.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.adapters.management import UNAVAILABLE_MESSAGE, ManagementBridge
from app.errors import BobiError
from app.models.manage import (
    FEATURE_OPERATIONS,
    TASK_OPERATIONS,
    BridgeOutcome,
    ManagedOperation,
    ManagedTarget,
    ManagementResource,
    ManagementStatus,
    ObservedState,
    ResourceSnapshot,
    SnapshotTask,
    TaskSnapshot,
)
from app.services import normalize
from app.services.resource_normalize import normalize_resource, unavailable
from app.services.resources import (
    RESOURCE_IDS,
    RESOURCE_READ_SERVICES,
    RESOURCE_WRITE_SERVICES,
    SPECS,
    canonical_operation,
)

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters to type checkers
    from app.adapters.real import RealHomeAssistantAdapter

logger = logging.getLogger("bobi.manage.ha")

#: Bridge scripts, without the `script.` domain prefix.
CONTRACT = "bobi_cc_manage_contract"
TASK_SNAPSHOT = "bobi_cc_task_snapshot"
TASK_ADD_COMMIT = "bobi_cc_task_add_commit"
TASK_UPDATE_COMMIT = "bobi_cc_task_update_commit"
FEATURE_COMMIT = "bobi_cc_feature_commit"

#: The read half. Callable while previewing.
MANAGEMENT_READ_SERVICES = frozenset({CONTRACT, TASK_SNAPSHOT}) | RESOURCE_READ_SERVICES
#: The write half. Reachable only from `apply()`, only after a confirmed
#: preview, and only when Home Assistant's master switch is on.
MANAGEMENT_WRITE_SERVICES = (
    frozenset({TASK_ADD_COMMIT, TASK_UPDATE_COMMIT, FEATURE_COMMIT}) | RESOURCE_WRITE_SERVICES
)

#: Hebrew for the operations the contract names.
_TASK_OPERATION_LABELS = {
    "add": "הוספת משימה",
    "edit": "שינוי תוכן",
    "complete": "סימון כבוצעה",
    "reopen": "החזרה לפעילה",
    "delete": "מחיקה",
}

#: Statuses the snapshot uses.
_COMPLETED = "completed"
_OPEN = "needs_action"


class RealManagementBridge(ManagementBridge):
    """Talk to Bobi's closed management bridge surface, and nothing else."""

    def __init__(self, adapter: RealHomeAssistantAdapter) -> None:
        self._adapter = adapter

    async def _payload(self, service: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._adapter._payload(service, data)

    # --- discovery --------------------------------------------------------
    async def status(self) -> ManagementStatus:
        """Read and validate `script.bobi_cc_manage_contract`."""
        payload = await self._payload(CONTRACT)
        return _contract(payload)

    # --- reads ------------------------------------------------------------
    async def snapshot(self) -> TaskSnapshot:
        """`script.bobi_cc_task_snapshot`. Read-only."""
        return _snapshot(await self._payload(TASK_SNAPSHOT))

    async def resource_snapshot(self, resource: str) -> ResourceSnapshot:
        """Read one contract-driven family from its declared Bobi bridge.

        A missing bridge is represented as unavailable. It is never replaced by
        an entity lookup or a raw Home Assistant service call.
        """
        spec = SPECS.get(resource)
        if spec is None or spec.snapshot_service is None:
            return unavailable(resource, UNAVAILABLE_MESSAGE)
        try:
            payload = await self._payload(spec.snapshot_service)
        except BobiError as exc:
            if exc.code == "bridge_service_missing":
                return unavailable(
                    resource, f"{spec.label}: הגשר של בובי עדיין לא כולל את השירות הזה"
                )
            raise
        return normalize_resource(resource, payload)

    async def observe(self, resource_type: str, resource_id: str | None) -> ObservedState | None:
        """Read the current state a preview binds to."""
        if resource_type in SPECS and resource_type not in ("tasks", "features"):
            return await self._observe_resource(resource_type, resource_id)

        if resource_type == "tasks":
            if resource_id is None:
                return ObservedState(resource_id=None, label=None, values={})
            snapshot = await self.snapshot()
            task = next((item for item in snapshot.tasks if item.uid == resource_id), None)
            if task is None:
                return None
            return ObservedState(
                resource_id=task.uid,
                label=task.summary,
                values={
                    "summary": task.summary,
                    "status": task.status,
                    "user_id": task.owner_id,
                    "owner": task.owner,
                },
            )

        if resource_type == "features":
            status = await self.status()
            resource = next((r for r in status.resources if r.id == "features"), None)
            target = next(
                (t for t in (resource.targets if resource else []) if t.id == resource_id), None
            )
            if target is None or target.enabled is None:
                return None
            return ObservedState(
                resource_id=target.id,
                label=target.label,
                values={"state": "on" if target.enabled else "off", "enabled": target.enabled},
            )

        return None

    async def _observe_resource(
        self, resource: str, resource_id: str | None
    ) -> ObservedState | None:
        """Find the item a preview is about and retain its expected state."""
        if resource_id is None:
            return ObservedState(resource_id=None, label=None, values={})

        snapshot = await self.resource_snapshot(resource)
        if not snapshot.available:
            return None
        item = next((entry for entry in snapshot.items if entry.id == resource_id), None)
        if item is None or item.value is None:
            return None

        values: dict[str, Any] = {"value": item.value}
        for key, value in item.detail.items():
            if isinstance(value, str | int | float | bool):
                values[key] = value
        return ObservedState(resource_id=item.id, label=item.label, values=values)

    # --- writes -----------------------------------------------------------
    async def apply(
        self,
        *,
        resource_type: str,
        operation: str,
        resource_id: str | None,
        payload: dict[str, Any],
        observed: ObservedState,
        request_id: str,
        preview_token: str,
    ) -> BridgeOutcome:
        """Map one validated operation onto one declared commit bridge."""
        if not preview_token:
            raise _missing_token(resource_type, operation)
        if resource_type == "tasks":
            return await self._apply_task(
                operation, resource_id, payload, observed, request_id, preview_token
            )
        if resource_type == "features":
            return await self._apply_feature(
                operation, resource_id, payload, observed, request_id, preview_token
            )
        if resource_type in SPECS:
            return await self._apply_resource(
                resource_type, operation, resource_id, payload, observed, request_id, preview_token
            )
        raise _unsupported(resource_type, operation)

    async def _apply_resource(
        self,
        resource: str,
        operation: str,
        resource_id: str | None,
        payload: dict[str, Any],
        observed: ObservedState,
        request_id: str,
        preview_token: str,
    ) -> BridgeOutcome:
        """Commit one contract-driven family using only its explicit bridge."""
        spec = SPECS[resource]
        if operation not in spec.operations:
            raise _unsupported(resource, operation)
        if spec.commit_service is None:
            raise _unsupported(resource, operation)

        data: dict[str, Any] = {"operation": operation}
        if resource_id is not None:
            data[spec.id_field] = resource_id
        data.update(payload)
        for key, value in observed.values.items():
            data[f"expected_{key}"] = value
        data["preview_token"] = preview_token
        data["confirmed"] = True
        data["request_id"] = request_id
        return _outcome(await self._payload(spec.commit_service, data))

    async def _apply_task(
        self,
        operation: str,
        resource_id: str | None,
        payload: dict[str, Any],
        observed: ObservedState,
        request_id: str,
        preview_token: str,
    ) -> BridgeOutcome:
        if operation not in TASK_OPERATIONS:
            raise _unsupported("tasks", operation)

        if operation == "add":
            data = {
                "user_id": payload.get("user_id"),
                "summary": payload.get("summary"),
                "due_date": payload.get("due_date") or "",
                "preview_token": preview_token,
                "confirmed": True,
                "request_id": request_id,
            }
            return _outcome(await self._payload(TASK_ADD_COMMIT, data))

        data = {
            "operation": operation,
            "user_id": observed.values.get("user_id") or payload.get("user_id"),
            "uid": resource_id,
            "new_summary": payload.get("new_summary") or "",
            "expected_summary": observed.values.get("summary") or "",
            "expected_status": observed.values.get("status") or "",
            "preview_token": preview_token,
            "confirmed": True,
            "request_id": request_id,
        }
        return _outcome(await self._payload(TASK_UPDATE_COMMIT, data))

    async def _apply_feature(
        self,
        operation: str,
        resource_id: str | None,
        payload: dict[str, Any],
        observed: ObservedState,
        request_id: str,
        preview_token: str,
    ) -> BridgeOutcome:
        if operation not in FEATURE_OPERATIONS:
            raise _unsupported("features", operation)

        data = {
            "feature_id": resource_id,
            "enabled": bool(payload.get("enabled")),
            "expected_state": observed.values.get("state"),
            "preview_token": preview_token,
            "confirmed": True,
            "request_id": request_id,
        }
        return _outcome(await self._payload(FEATURE_COMMIT, data))


def _unsupported(resource_type: str, operation: str) -> BobiError:
    return BobiError(
        "הפעולה הזו אינה נתמכת על ידי הגשר של בובי",
        code="operation_not_supported",
        status_code=422,
        details={"resource": resource_type, "operation": operation},
    )


def _missing_token(resource_type: str, operation: str) -> BobiError:
    """No token means no Home Assistant request is built."""
    return BobiError(
        "התצוגה המקדימה כבר אינה בתוקף. בצעו תצוגה מקדימה מחדש.",
        code="preview_token_missing",
        status_code=409,
        details={"resource": resource_type, "operation": operation},
    )


# --- contract normalization -------------------------------------------------
def _bool(value: Any) -> bool | None:
    return normalize._bool(value)


def _text(value: Any) -> str | None:
    return normalize._text(value)


def _contract_entries(payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Validate `resources[]` and return known declarations in wire order.

    Contract 3c makes this array authoritative. Unknown resources and malformed
    entries are ignored rather than guessed. If the key exists but is not a
    list, the result is deliberately empty: malformed new discovery data must
    not silently fall back to broader permissions.

    Older contracts did not have `resources`; for those only the legacy tasks
    and features blocks are admitted, preserving 3.0.0 compatibility without
    manufacturing any of the newer families.

    **`tasks` and `features` are admitted from their own blocks even when
    `resources` is present.** The live 3c contract sends both shapes and lists
    neither of those two in the array — so reading the array alone dropped the
    only two families that actually work today, and task management would have
    gone dark the moment the newer families were declared. Authority still rests
    with `resources` where it names something: a family listed there wins, and
    the legacy block only fills a gap it left.
    """
    if "resources" not in payload:
        return [
            (resource, {})
            for resource in ("tasks", "features")
            if isinstance(payload.get(resource), dict)
        ]

    raw = payload.get("resources")
    if not isinstance(raw, list):
        return []

    known = set(RESOURCE_IDS)
    result: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for entry in raw:
        meta: dict[str, Any]
        if isinstance(entry, str):
            resource = _text(entry)
            meta = {}
        elif isinstance(entry, dict):
            resource = _text(normalize._first(entry, "id", "resource"))
            meta = entry
        else:
            continue
        if resource not in known or resource in seen:
            continue
        seen.add(resource)
        result.append((resource, meta))

    for legacy in ("tasks", "features"):
        if legacy not in seen and isinstance(payload.get(legacy), dict):
            result.append((legacy, {}))
    return result


def _merged_meta(payload: dict[str, Any], resource: str, meta: dict[str, Any]) -> dict[str, Any]:
    """Combine a legacy per-family block with its 3c declaration."""
    legacy = payload.get(resource)
    if not isinstance(legacy, dict):
        legacy = {}
    return {**legacy, **meta}


def _supported(meta: dict[str, Any]) -> bool:
    """Explicit false denies; omission is allowed only after resources[] declared it."""
    for key in ("supported", "available"):
        if key in meta:
            return _bool(meta.get(key)) is True
    return True


def _operations(
    meta: dict[str, Any], allowed: tuple[str, ...], resource: str | None = None
) -> tuple[list[str], bool]:
    """Intersect advertised operations with the application's closed schema.

    A missing `operations` field means the 3c resource declaration itself is the
    family-level capability declaration, so the app's already-audited operation
    schema applies. An explicit malformed or empty list grants nothing and makes
    the resource unavailable for management.

    Names are translated through the synonym table first — the live contract
    says `add` where this application says `create`, and an unreconciled synonym
    is silently dropped by the closed-set filter, so the bridge would announce
    an operation, the app would quietly not offer it, and neither side would
    report anything wrong. Only true synonyms translate; a verb this application
    cannot describe and check stays dropped, because the closed set is what
    makes the write path safe.
    """
    if "operations" not in meta:
        return list(allowed), True
    raw = meta.get("operations")
    if not isinstance(raw, list):
        return [], False
    # The live contract sends `[{"id": "add", "label": …, "destructive": …}]`
    # where the older one sent `["add"]`. Both are read: a list of objects that
    # only `_str_list` understood came back empty, which read as "this family
    # declares no operations" — the family went read-only and nothing said why.
    names: list[str] = []
    for entry in raw:
        if isinstance(entry, str):
            name = _text(entry)
        elif isinstance(entry, dict):
            name = _text(normalize._first(entry, "id", "operation", "name"))
        else:
            continue
        if name:
            names.append(name)

    translated = [
        canonical_operation(resource, name) if resource else name for name in names
    ]
    # De-duplicated in wire order: two synonyms of one verb are one operation.
    operations: list[str] = []
    for name in translated:
        if name in allowed and name not in operations:
            operations.append(name)
    # A list is a valid declaration even when it is empty, and an empty one is
    # the documented way to publish a snapshot bridge whose commit bridge has
    # not been written yet: the family reads, and draws no save button. Treating
    # it as invalid reported those families *unavailable* instead — the
    # difference between a screen full of values and a screen saying there is
    # nothing here. Only a non-list is malformed, and that is refused above.
    return operations, True


def _task_resource(
    payload: dict[str, Any], meta: dict[str, Any], bridge_available: bool
) -> ManagementResource:
    merged = _merged_meta(payload, "tasks", meta)
    operations, operations_valid = _operations(merged, TASK_OPERATIONS, "tasks")
    supported = _supported(merged) and operations_valid
    return ManagementResource(
        id="tasks",
        label=_text(merged.get("label")) or "משימות",
        available=bridge_available and supported,
        operations=[
            ManagedOperation(
                id=name,
                label=_TASK_OPERATION_LABELS.get(name, name),
                destructive=name == "delete",
            )
            for name in operations
        ],
        targets=[
            ManagedTarget(id=user_id, label=name)
            for item in normalize._as_items(merged.get("users"))
            if (user_id := _text(item.get("id")))
            and (name := _text(item.get("name")) or user_id)
        ],
        detail=None if supported else _text(normalize._first(merged, "reason", "detail")),
    )


def _feature_resource(
    payload: dict[str, Any], meta: dict[str, Any], bridge_available: bool
) -> ManagementResource:
    merged = _merged_meta(payload, "features", meta)
    operations, operations_valid = _operations(merged, FEATURE_OPERATIONS, "features")
    supported = _supported(merged) and operations_valid
    targets = [
        ManagedTarget(
            id=feature_id,
            label=_text(item.get("label")) or feature_id,
            risk=_text(item.get("risk")),
            enabled=_bool(normalize._first(item, "enabled", "state", "value")),
        )
        for item in normalize._as_items(merged.get("items"))
        if (feature_id := _text(item.get("id")))
    ]
    return ManagementResource(
        id="features",
        label=_text(merged.get("label")) or "תכונות",
        available=bridge_available and supported,
        operations=[ManagedOperation(id="set", label="הפעלה או כיבוי")]
        if "set" in operations
        else [],
        targets=targets,
        detail=None if supported else _text(normalize._first(merged, "reason", "detail")),
    )


def _generic_resource(
    payload: dict[str, Any], resource: str, meta: dict[str, Any], bridge_available: bool
) -> ManagementResource:
    spec = SPECS[resource]
    merged = _merged_meta(payload, resource, meta)
    operations, operations_valid = _operations(merged, spec.operations, spec.id)
    supported = _supported(merged) and operations_valid
    return ManagementResource(
        id=resource,
        label=_text(merged.get("label")) or spec.label,
        available=bridge_available and supported,
        operations=[
            ManagedOperation(
                id=operation,
                label=spec.titles.get(operation, operation),
                destructive=operation in spec.destructive,
            )
            for operation in operations
        ],
        detail=(
            _text(normalize._first(merged, "reason", "detail"))
            if not supported
            else None
        ),
    )


def _contract(payload: dict[str, Any]) -> ManagementStatus:
    """`bobi_cc_manage_contract` → validated canonical management status."""
    available = _bool(payload.get("bridge_available")) is True
    writes_enabled = _bool(payload.get("writes_enabled")) is True

    resources: list[ManagementResource] = []
    for resource, meta in _contract_entries(payload):
        if resource == "tasks":
            resources.append(_task_resource(payload, meta, available))
        elif resource == "features":
            resources.append(_feature_resource(payload, meta, available))
        elif resource in SPECS:
            resources.append(_generic_resource(payload, resource, meta, available))

    return ManagementStatus(
        available=available,
        reason=None if available else UNAVAILABLE_MESSAGE,
        contract_version=_text(payload.get("contract_version")),
        resources=resources,
        writes_enabled=writes_enabled,
        # Missing/false flags never relax the application's mandatory flow.
        requires_preview=_bool(payload.get("requires_preview")) is not False,
        requires_confirmation=_bool(payload.get("requires_confirmation")) is not False,
        requires_read_after_write=_bool(payload.get("requires_read_after_write")) is not False,
    )


# --- task snapshot / commit outcome normalization ---------------------------
def _snapshot(payload: dict[str, Any]) -> TaskSnapshot:
    """`bobi_cc_task_snapshot` → one flat list, with the owner on each task."""
    tasks: list[SnapshotTask] = []
    owners: list[ManagedTarget] = []

    for group in normalize._as_items(payload.get("users"), id_key="id"):
        owner_id = _text(group.get("id"))
        owner = _text(group.get("name")) or owner_id
        if owner_id is None or owner is None:
            continue
        owners.append(ManagedTarget(id=owner_id, label=owner))

        for item in normalize._as_items(group.get("items")):
            uid = _text(item.get("uid"))
            summary = _text(item.get("summary"))
            if uid is None or summary is None:
                continue
            status = _text(item.get("status")) or _OPEN
            tasks.append(
                SnapshotTask(
                    uid=uid,
                    summary=summary,
                    status=status,
                    completed=status.lower() == _COMPLETED,
                    due=_text(item.get("due")),
                    owner_id=owner_id,
                    owner=owner,
                )
            )

    return TaskSnapshot(
        count=len(tasks),
        tasks=tasks,
        owners=owners,
        writes_enabled=bool(_bool(payload.get("writes_enabled"))),
    )


def _outcome(payload: dict[str, Any]) -> BridgeOutcome:
    """A commit response → the canonical outcome."""
    return BridgeOutcome(
        executed=bool(_bool(payload.get("executed"))),
        verified=_bool(payload.get("verified")),
        reason=_text(payload.get("reason")),
        resource_id=_text(normalize._first(payload, "uid", "feature_id", "resource_id")),
        writes_enabled=bool(_bool(payload.get("writes_enabled"))),
    )
