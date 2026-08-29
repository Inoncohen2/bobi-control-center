"""Mock adapter for local development and tests.

It emits raw payloads in the **real** bridge shape and runs them through the
same normalizer as the real adapter, so mock mode exercises the identical code
path rather than a parallel one.

There is no HTTP client here at all, which makes it structurally incapable of
reaching a real system — a property asserted by the test suite.
"""

from __future__ import annotations

import struct
import zlib

from app.adapters.base import HomeAssistantAdapter
from app.mock import bridge_data
from app.mock.management import DEFAULT_RESOURCE_PAYLOADS
from app.models.bridge import (
    BridgeCapabilities,
    BridgeDevices,
    BridgeDiagnostics,
    BridgeProbe,
    BridgeRules,
    BridgeShabbat,
    BridgeStatus,
    BridgeTasks,
    BridgeUsers,
    CameraFrame,
    ConnectionInfo,
)
from app.services import camera, normalize
from app.version import APP_VERSION


class MockHomeAssistantAdapter(HomeAssistantAdapter):
    """Deterministic demo data in the exact shape of the bridge."""

    name = "mock"
    unrestricted_writes = False

    async def connection_info(self) -> ConnectionInfo:
        return ConnectionInfo(
            adapter=self.name,
            app_version=APP_VERSION,
            connected=True,
            writes_enabled=False,
            detail="מצב הדגמה — הנתונים מדומים ואין חיבור למערכת אמיתית",
        )

    async def get_status(self) -> BridgeStatus:
        return normalize.normalize_status(bridge_data.status_payload())

    async def get_devices(
        self, scope: str = "all", include_unavailable: bool = True
    ) -> BridgeDevices:
        payload = bridge_data.devices_payload(scope, include_unavailable)
        return normalize.normalize_devices(payload, scope, include_unavailable)

    async def camera_frame(self, camera_id: str) -> CameraFrame:
        """A placeholder frame, resolved through the real whitelist.

        The picture is invented, but the decision about *which* camera may be
        fetched is not: it runs `services/camera.resolve` against the double's
        own catalogue, so mock mode exercises the rule that refuses an unknown
        id and the rule that refuses a canonical id pointing at something which
        is not a camera. A double that simply returned bytes for any string
        would leave both untested in every test that uses it.
        """
        camera.resolve(DEFAULT_RESOURCE_PAYLOADS["devices"], camera_id)
        return CameraFrame(image=_placeholder(), content_type="image/png")

    async def get_capabilities(self) -> BridgeCapabilities:
        return normalize.normalize_capabilities(bridge_data.capabilities_payload())

    async def get_users(self) -> BridgeUsers:
        return normalize.normalize_users(bridge_data.users_payload())

    async def get_shabbat(self) -> BridgeShabbat:
        return normalize.normalize_shabbat(bridge_data.shabbat_payload())

    async def get_rules(self) -> BridgeRules:
        return normalize.normalize_rules(bridge_data.rules_payload())

    async def get_tasks(self) -> BridgeTasks:
        return normalize.normalize_tasks(bridge_data.tasks_payload())

    async def get_diagnostics(self) -> BridgeDiagnostics:
        return normalize.normalize_diagnostics(bridge_data.diagnostics_payload())

    async def probe(self, text: str) -> BridgeProbe:
        return normalize.normalize_probe(bridge_data.probe_payload(text), text)


def _placeholder() -> bytes:
    """A small slate-grey PNG, built rather than pasted.

    Demo mode needs *a* picture so the camera screen can be looked at without a
    house attached. Generating it keeps a kilobyte of base64 out of the source
    and makes the size and colour something a reader can see at a glance.
    """
    width, height = 320, 180
    pixel = b"\x2f\x37\x46"
    raw = b"".join(b"\x00" + pixel * width for _ in range(height))

    def chunk(tag: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + tag
            + body
            + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
