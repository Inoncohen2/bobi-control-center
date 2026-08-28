"""The Bobi Control Center API.

One endpoint per bridge service. Every route is a read or a probe — Phase 2
exposes no write path at all, and the adapter interface has none to expose.
"""

from __future__ import annotations

from fastapi import APIRouter, Path, Query, Response
from pydantic import BaseModel, Field

from app.api.deps import AdapterDep
from app.errors import ValidationError
from app.models.bridge import (
    DEVICE_SCOPES,
    BridgeCapabilities,
    BridgeDevices,
    BridgeDiagnostics,
    BridgeProbe,
    BridgeRules,
    BridgeShabbat,
    BridgeStatus,
    BridgeTasks,
    BridgeUsers,
    ConnectionInfo,
)

router = APIRouter(prefix="/api/bobi", tags=["bobi"])


class ProbeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


@router.get("/connection", response_model=ConnectionInfo, summary="מצב החיבור")
async def get_connection(adapter: AdapterDep) -> ConnectionInfo:
    """Whether the app is showing real data or demo data. Contains no secret."""
    return await adapter.connection_info()


@router.get("/status", response_model=BridgeStatus, summary="מצב המערכת")
async def get_status(adapter: AdapterDep) -> BridgeStatus:
    return await adapter.get_status()


@router.get("/devices", response_model=BridgeDevices, summary="מכשירים")
async def get_devices(
    adapter: AdapterDep,
    scope: str = Query(default="all", description="One of the bridge's semantic scopes."),
    include_unavailable: bool = Query(default=True),
) -> BridgeDevices:
    if scope not in DEVICE_SCOPES:
        raise ValidationError(
            "קטגוריית מכשירים לא מוכרת",
            details={"scope": scope, "allowed": list(DEVICE_SCOPES)},
        )
    return await adapter.get_devices(scope=scope, include_unavailable=include_unavailable)


@router.get("/capabilities", response_model=BridgeCapabilities, summary="יכולות")
async def get_capabilities(adapter: AdapterDep) -> BridgeCapabilities:
    """Bobi's canonical Capability Registry, rendered dynamically by the UI."""
    return await adapter.get_capabilities()


@router.get("/users", response_model=BridgeUsers, summary="משתמשים")
async def get_users(adapter: AdapterDep) -> BridgeUsers:
    """Household members. The bridge withholds phone numbers and LIDs."""
    return await adapter.get_users()


@router.get("/shabbat", response_model=BridgeShabbat, summary="שעון שבת")
async def get_shabbat(adapter: AdapterDep) -> BridgeShabbat:
    """Read-only in Phase 2: `writes_enabled` is always False."""
    return await adapter.get_shabbat()


@router.get("/rules", response_model=BridgeRules, summary="כללים חכמים")
async def get_rules(adapter: AdapterDep) -> BridgeRules:
    return await adapter.get_rules()


@router.get("/tasks", response_model=BridgeTasks, summary="משימות")
async def get_tasks(adapter: AdapterDep) -> BridgeTasks:
    return await adapter.get_tasks()


@router.get("/diagnostics", response_model=BridgeDiagnostics, summary="תקלות")
async def get_diagnostics(adapter: AdapterDep) -> BridgeDiagnostics:
    return await adapter.get_diagnostics()


@router.post("/probe", response_model=BridgeProbe, summary="בדיקה בלבד")
async def probe(payload: ProbeRequest, adapter: AdapterDep) -> BridgeProbe:
    """Run text through Bobi's dispatcher with `probe_only=true`.

    Nothing is executed. `would_execute` is False in every response.
    """
    return await adapter.probe(payload.text)


@router.get(
    "/cameras/{camera_id}/snapshot",
    summary="תמונה מהמצלמה",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}, "description": "תמונה מהמצלמה"}},
)
async def get_camera_snapshot(
    adapter: AdapterDep,
    camera_id: str = Path(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9_]+$",
        description="The camera's canonical id — never a Home Assistant entity id.",
    ),
) -> Response:
    """One still picture, fetched by this application and passed through.

    The browser names a canonical id and receives bytes. It never learns the
    entity id behind the camera, and it never receives a credential: the
    `entity_picture` URL Home Assistant publishes carries the camera's own
    access token, and that token is not read here and does not leave the
    server.

    `no-store` matters more than the bandwidth it costs. A camera frame is a
    picture of the inside of a house, and a shared cache or a browser's
    back-button cache is not where it should be able to reappear.

    The pattern on `camera_id` is a second lock behind the catalogue whitelist:
    it admits only the shape a canonical id has, so a path traversal or an
    entity id with a dot in it is rejected before any lookup happens.
    """
    frame = await adapter.camera_frame(camera_id)
    return Response(
        content=frame.image,
        media_type=frame.content_type,
        headers={"Cache-Control": "no-store, private", "X-Content-Type-Options": "nosniff"},
    )
