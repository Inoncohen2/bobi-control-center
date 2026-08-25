"""Management endpoints — Phase 3A.

Four routes per resource shape, and every one of them refuses unless Home
Assistant has declared a write bridge. There is no route here that can reach a
Home Assistant service by name: the resource is one of a closed set, the
operation is one of a closed set, and the bridge decides what either means.
"""

from __future__ import annotations

from fastapi import APIRouter, Path, Query

from app.api.deps import ManagementDep
from app.errors import NotFoundError
from app.models.manage import (
    MANAGED_RESOURCES,
    AuditLog,
    CommitRequest,
    CommitResponse,
    ManagementStatus,
    PreviewRequest,
    PreviewResponse,
)

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


@router.get("/status", response_model=ManagementStatus, summary="מצב הניהול")
async def get_management_status(service: ManagementDep) -> ManagementStatus:
    """Whether management is available, discovered from the bridge.

    Nothing in configuration can turn this on — if Home Assistant has not
    declared a write bridge, this reports unavailable and every other route
    below refuses.
    """
    return await service.status()


@router.post(
    "/{resource}/preview", response_model=PreviewResponse, summary="תצוגה מקדימה של שינוי"
)
async def preview_change(
    service: ManagementDep,
    request: PreviewRequest,
    resource: str = _RESOURCE,
) -> PreviewResponse:
    """Describe a change without making it.

    This path performs no write. The response carries a single-use id that the
    matching commit requires.
    """
    return await service.preview(_check(resource), request)


@router.post("/{resource}/commit", response_model=CommitResponse, summary="ביצוע שינוי")
async def commit_change(
    service: ManagementDep,
    request: CommitRequest,
    resource: str = _RESOURCE,
) -> CommitResponse:
    """Apply a change the user previewed and confirmed, then read it back."""
    return await service.commit(_check(resource), request)


@router.get("/audit", response_model=AuditLog, summary="יומן שינויים")
async def get_audit(
    service: ManagementDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> AuditLog:
    """Recent previews and commits, newest first. Carries no personal detail."""
    return service.audit(limit=limit)
