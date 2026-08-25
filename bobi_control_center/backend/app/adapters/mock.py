"""Mock adapter for local development and tests.

Returns the same bridge shapes as the real adapter, so the UI and the models are
exercised identically without a Home Assistant instance. It contains no HTTP
client at all, which makes it structurally incapable of reaching a real system —
a property asserted by the test suite.
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
        return BridgeStatus.model_validate(bridge_data.status_payload())

    async def get_devices(
        self, scope: str = "all", include_unavailable: bool = True
    ) -> BridgeDevices:
        return BridgeDevices.model_validate(
            bridge_data.devices_payload(scope, include_unavailable)
        )

    async def get_capabilities(self) -> BridgeCapabilities:
        return BridgeCapabilities.model_validate(bridge_data.capabilities_payload())

    async def get_users(self) -> BridgeUsers:
        return BridgeUsers.model_validate(bridge_data.users_payload())

    async def get_shabbat(self) -> BridgeShabbat:
        return BridgeShabbat.model_validate(bridge_data.shabbat_payload())

    async def get_rules(self) -> BridgeRules:
        return BridgeRules.model_validate(bridge_data.rules_payload())

    async def get_tasks(self) -> BridgeTasks:
        return BridgeTasks.model_validate(bridge_data.tasks_payload())

    async def get_diagnostics(self) -> BridgeDiagnostics:
        return BridgeDiagnostics.model_validate(bridge_data.diagnostics_payload())

    async def probe(self, text: str) -> BridgeProbe:
        result = BridgeProbe.model_validate(bridge_data.probe_payload(text))
        result.probe_only = True
        result.would_execute = False
        return result
