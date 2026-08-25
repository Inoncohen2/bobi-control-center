"""Mock adapter for local development and tests.

It emits raw payloads in the **real** bridge shape and runs them through the
same normalizer as the real adapter, so mock mode exercises the identical code
path rather than a parallel one.

There is no HTTP client here at all, which makes it structurally incapable of
reaching a real system — a property asserted by the test suite.
"""

from __future__ import annotations

from app.adapters.base import HomeAssistantAdapter
from app.mock import bridge_data
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
    ConnectionInfo,
)
from app.services import normalize


class MockHomeAssistantAdapter(HomeAssistantAdapter):
    """Deterministic demo data in the exact shape of the bridge."""

    name = "mock"
    writes_enabled = False

    async def connection_info(self) -> ConnectionInfo:
        return ConnectionInfo(
            adapter=self.name,
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
