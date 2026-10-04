from __future__ import annotations

import pytest

from app.bobi_next.intent import SemanticIntent
from app.bobi_next.routing import RoutingError, route_intent


def _intent(**changes):
    values = {
        "raw_text": "command",
        "family": "control",
        "domain": "light",
        "operation": "off",
        "confidence": 0.99,
    }
    values.update(changes)
    return SemanticIntent(**values)


def test_light_power_routes_without_device_specific_knowledge():
    routed = route_intent(_intent(domain="lighting", operation="turn_off"))
    assert routed.domain_hint == "light"
    assert routed.capability == "power"
    assert routed.operation == "off"


def test_climate_delta_routes_to_temperature_capability():
    routed = route_intent(
        _intent(
            domain="climate",
            operation="set",
            value_kind="delta_temperature",
            delta=0.5,
        )
    )
    assert routed.capability == "temperature"
    assert routed.delta == 0.5


def test_cover_percentage_routes_to_position_instead_of_power():
    routed = route_intent(
        _intent(
            domain="cover",
            operation="set_position",
            value_kind="percentage",
            value=30,
        )
    )
    assert routed.capability == "position"
    assert routed.operation == "set"
    assert routed.value == 30


def test_scheduled_control_is_planned_but_deferred():
    routed = route_intent(
        _intent(
            domain="lighting",
            operation="turn_off",
            scheduled=True,
            family="schedule",
        )
    )
    assert routed.capability == "power"
    assert routed.defer_execution is True
    assert routed.defer_reason == "scheduled"


def test_group_intent_keeps_group_authority_explicit():
    routed = route_intent(_intent(domain="lighting", operation="turn_off", multi_target=True))
    assert routed.allow_group is True


def test_unknown_intent_fails_closed():
    with pytest.raises(RoutingError, match="unsupported_intent"):
        route_intent(_intent(domain="alarm_control_panel", operation="explode"))
