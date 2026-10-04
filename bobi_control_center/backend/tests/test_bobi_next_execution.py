from __future__ import annotations

import pytest

from app.bobi_next.executor import execute_plan, verify_expected
from app.bobi_next.ha_discovery import websocket_url_from_api
from app.bobi_next.models import ActionPlan


def test_supervisor_api_url_maps_to_core_websocket():
    assert websocket_url_from_api("http://supervisor/core/api") == "ws://supervisor/core/websocket"
    assert websocket_url_from_api("https://ha.example/api") == "wss://ha.example/websocket"


def test_verifier_understands_home_assistant_brightness_units():
    snapshot = {"state": "on", "attributes": {"brightness": 128}}
    assert verify_expected(
        snapshot,
        {"attribute": "brightness_pct", "value": 50, "tolerance": 1},
    )


class FakeHA:
    def __init__(self, before, after):
        self.before = before
        self.after = after
        self.calls = []
        self.reads = 0

    async def call_service(self, domain, service, data):
        self.calls.append((domain, service, data))

    async def get_state(self, entity_id):
        self.reads += 1
        return self.before if self.reads == 1 else self.after


@pytest.mark.asyncio
async def test_executor_only_reports_success_after_readback_verification():
    plan = ActionPlan(
        request_id="m1",
        device_id="dev_x",
        entity_id="climate.room",
        domain="climate",
        action="set_temperature",
        capability="temperature",
        data={"entity_id": "climate.room", "temperature": 23.5},
        expected={"attribute": "temperature", "value": 23.5, "tolerance": 0.25},
    )
    ha = FakeHA(
        {"state": "cool", "attributes": {"temperature": 23.0}},
        {"state": "cool", "attributes": {"temperature": 23.5}},
    )
    result = await execute_plan(plan, ha, verification_delay=0)
    assert result.executed is True
    assert result.verified is True
    assert ha.calls == [
        ("climate", "set_temperature", {"entity_id": "climate.room", "temperature": 23.5})
    ]


@pytest.mark.asyncio
async def test_executor_fails_closed_before_side_effect_when_unavailable():
    plan = ActionPlan(
        request_id="m2",
        device_id="dev_x",
        entity_id="switch.room",
        domain="switch",
        action="turn_on",
        capability="power",
        data={"entity_id": "switch.room"},
        expected={"state": "on"},
    )
    ha = FakeHA({"state": "unavailable", "attributes": {}}, {"state": "on", "attributes": {}})
    result = await execute_plan(plan, ha, verification_delay=0)
    assert result.executed is False
    assert result.reason == "target_unavailable"
    assert ha.calls == []


@pytest.mark.asyncio
async def test_executor_does_not_claim_verified_when_readback_disagrees():
    plan = ActionPlan(
        request_id="m3",
        device_id="dev_x",
        entity_id="light.room",
        domain="light",
        action="turn_off",
        capability="power",
        data={"entity_id": "light.room"},
        expected={"state": "off"},
    )
    ha = FakeHA({"state": "on", "attributes": {}}, {"state": "on", "attributes": {}})
    result = await execute_plan(plan, ha, verification_attempts=1, verification_delay=0)
    assert result.executed is True
    assert result.verified is False
    assert result.reason == "verification_failed"
