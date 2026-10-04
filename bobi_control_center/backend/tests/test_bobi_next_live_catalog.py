from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.bobi_next.conditional import StateChangeEvent
from app.bobi_next.live_catalog import LiveDeviceCatalog
from app.bobi_next.models import DeviceRecord, EntityRecord


@dataclass
class FakeSnapshot:
    devices: tuple[DeviceRecord, ...]

    def semantic_devices(self) -> tuple[DeviceRecord, ...]:
        return self.devices


class FakeDiscovery:
    def __init__(self, snapshots: list[FakeSnapshot]) -> None:
        self.snapshots = snapshots
        self.calls = 0

    async def snapshot(self) -> FakeSnapshot:
        index = min(self.calls, len(self.snapshots) - 1)
        self.calls += 1
        return self.snapshots[index]


def _climate(entity_id: str, temperature: float = 23.0) -> DeviceRecord:
    entity = EntityRecord(
        entity_id=entity_id,
        domain="climate",
        unique_id="climate-1",
        platform="test",
        device_id="device-1",
        state="cool",
        attributes={
            "temperature": temperature,
            "min_temp": 16,
            "max_temp": 30,
            "target_temp_step": 0.5,
            "hvac_modes": ["off", "cool", "heat"],
        },
        available=True,
        capabilities=frozenset({"power", "temperature", "hvac_mode"}),
        limits={"min_temp": 16, "max_temp": 30, "temp_step": 0.5},
    )
    return DeviceRecord(
        bobi_id="bobi-device-1",
        stable_key="device:device-1",
        ha_device_id="device-1",
        name="Room AC",
        entities=(entity,),
        capabilities=entity.capabilities,
        available=True,
    )


@pytest.mark.asyncio
async def test_catalog_refreshes_once_then_overlays_state_events() -> None:
    discovery = FakeDiscovery([FakeSnapshot((_climate("climate.room"),))])
    catalog = LiveDeviceCatalog(discovery, refresh_seconds=300)

    first = await catalog.get_devices()
    second = await catalog.get_devices()
    assert discovery.calls == 1
    assert first is second

    await catalog.apply_state_event(
        StateChangeEvent(
            event_id="evt-1",
            entity_id="climate.room",
            old_state="cool",
            new_state="heat",
            old_attributes={"temperature": 23.0},
            new_attributes={
                "temperature": 24.5,
                "min_temp": 16,
                "max_temp": 30,
                "target_temp_step": 0.5,
                "hvac_modes": ["off", "cool", "heat"],
                "fan_modes": ["auto", "high"],
            },
            occurred_ts=10,
        )
    )

    devices = await catalog.get_devices()
    entity = devices[0].entities[0]
    assert discovery.calls == 1
    assert entity.state == "heat"
    assert entity.attributes["temperature"] == 24.5
    assert entity.limits["temp_step"] == 0.5
    assert "fan_mode" in entity.capabilities
    assert "fan_mode" in devices[0].capabilities


@pytest.mark.asyncio
async def test_unknown_entity_event_forces_registry_refresh() -> None:
    first = FakeSnapshot((_climate("climate.old_name"),))
    second = FakeSnapshot((_climate("climate.new_name"),))
    discovery = FakeDiscovery([first, second])
    catalog = LiveDeviceCatalog(discovery, refresh_seconds=300)
    await catalog.refresh()

    await catalog.apply_state_event(
        StateChangeEvent(
            event_id="evt-rename",
            entity_id="climate.new_name",
            old_state="cool",
            new_state="cool",
            old_attributes={},
            new_attributes={"temperature": 22.5},
            occurred_ts=20,
        )
    )

    devices = await catalog.get_devices()
    assert discovery.calls == 2
    assert devices[0].entities[0].entity_id == "climate.new_name"


@pytest.mark.asyncio
async def test_unavailable_event_updates_semantic_device_availability() -> None:
    discovery = FakeDiscovery([FakeSnapshot((_climate("climate.room"),))])
    catalog = LiveDeviceCatalog(discovery)
    await catalog.refresh()

    await catalog.apply_state_event(
        StateChangeEvent(
            event_id="evt-offline",
            entity_id="climate.room",
            old_state="cool",
            new_state="unavailable",
            old_attributes={},
            new_attributes={},
            occurred_ts=30,
        )
    )

    devices = await catalog.get_devices()
    assert devices[0].available is False
    assert devices[0].entities[0].available is False
