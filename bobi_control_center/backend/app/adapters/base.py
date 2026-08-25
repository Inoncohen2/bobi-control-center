"""The single seam between this application and Home Assistant.

Phase 2 narrowed this interface to exactly the Bobi Control Center bridge: one
method per `script.bobi_cc_*` service, and no write method at all.

Phase 3A keeps that discipline and adds one narrow door. There is still no
write method here. Instead `management_bridge()` returns an object that only a
Home Assistant write bridge can supply, and returns `None` — refusing every
write — unless one has. An adapter cannot acquire a write path by editing
itself; Home Assistant has to declare one.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.adapters.management import ManagementBridge
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

    #: Unrestricted writes. Still False in Phase 3A, for every implementation:
    #: management is per-operation and goes through the bridge below, never
    #: through a general permission to write.
    writes_enabled: bool = False

    # --- management -------------------------------------------------------
    def management_bridge(self) -> ManagementBridge | None:
        """The declared write path, or `None`.

        Concrete and defaulting to `None` on purpose: an adapter that does
        nothing gets no write path, and the API answers *"ניהול עדיין לא הופעל
        ב-Home Assistant"*. Overriding this is the only way to enable
        management, and an override is only correct once Home Assistant
        actually declares the contract.
        """
        return None

    # --- lifecycle --------------------------------------------------------
    async def aclose(self) -> None:  # noqa: B027 - optional hook, not abstract
        """Release any client resources.

        Deliberately concrete and empty: only an adapter that holds a network
        client needs to close anything, and the mock must not be forced to
        implement a no-op.
        """

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
