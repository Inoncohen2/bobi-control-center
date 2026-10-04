from __future__ import annotations

from app.bobi_next.memory import BobiMemory
from app.bobi_next.planner import build_plan
from app.bobi_next.registry import build_registry
from app.bobi_next.resolver import resolve_target


def _fixture_registry():
    states = [
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
                "fan_modes": ["auto", "low", "high"],
            },
        },
        {
            "entity_id": "sensor.master_ac_temperature",
            "state": "24.1",
            "attributes": {"friendly_name": "Master AC Temperature"},
        },
        {
            "entity_id": "light.kitchen_ceiling",
            "state": "on",
            "attributes": {
                "friendly_name": "Kitchen Ceiling",
                "brightness": 128,
                "supported_color_modes": ["brightness"],
            },
        },
    ]
    entities = [
        {
            "entity_id": "climate.master_ac",
            "unique_id": "ac-1-climate",
            "platform": "example",
            "device_id": "ha-dev-ac-1",
            "area_id": "bedroom",
            "aliases": ["bedroom ac"],
        },
        {
            "entity_id": "sensor.master_ac_temperature",
            "unique_id": "ac-1-temp",
            "platform": "example",
            "device_id": "ha-dev-ac-1",
            "area_id": "bedroom",
        },
        {
            "entity_id": "light.kitchen_ceiling",
            "unique_id": "light-1",
            "platform": "example",
            "device_id": "ha-dev-light-1",
            "area_id": "kitchen",
            "aliases": ["main kitchen light"],
        },
    ]
    devices = [
        {"id": "ha-dev-ac-1", "name": "Bedroom air conditioner", "area_id": "bedroom"},
        {"id": "ha-dev-light-1", "name": "Kitchen ceiling light", "area_id": "kitchen"},
    ]
    areas = [
        {"area_id": "bedroom", "name": "Bedroom"},
        {"area_id": "kitchen", "name": "Kitchen"},
    ]
    return build_registry(states, entities, devices, areas)


def test_groups_many_entities_into_one_semantic_device():
    registry = _fixture_registry()
    ac = next(d for d in registry if d.ha_device_id == "ha-dev-ac-1")
    assert len(ac.entities) == 2
    assert "temperature" in ac.capabilities
    assert "fan_mode" in ac.capabilities
    assert "read" in ac.capabilities
    assert ac.stable_key == "ha-device:ha-dev-ac-1"


def test_entity_rename_does_not_change_bobi_identity():
    first = _fixture_registry()
    ac1 = next(d for d in first if d.ha_device_id == "ha-dev-ac-1")

    second = build_registry(
        [{"entity_id": "climate.renamed", "state": "cool", "attributes": {"temperature": 23, "target_temp_step": 0.5}}],
        [{"entity_id": "climate.renamed", "unique_id": "ac-1-climate", "platform": "example", "device_id": "ha-dev-ac-1"}],
        [{"id": "ha-dev-ac-1", "name": "Bedroom air conditioner"}],
        [],
    )
    ac2 = second[0]
    assert ac1.bobi_id == ac2.bobi_id
    assert ac2.entities[0].entity_id == "climate.renamed"


def test_resolver_uses_discovered_alias_not_house_mapping():
    registry = _fixture_registry()
    result = resolve_target("turn off the main kitchen light", registry, domain_hint="light", capability="power")
    assert result.ok
    assert result.devices[0].ha_device_id == "ha-dev-light-1"
    assert result.confidence >= 0.92


def test_context_reference_reuses_active_device_only_when_compatible():
    registry = _fixture_registry()
    ac = next(d for d in registry if d.ha_device_id == "ha-dev-ac-1")
    result = resolve_target(
        "עוד קצת",
        registry,
        domain_hint="climate",
        capability="temperature",
        active_device_id=ac.bobi_id,
    )
    assert result.ok
    assert result.resolution_kind == "context"
    assert result.devices == (ac,)


def test_half_degree_is_taken_from_device_capability_contract():
    registry = _fixture_registry()
    ac = next(d for d in registry if d.ha_device_id == "ha-dev-ac-1")
    plan = build_plan(
        request_id="msg-1",
        device=ac,
        capability="temperature",
        operation="set",
        delta=0.5,
    )
    assert plan.domain == "climate"
    assert plan.action == "set_temperature"
    assert plan.data["temperature"] == 23.5
    assert plan.expected["value"] == 23.5


def test_memory_replaces_helper_style_context_and_keeps_learned_alias(tmp_path):
    registry = _fixture_registry()
    ac = next(d for d in registry if d.ha_device_id == "ha-dev-ac-1")
    memory = BobiMemory(tmp_path / "bobi.db")
    try:
        memory.sync_devices(registry, now_ts=100)
        memory.add_alias(ac.bobi_id, "our bedroom ac")
        assert ("our bedroom ac", 1.2) in memory.aliases_for(ac.bobi_id)

        memory.set_active_context(
            "user-1",
            bobi_device_id=ac.bobi_id,
            object_type="device",
            ttl_seconds=300,
            now_ts=100,
        )
        assert memory.get_active_context("user-1", now_ts=200)["bobi_device_id"] == ac.bobi_id
        assert memory.get_active_context("user-1", now_ts=401) is None

        memory.store_turn("user-1", "turn it up", direction="user", message_id="m1", created_ts=100)
        memory.store_turn("user-1", "turn it up", direction="user", message_id="m1", created_ts=101)
        assert len(memory.recent_turns("user-1")) == 1
    finally:
        memory.close()
