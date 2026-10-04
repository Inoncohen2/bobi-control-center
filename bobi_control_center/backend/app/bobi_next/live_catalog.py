"""Low-cost live semantic device catalogue for Bobi Next runtimes.

A full Home Assistant discovery snapshot is expensive because it includes the
entity/device/area registries.  The catalogue takes that snapshot at startup and
periodically, then overlays every `state_changed` event in memory.  This keeps
relative planning current without opening a new registry WebSocket for every
state event.
"""

from __future__ import annotations

import asyncio
import time
from typing import Protocol

from .capabilities import infer_capabilities
from .conditional import StateChangeEvent
from .ha_discovery import DiscoverySnapshot
from .models import DeviceRecord, EntityRecord


class DiscoveryProvider(Protocol):
    async def snapshot(self) -> DiscoverySnapshot: ...


class LiveDeviceCatalog:
    def __init__(
        self,
        discovery: DiscoveryProvider,
        *,
        refresh_seconds: float = 300.0,
    ) -> None:
        self.discovery = discovery
        self.refresh_seconds = max(5.0, float(refresh_seconds))
        self._devices: tuple[DeviceRecord, ...] = ()
        self._last_refresh = 0.0
        self._refresh_lock = asyncio.Lock()
        self._data_lock = asyncio.Lock()

    async def refresh(self) -> tuple[DeviceRecord, ...]:
        async with self._refresh_lock:
            snapshot = await self.discovery.snapshot()
            devices = snapshot.semantic_devices()
            async with self._data_lock:
                self._devices = devices
                self._last_refresh = time.monotonic()
                return self._devices

    async def get_devices(self) -> tuple[DeviceRecord, ...]:
        now = time.monotonic()
        if not self._devices or now - self._last_refresh >= self.refresh_seconds:
            return await self.refresh()
        async with self._data_lock:
            return self._devices

    @staticmethod
    def _update_entity(entity: EntityRecord, event: StateChangeEvent) -> None:
        entity.state = str(event.new_state) if event.new_state is not None else "unknown"
        entity.attributes = dict(event.new_attributes)
        entity.available = entity.state not in {"unknown", "unavailable"}
        capabilities, limits = infer_capabilities(entity.domain, entity.attributes)
        entity.capabilities = capabilities
        entity.limits = limits

    @staticmethod
    def _recompute_device(device: DeviceRecord) -> None:
        caps: set[str] = set()
        available = False
        for entity in device.entities:
            caps.update(entity.capabilities)
            available = available or entity.available
        device.capabilities = frozenset(caps)
        device.available = available

    async def apply_state_event(self, event: StateChangeEvent) -> None:
        """Overlay one live HA event; unknown entities trigger a registry refresh."""

        found = False
        async with self._data_lock:
            for device in self._devices:
                for entity in device.entities:
                    if entity.entity_id != event.entity_id:
                        continue
                    self._update_entity(entity, event)
                    self._recompute_device(device)
                    found = True
                    break
                if found:
                    break
        if not found:
            # A newly created or renamed entity is exactly when the cached
            # registries are no longer authoritative. Refresh outside the data
            # lock so network I/O never blocks readers holding it.
            await self.refresh()
