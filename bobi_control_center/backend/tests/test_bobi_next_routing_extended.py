from __future__ import annotations

from app.bobi_next.intent import SemanticIntent
from app.bobi_next.routing import route_intent


def _intent(domain: str, operation: str = "set", **changes):
    values = {
        "raw_text": "command",
        "family": "control",
        "domain": domain,
        "operation": operation,
        "confidence": 0.99,
    }
    values.update(changes)
    return SemanticIntent(**values)


def test_fan_percentage_routes_to_percentage_capability():
    routed = route_intent(
        _intent("fan", value_kind="percentage", value=45)
    )
    assert routed.capability == "percentage"
    assert routed.value == 45


def test_vacuum_fan_speed_routes_to_native_capability():
    routed = route_intent(
        _intent("vacuum", value_kind="fan_speed", value="turbo")
    )
    assert routed.capability == "fan_speed"
    assert routed.value == "turbo"


def test_media_play_and_volume_are_distinct_capabilities():
    play = route_intent(_intent("media", operation="play"))
    volume = route_intent(
        _intent("media", operation="set_volume", value_kind="volume", value=35)
    )
    assert play.domain_hint == "media_player"
    assert play.capability == "play"
    assert volume.capability == "volume"
    assert volume.value == 35


def test_number_routes_to_set_value():
    routed = route_intent(_intent("number", operation="set_value", value=7.5))
    assert routed.capability == "set_value"
    assert routed.value == 7.5


def test_cover_tilt_routes_separately_from_main_position():
    routed = route_intent(
        _intent("cover", value_kind="tilt_position", value=25)
    )
    assert routed.capability == "tilt_position"
    assert routed.value == 25
