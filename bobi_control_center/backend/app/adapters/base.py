"""The single seam between this application and Home Assistant.

Phase 2 narrows the interface to exactly the Bobi Control Center bridge: one
method per `script.bobi_cc_*` service, and nothing else. There is deliberately
no write method on this interface — an adapter cannot expose one without
changing this file, which makes the read-only guarantee structural rather than
a matter of discipline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

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


class HomeAssistantAdapter(ABC):
    """Read-only contract over Bobi's bridge services."""

    #: Identifies the implementation in `/health` and the settings screen.
    name: str = "abstract"

    #: Phase 2 invariant. No implementation may set this True.
    writes_enabled: bool = False

    # --- lifecycle --------------------------------------------------------
    async def aclose(self) -> None:
        """Release any client resources. No-op unless overridden."""

    @abstractmethod
    async def connection_info(self) -> ConnectionInfo:
        """Describe the current data source. Must never include a token."""

    # --- bridge services --------------------------------------------------
    @abstractmethod
    async def get_status(self) -> BridgeStatus:
        """`script.bobi_cc_status`."""

    @abstractmethod
    async def get_devices(
        self, scope: str = "all", include_unavailable: bool = True
    ) -> BridgeDevices:
        """`script.bobi_cc_devices`."""

    @abstractmethod
    async def get_capabilities(self) -> BridgeCapabilities:
        """`script.bobi_cc_capabilities` — the canonical Capability Registry."""

    @abstractmethod
    async def get_users(self) -> BridgeUsers:
        """`script.bobi_cc_users`. Never contains phone numbers or LIDs."""

    @abstractmethod
    async def get_shabbat(self) -> BridgeShabbat:
        """`script.bobi_cc_shabbat`. Read-only in Phase 2."""

    @abstractmethod
    async def get_rules(self) -> BridgeRules:
        """`script.bobi_cc_rules` — Bobi's canonical smart rules."""

    @abstractmethod
    async def get_tasks(self) -> BridgeTasks:
        """`script.bobi_cc_tasks`. Internal metadata is stripped by the bridge."""

    @abstractmethod
    async def get_diagnostics(self) -> BridgeDiagnostics:
        """`script.bobi_cc_diagnostics`."""

    @abstractmethod
    async def probe(self, text: str) -> BridgeProbe:
        """`script.bobi_cc_probe`.

        The bridge invokes Bobi's Skill Dispatcher with `probe_only=true`, so
        this inspects text without acting on it. Implementations must not add
        any execution path.
        """
