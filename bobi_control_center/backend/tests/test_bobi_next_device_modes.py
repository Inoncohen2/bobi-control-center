from __future__ import annotations

import pytest

from app.bobi_next.executor import verify_expected
from app.bobi_next.models import DeviceRecord, EntityRecord
from app.bobi_next.planner import PlanError, build_plan


def _device(entity: EntityRecord) -> DeviceRecord:
    return DeviceRecord(
        bobi_id="dev-test",
        stable_key="ha-device:test",
        name="Test device",
        entities=(entity,),
        capabilities=entity.capabilities,
    )


def _climate() -> DeviceRecord:
    return _device(
        EntityRecord(
            entity_id="climate.test",
            domain="climate",
            state="cool",
            attributes={"fan_mode": "auto", "swing_mode": "off", "preset_mode": "none"},
            capabilities=frozenset({"hvac_mode", "fan_mode", "swing_mode", "preset_mode"}),
            limits={
                "hvac_modes": ["off", "cool", "heat"],
                "fan_modes": ["auto", "low", "high"],
                "swing_modes": ["off", "vertical", "both"],
                "preset_modes": ["none", "eco", "sleep"],
            },
        )
    )


def test_verifier_supports_string_attributes():
    snapshot = {"state": "cool", "attributes": {"fan_mode": "auto"}}
    assert verify_expected(snapshot, {"attribute": "fan_mode", "value": "auto"})
    assert not verify_expected(snapshot, {"attribute": "fan_mode", "value": "high"})


def test_planner_sets_hvac_mode_and_verifies_state():
    plan = build_plan(
        request_id="m1",
        device=_climate(),
        capability="hvac_mode",
        operation="set",
        value="heat",
    )
    assert plan.action == "set_hvac_mode"
    assert plan.data["hvac_mode"] == "heat"
    assert plan.expected == {"state": "heat"}


@pytest.mark.parametrize(
    ("capability", "value", "service", "data_key"),
    [
        ("fan_mode", "high", "set_fan_mode", "fan_mode"),
        ("swing_mode", "vertical", "set_swing_mode", "swing_mode"),
        ("preset_mode", "sleep", "set_preset_mode", "preset_mode"),
    ],
)
def test_planner_sets_supported_climate_modes(capability, value, service, data_key):
    plan = build_plan(
        request_id="m2",
        device=_climate(),
        capability=capability,
        operation="set",
        value=value,
    )
    assert plan.action == service
    assert plan.data[data_key] == value
    assert plan.expected == {"attribute": data_key, "value": value}


def test_planner_rejects_mode_not_advertised_by_device():
    with pytest.raises(PlanError, match="fan_mode_not_supported"):
        build_plan(
            request_id="m3",
            device=_climate(),
            capability="fan_mode",
            operation="set",
            value="turbo-plus",
        )


def test_media_power_on_uses_non_off_verification():
    device = _device(
        EntityRecord(
            entity_id="media_player.test",
            domain="media_player",
            state="off",
            capabilities=frozenset({"power"}),
        )
    )
    plan = build_plan(
        request_id="m4",
        device=device,
        capability="power",
        operation="on",
    )
    assert plan.action == "turn_on"
    assert plan.expected == {"state_not": ["off", "unavailable", "unknown"]}
