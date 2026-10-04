from __future__ import annotations

import pytest

from app.bobi_next.conditional_capture import capture_trigger, resolve_trigger_entity
from app.bobi_next.models import DeviceRecord, EntityRecord


def _device() -> DeviceRecord:
    temp = EntityRecord(
        entity_id="sensor.room_temp",
        domain="sensor",
        unique_id="room-temp",
        platform="demo",
        device_id="room-device",
        area_id="room",
        area_name="Room",
        name="Temperature",
        aliases=("room temperature",),
        state="25",
    )
    door = EntityRecord(
        entity_id="binary_sensor.door",
        domain="binary_sensor",
        unique_id="door-contact",
        platform="demo",
        device_id="room-device",
        area_id="room",
        area_name="Room",
        name="Door",
        aliases=("room door",),
        state="off",
    )
    return DeviceRecord(
        bobi_id="dev-room",
        stable_key="device:room-device",
        ha_device_id="room-device",
        name="Room sensors",
        area_id="room",
        area_name="Room",
        entities=(temp, door),
    )


def test_resolves_trigger_to_one_entity_not_whole_physical_device():
    entity = resolve_trigger_entity(
        {
            "target_text": "room temperature",
            "domain_hint": "sensor",
        },
        (_device(),),
    )

    assert entity.entity_id == "sensor.room_temp"
    assert entity.unique_id == "room-temp"


def test_capture_numeric_trigger_uses_stable_entity_identity():
    trigger = capture_trigger(
        {
            "kind": "numeric",
            "target_text": "room temperature",
            "domain_hint": "sensor",
            "above": 27,
        },
        (_device(),),
    )

    assert trigger.kind == "numeric"
    assert trigger.above == 27
    assert trigger.entity.entity_id == "sensor.room_temp"
    assert "room-temp" in trigger.entity.stable_key


def test_capture_state_trigger():
    trigger = capture_trigger(
        {
            "kind": "state",
            "target_text": "room door",
            "domain_hint": "binary_sensor",
            "from_state": "off",
            "to_state": "on",
        },
        (_device(),),
    )

    assert trigger.entity.entity_id == "binary_sensor.door"
    assert trigger.from_state == "off"
    assert trigger.to_state == "on"


def test_ambiguous_or_missing_target_fails_closed():
    with pytest.raises(ValueError, match="conditional_trigger"):
        capture_trigger(
            {
                "kind": "state",
                "target_text": "something else",
                "domain_hint": "binary_sensor",
                "to_state": "on",
            },
            (_device(),),
        )


def test_numeric_trigger_requires_threshold():
    with pytest.raises(ValueError, match="threshold_missing"):
        capture_trigger(
            {
                "kind": "numeric",
                "target_text": "room temperature",
                "domain_hint": "sensor",
            },
            (_device(),),
        )


def test_numeric_window_must_be_ordered():
    with pytest.raises(ValueError, match="invalid_window"):
        capture_trigger(
            {
                "kind": "numeric",
                "target_text": "room temperature",
                "domain_hint": "sensor",
                "above": 20,
                "below": 21,
            },
            (_device(),),
        )


def test_threshold_is_rejected_on_non_numeric_trigger():
    with pytest.raises(ValueError, match="threshold_only_valid"):
        capture_trigger(
            {
                "kind": "state",
                "target_text": "room door",
                "domain_hint": "binary_sensor",
                "to_state": "on",
                "above": 1,
            },
            (_device(),),
        )
