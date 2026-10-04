from __future__ import annotations

import pytest

from app.bobi_next.ha_discovery import DiscoverySnapshot
from app.bobi_next.memory import BobiMemory
from app.bobi_next.shadow import ShadowRequest, run_shadow


class FakeDiscovery:
    def __init__(self, snapshot: DiscoverySnapshot) -> None:
        self._snapshot = snapshot
        self.calls = 0

    async def snapshot(self) -> DiscoverySnapshot:
        self.calls += 1
        return self._snapshot


def _snapshot() -> DiscoverySnapshot:
    return DiscoverySnapshot(
        states=[
            {
                "entity_id": "climate.master_ac",
                "state": "cool",
                "attributes": {
                    "friendly_name": "Master AC",
                    "temperature": 23.0,
                    "min_temp": 16,
                    "max_temp": 30,
                    "target_temp_step": 0.5,
                    "hvac_modes": ["off", "cool", "heat"],
                },
            },
            {
                "entity_id": "light.kitchen_ceiling",
                "state": "on",
                "attributes": {
                    "friendly_name": "Kitchen ceiling",
                    "brightness": 128,
                    "supported_color_modes": ["brightness"],
                },
            },
        ],
        entities=[
            {
                "entity_id": "climate.master_ac",
                "unique_id": "ac-1",
                "platform": "example",
                "device_id": "dev-ac",
                "area_id": "bedroom",
            },
            {
                "entity_id": "light.kitchen_ceiling",
                "unique_id": "light-1",
                "platform": "example",
                "device_id": "dev-light",
                "area_id": "kitchen",
            },
        ],
        devices=[
            {"id": "dev-ac", "name": "Bedroom air conditioner", "area_id": "bedroom"},
            {"id": "dev-light", "name": "Kitchen ceiling light", "area_id": "kitchen"},
        ],
        areas=[
            {"area_id": "bedroom", "name": "Bedroom"},
            {"area_id": "kitchen", "name": "Kitchen"},
        ],
    )


@pytest.mark.asyncio
async def test_shadow_plans_half_degree_without_executing(tmp_path):
    discovery = FakeDiscovery(_snapshot())
    memory = BobiMemory(tmp_path / "bobi.db")
    try:
        result = await run_shadow(
            ShadowRequest(
                request_id="m1",
                user_key="user-1",
                text="Bedroom air conditioner",
                domain_hint="climate",
                capability="temperature",
                operation="set",
                delta=0.5,
            ),
            discovery=discovery,
            memory=memory,
        )

        assert result.ok
        assert result.reason == "planned"
        assert result.discovered_devices == 2
        assert len(result.plans) == 1
        assert result.plans[0].entity_id == "climate.master_ac"
        assert result.plans[0].action == "set_temperature"
        assert result.plans[0].data["temperature"] == 23.5
        assert result.metadata["shadow"] is True
        assert result.metadata["executes_home_assistant"] is False
        assert discovery.calls == 1
    finally:
        memory.close()


@pytest.mark.asyncio
async def test_shadow_uses_persisted_context_for_followup(tmp_path):
    discovery = FakeDiscovery(_snapshot())
    memory = BobiMemory(tmp_path / "bobi.db")
    try:
        first = await run_shadow(
            ShadowRequest(
                request_id="m1",
                user_key="user-1",
                text="Bedroom air conditioner",
                domain_hint="climate",
                capability="temperature",
                operation="set",
                delta=0.5,
            ),
            discovery=discovery,
            memory=memory,
        )
        assert first.ok

        followup = await run_shadow(
            ShadowRequest(
                request_id="m2",
                user_key="user-1",
                text="עוד קצת",
                domain_hint="climate",
                capability="temperature",
                operation="set",
                delta=0.5,
            ),
            discovery=discovery,
            memory=memory,
        )

        assert followup.ok
        assert followup.resolution.resolution_kind == "context"
        assert followup.plans[0].entity_id == "climate.master_ac"
        assert followup.plans[0].data["temperature"] == 23.5
    finally:
        memory.close()


@pytest.mark.asyncio
async def test_shadow_uses_learned_alias_from_local_memory(tmp_path):
    discovery = FakeDiscovery(_snapshot())
    memory = BobiMemory(tmp_path / "bobi.db")
    try:
        first = await run_shadow(
            ShadowRequest(
                request_id="m1",
                user_key="user-1",
                text="Bedroom air conditioner",
                domain_hint="climate",
                capability="temperature",
                operation="set",
                value=24,
            ),
            discovery=discovery,
            memory=memory,
        )
        assert first.ok
        memory.add_alias(first.plans[0].device_id, "my special cooler")

        learned = await run_shadow(
            ShadowRequest(
                request_id="m2",
                user_key="user-2",
                text="my special cooler",
                domain_hint="climate",
                capability="temperature",
                operation="set",
                value=22.5,
            ),
            discovery=discovery,
            memory=memory,
        )

        assert learned.ok
        assert learned.plans[0].entity_id == "climate.master_ac"
        assert learned.plans[0].data["temperature"] == 22.5
    finally:
        memory.close()


@pytest.mark.asyncio
async def test_shadow_fails_closed_when_area_target_is_ambiguous(tmp_path):
    snapshot = DiscoverySnapshot(
        states=[
            {"entity_id": "light.kitchen_left", "state": "off", "attributes": {}},
            {"entity_id": "light.kitchen_right", "state": "off", "attributes": {}},
        ],
        entities=[
            {
                "entity_id": "light.kitchen_left",
                "unique_id": "left",
                "platform": "example",
                "device_id": "left-device",
                "area_id": "kitchen",
            },
            {
                "entity_id": "light.kitchen_right",
                "unique_id": "right",
                "platform": "example",
                "device_id": "right-device",
                "area_id": "kitchen",
            },
        ],
        devices=[
            {"id": "left-device", "name": "Left lamp", "area_id": "kitchen"},
            {"id": "right-device", "name": "Right lamp", "area_id": "kitchen"},
        ],
        areas=[{"area_id": "kitchen", "name": "Kitchen"}],
    )
    memory = BobiMemory(tmp_path / "bobi.db")
    try:
        result = await run_shadow(
            ShadowRequest(
                request_id="m3",
                user_key="user-1",
                text="Kitchen",
                domain_hint="light",
                capability="power",
                operation="off",
            ),
            discovery=FakeDiscovery(snapshot),
            memory=memory,
        )

        assert not result.ok
        assert result.reason == "ambiguous_target"
        assert result.plans == ()
        assert result.resolution.ambiguous is True
    finally:
        memory.close()
