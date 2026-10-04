from __future__ import annotations

import pytest

from app.bobi_next.models import DeviceRecord, EntityRecord, TargetResolution
from app.bobi_next.routing import RoutedIntent
from app.bobi_next.scheduled_actions import (
    ScheduledDeviceAction,
    build_due_plans,
    capture_scheduled_action,
)


def _climate(current: float) -> DeviceRecord:
    entity = EntityRecord(
        entity_id="climate.bedroom",
        domain="climate",
        state="cool",
        attributes={
            "temperature": current,
            "min_temp": 16,
            "max_temp": 30,
            "target_temp_step": 0.5,
        },
        capabilities=frozenset({"power", "temperature"}),
        limits={"min_temp": 16, "max_temp": 30, "temp_step": 0.5},
    )
    return DeviceRecord(
        bobi_id="dev-stable-ac",
        stable_key="ha-device:ac",
        name="Bedroom AC",
        entities=(entity,),
        capabilities=entity.capabilities,
    )


def _routed(delta: float = 0.5) -> RoutedIntent:
    return RoutedIntent(
        domain_hint="climate",
        capability="temperature",
        operation="set",
        delta=delta,
        defer_execution=True,
        defer_reason="scheduled",
    )


def test_scheduled_action_round_trip_keeps_stable_device_identity():
    action = capture_scheduled_action(
        source_text="raise it later",
        routed=_routed(),
        resolution=TargetResolution(ok=True, devices=(_climate(23),), confidence=0.99),
    )
    restored = ScheduledDeviceAction.from_payload(action.to_payload())
    assert restored.device_ids == ("dev-stable-ac",)
    assert restored.delta == 0.5
    assert restored.capability == "temperature"


def test_relative_temperature_is_computed_from_live_state_at_execution_time():
    action = capture_scheduled_action(
        source_text="in 20 minutes raise by half a degree",
        routed=_routed(),
        resolution=TargetResolution(ok=True, devices=(_climate(23),), confidence=0.99),
    )

    # The AC changed to 25 before the schedule fired. The due plan must become
    # 25.5, not the 23.5 that would have been correct when the job was created.
    plans = build_due_plans(action, (_climate(25),), request_id="job:1")
    assert len(plans) == 1
    assert plans[0].data["temperature"] == 25.5


def test_scheduled_action_fails_closed_if_stable_device_disappears():
    action = capture_scheduled_action(
        source_text="later",
        routed=_routed(),
        resolution=TargetResolution(ok=True, devices=(_climate(23),), confidence=0.99),
    )
    with pytest.raises(ValueError, match="scheduled_device_missing"):
        build_due_plans(action, (), request_id="job:2")


def test_scheduled_action_rechecks_capability_at_execution_time():
    action = capture_scheduled_action(
        source_text="later",
        routed=_routed(),
        resolution=TargetResolution(ok=True, devices=(_climate(23),), confidence=0.99),
    )
    entity = EntityRecord(
        entity_id="climate.bedroom",
        domain="climate",
        state="cool",
        capabilities=frozenset({"power"}),
    )
    changed = DeviceRecord(
        bobi_id="dev-stable-ac",
        stable_key="ha-device:ac",
        name="Bedroom AC",
        entities=(entity,),
        capabilities=entity.capabilities,
    )
    with pytest.raises(ValueError, match="scheduled_capability_missing"):
        build_due_plans(action, (changed,), request_id="job:3")


def test_sensitive_scheduled_action_keeps_confirmation_requirement():
    action = capture_scheduled_action(
        source_text="later",
        routed=_routed(),
        resolution=TargetResolution(ok=True, devices=(_climate(23),), confidence=0.99),
        requires_confirmation=True,
    )
    plan = build_due_plans(action, (_climate(23),), request_id="job:4")[0]
    assert plan.requires_confirmation is True
