"""The Home Assistant write bridge — Phase 3A.

Five `script.bobi_cc_*` services and nothing else:

| Service | Kind |
| --- | --- |
| `bobi_cc_manage_contract` | read — what may be managed, and whether writes are on |
| `bobi_cc_task_snapshot` | read — open and completed tasks |
| `bobi_cc_task_add_commit` | write |
| `bobi_cc_task_update_commit` | write — edit · complete · reopen · delete |
| `bobi_cc_feature_commit` | write |

`todo.add_item`, `todo.update_item`, `todo.remove_item` and every
`input_boolean.*` are **never** called. The adapter's allow-list rejects them
before a request is built, and a test asserts none of them appears anywhere on
this path. Bobi's bridge owns those entities; this application only asks the
bridge, by operation name, to do one of the things it has declared.

## The two layers

Home Assistant enforces its own master switch, whitelists, duplicate checks,
expected-state comparison and read-after-write. This module does not repeat that
work and, more importantly, does not relax anything because of it: the token,
expiry, single-use and confirmation checks in `services/manage.py` run whatever
the bridge would have done.

## The master switch

`writes_enabled` is read here and reported upward. There is no code path that
sets it, and none may ever be added: enabling writes is a Home Assistant-side
decision, taken after its own end-to-end testing.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.adapters.management import UNAVAILABLE_MESSAGE, ManagementBridge
from app.models.manage import (
    FEATURE_OPERATIONS,
    TASK_OPERATIONS,
    BridgeOutcome,
    ManagedOperation,
    ManagedTarget,
    ManagementResource,
    ManagementStatus,
    ObservedState,
    SnapshotTask,
    TaskSnapshot,
)
from app.services import normalize

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
MANAGEMENT_READ_SERVICES = frozenset({CONTRACT, TASK_SNAPSHOT})
#: The write half. Reachable only from `apply()`, only after a confirmed
#: preview, and only when Home Assistant's master switch is on.
MANAGEMENT_WRITE_SERVICES = frozenset({TASK_ADD_COMMIT, TASK_UPDATE_COMMIT, FEATURE_COMMIT})

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
    """Talks to the five bridge services, and to nothing else."""

    def __init__(self, adapter: RealHomeAssistantAdapter) -> None:
        self._adapter = adapter

    async def _payload(self, service: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._adapter._payload(service, data)

    # --- discovery --------------------------------------------------------
    async def status(self) -> ManagementStatus:
        """`script.bobi_cc_manage_contract`. Read-only.

        A bridge that cannot be reached, or that says it is not available, is
        reported as unavailable — never assumed present.
        """
        payload = await self._payload(CONTRACT)
        return _contract(payload)

    # --- reads ------------------------------------------------------------
    async def snapshot(self) -> TaskSnapshot:
        """`script.bobi_cc_task_snapshot`. Read-only."""
        return _snapshot(await self._payload(TASK_SNAPSHOT))

    async def observe(self, resource_type: str, resource_id: str | None) -> ObservedState | None:
        """The current state a preview binds to, read fresh from the bridge."""
        if resource_type == "tasks":
            if resource_id is None:
                # Adding a task binds to nothing that exists yet.
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
            # The bridge must report the current state: it compares against it
            # immediately before acting, so an unknown state is not previewable.
            if target is None or target.enabled is None:
                return None
            return ObservedState(
                resource_id=target.id,
                label=target.label,
                values={"state": "on" if target.enabled else "off", "enabled": target.enabled},
            )

        return None

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
        """One declared operation, mapped onto one declared service."""
        # Every commit service requires the token. A blank one is a bug on this
        # side, and Home Assistant would reject the call anyway — so it is
        # caught here, before a request is built, rather than being sent for the
        # bridge to refuse.
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
        raise _unsupported(resource_type, operation)

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
                # The bridge accepts an empty string for "no date".
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
            # Straight from what the preview observed — never from the client,
            # and never re-read here, or the staleness check would be pointless.
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


def _unsupported(resource_type: str, operation: str):
    from app.errors import BobiError

    return BobiError(
        "הפעולה הזו אינה נתמכת על ידי הגשר של בובי",
        code="operation_not_supported",
        status_code=422,
        details={"resource": resource_type, "operation": operation},
    )


def _missing_token(resource_type: str, operation: str):
    """No token, no request. The message stays the same as a stale preview's.

    From the screen's point of view the situation is identical — the change was
    not made and the preview has to be taken again — and there is nothing a
    household member could do differently if told which of the two it was.
    """
    from app.errors import BobiError

    return BobiError(
        "התצוגה המקדימה כבר אינה בתוקף. בצעו תצוגה מקדימה מחדש.",
        code="preview_token_missing",
        status_code=409,
        details={"resource": resource_type, "operation": operation},
    )


# --- normalization ----------------------------------------------------------
# The same rule as everywhere else: this is the only layer that knows the
# bridge's field names, and it never raises on a missing or odd one.
def _bool(value: Any) -> bool | None:
    return normalize._bool(value)


def _text(value: Any) -> str | None:
    return normalize._text(value)


def _contract(payload: dict[str, Any]) -> ManagementStatus:
    """`bobi_cc_manage_contract` → the canonical management status."""
    available = _bool(payload.get("bridge_available"))
    writes_enabled = bool(_bool(payload.get("writes_enabled")))

    resources: list[ManagementResource] = []

    tasks = payload.get("tasks")
    if isinstance(tasks, dict):
        supported = bool(_bool(tasks.get("supported")))
        operations = [
            ManagedOperation(
                id=name,
                label=_TASK_OPERATION_LABELS.get(name, name),
                destructive=name == "delete",
            )
            for name in normalize._str_list(tasks.get("operations"))
            # An operation this application does not implement is ignored rather
            # than offered: the closed set is the contract on both sides.
            if name in TASK_OPERATIONS
        ]
        resources.append(
            ManagementResource(
                id="tasks",
                label="משימות",
                available=supported and available is not False,
                operations=operations,
                targets=[
                    ManagedTarget(id=user_id, label=name)
                    for item in normalize._as_items(tasks.get("users"))
                    if (user_id := _text(item.get("id")))
                    and (name := _text(item.get("name")) or user_id)
                ],
            )
        )

    features = payload.get("features")
    if isinstance(features, dict):
        supported = bool(_bool(features.get("supported")))
        targets = [
            ManagedTarget(
                id=feature_id,
                label=_text(item.get("label")) or feature_id,
                risk=_text(item.get("risk")),
                # Absent today. Read tolerantly so it works the moment the
                # bridge starts reporting it — and blocks a preview until then,
                # rather than guessing.
                enabled=_bool(normalize._first(item, "enabled", "state", "value")),
            )
            for item in normalize._as_items(features.get("items"))
            if (feature_id := _text(item.get("id")))
        ]
        resources.append(
            ManagementResource(
                id="features",
                label="תכונות",
                available=supported and available is not False,
                operations=[ManagedOperation(id="set", label="הפעלה או כיבוי")],
                targets=targets,
            )
        )

    return ManagementStatus(
        available=bool(available),
        reason=None if available else UNAVAILABLE_MESSAGE,
        contract_version=_text(payload.get("contract_version")),
        resources=resources,
        writes_enabled=writes_enabled,
        # Defaulting to True: a bridge that omits these is not granting
        # permission to skip a step.
        requires_preview=_bool(payload.get("requires_preview")) is not False,
        requires_confirmation=_bool(payload.get("requires_confirmation")) is not False,
        requires_read_after_write=_bool(payload.get("requires_read_after_write")) is not False,
    )


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
    """A commit response → the canonical outcome.

    `verified` stays `None` when the bridge did not say, so an unverified write
    is never reported as a verified one.
    """
    return BridgeOutcome(
        executed=bool(_bool(payload.get("executed"))),
        verified=_bool(payload.get("verified")),
        reason=_text(payload.get("reason")),
        resource_id=_text(normalize._first(payload, "uid", "feature_id", "resource_id")),
        writes_enabled=bool(_bool(payload.get("writes_enabled"))),
    )
