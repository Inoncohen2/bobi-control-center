"""Management endpoints — all writes remain bridge-bound and fail closed.

There is no route here that can reach a Home Assistant service by name: the
resource is one of a closed set, the operation is one of a closed set, and the
live bridge decides what either means.
"""

from __future__ import annotations

from fastapi import APIRouter, Path, Query

from app.api.deps import ActorDep, ManagementDep
from app.errors import NotFoundError
from app.models.manage import (
    FEATURE_OPERATIONS,
    MANAGED_RESOURCES,
    TASK_OPERATIONS,
    AuditLog,
    BridgeContract,
    CommitRequest,
    CommitResponse,
    ManagementStatus,
    PreviewRequest,
    PreviewResponse,
    ResourceSnapshot,
    TaskSnapshot,
)
from app.services.bridge_report import build_bridge_contract
from app.services.resources import SPECS, canonical_operation

router = APIRouter(prefix="/api/bobi/manage", tags=["manage"])

#: Rejected before any service is consulted, so a new resource cannot be
#: managed by guessing its name in a URL.
_RESOURCE = Path(description="One of the managed resources.")


def _check(resource: str) -> str:
    if resource not in MANAGED_RESOURCES:
        raise NotFoundError(
            "המשאב הזה אינו נתמך לניהול",
            details={"resource": resource, "allowed": list(MANAGED_RESOURCES)},
        )
    return resource


@router.get("/contract", response_model=ManagementStatus, summary="חוזה הניהול")
async def get_management_contract(service: ManagementDep) -> ManagementStatus:
    """`script.bobi_cc_manage_contract` — what may be managed, and whether writes are on.

    Read-only, and the only place `writes_enabled` comes from. Nothing in
    configuration can turn management on, and **no endpoint anywhere in this
    application can set Home Assistant's master write switch** — it is reported
    and never written.
    """
    return await service.status()


@router.get("/bridge-drift", summary="בדיקת התאמה בין החוזה החי לבילד")
async def get_bridge_drift(service: ManagementDep) -> dict[str, object]:
    """Compare the live Home Assistant vocabulary with what this build understands.

    This is deliberately a read-only runtime check. A stale copied fixture can
    still pass CI; the live contract cannot. Unknown resources or verbs are
    therefore surfaced here instead of being silently dropped by the closed-set
    filter. Missing snapshot/commit services come from the same live comparison
    as the bridge-contract screen.
    """
    status = await service.status()
    report = await build_bridge_contract(service)

    unknown_resources: list[str] = []
    unknown_operations: list[str] = []
    known_special = {
        "tasks": set(TASK_OPERATIONS),
        "features": set(FEATURE_OPERATIONS),
    }

    for resource in status.resources:
        if resource.id in SPECS:
            allowed = set(SPECS[resource.id].operations)
            for operation in resource.operations:
                canonical = canonical_operation(resource.id, operation.id)
                if canonical not in allowed:
                    unknown_operations.append(f"{resource.id}.{operation.id}")
            continue

        if resource.id in known_special:
            allowed = known_special[resource.id]
            for operation in resource.operations:
                if operation.id not in allowed:
                    unknown_operations.append(f"{resource.id}.{operation.id}")
            continue

        unknown_resources.append(resource.id)

    unknown_resources = sorted(set(unknown_resources))
    unknown_operations = sorted(set(unknown_operations))
    missing_services = sorted(set(report.missing))

    return {
        "ok": not unknown_resources and not unknown_operations,
        "contract_available": status.available,
        "contract_version": status.contract_version,
        "unknown_resources": unknown_resources,
        "unknown_operations": unknown_operations,
        "missing_services": missing_services,
        "writes_enabled": status.writes_enabled,
    }


@router.get(
    "/tasks/snapshot", response_model=TaskSnapshot, summary="משימות פתוחות והושלמו"
)
async def get_task_snapshot(service: ManagementDep) -> TaskSnapshot:
    """`script.bobi_cc_task_snapshot`. Read-only.

    The list a preview binds to. Carries the bridge's own task `uid`, never a
    Home Assistant `todo.*` entity id — the bridge does not send one, and this
    application must not infer one.
    """
    return await service.snapshot()


@router.get(
    "/{resource}/snapshot",
    response_model=ResourceSnapshot,
    summary="מצב נוכחי של משאב מנוהל",
)
async def get_resource_snapshot(
    service: ManagementDep,
    resource: str = _RESOURCE,
) -> ResourceSnapshot:
    """One family's current state, from its own `bobi_cc_*` read service.

    A family whose bridge has not shipped answers `available: false` with a
    Hebrew reason and a 200, not an error. There is no second path to this data,
    and none may be added.

    `tasks` keeps its own richer endpoint above; asking for it here is refused
    rather than answered in a shape that would lose the open/completed split.
    """
    checked = _check(resource)
    if checked in ("tasks", "features"):
        raise NotFoundError(
            "למשאב הזה יש נקודת קצה משלו",
            details={"resource": checked, "endpoint": "/api/bobi/manage/tasks/snapshot"},
        )
    return await service.resource_snapshot(checked)


@router.post(
    "/{resource}/preview", response_model=PreviewResponse, summary="תצוגה מקדימה של שינוי"
)
async def preview_change(
    service: ManagementDep,
    actor: ActorDep,
    request: PreviewRequest,
    resource: str = _RESOURCE,
) -> PreviewResponse:
    """Describe a change without making it.

    This path performs no write. The response carries a single-use id that the
    matching commit requires, and it is refused outright when the session's role
    is below what the change's risk needs.
    """
    return await service.preview(_check(resource), request, actor)


@router.post("/{resource}/commit", response_model=CommitResponse, summary="ביצוע שינוי")
async def commit_change(
    service: ManagementDep,
    actor: ActorDep,
    request: CommitRequest,
    resource: str = _RESOURCE,
) -> CommitResponse:
    """Apply a change the user previewed and confirmed, then read it back."""
    return await service.commit(_check(resource), request, actor)


@router.get(
    "/bridge-contract",
    response_model=BridgeContract,
    summary="מה כל גשר bobi_cc_* צריך לקבל ולהחזיר",
)
async def get_bridge_contract(service: ManagementDep) -> BridgeContract:
    """The specification every `script.bobi_cc_*` must satisfy, from this build.

    `implemented` and `missing` are computed against the **live** contract: a
    family the bridge does not declare, or declares with no operations, shows
    its commit service as missing.
    """
    return await build_bridge_contract(service)


@router.get("/audit", response_model=AuditLog, summary="יומן שינויים")
async def get_audit(
    service: ManagementDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> AuditLog:
    """Recent previews and commits, newest first. Carries no personal detail."""
    return service.audit(limit=limit)
