from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.bobi_next.authorization import UserPolicy
from app.bobi_next.conditional import ConditionalRuleStore
from app.bobi_next.engine import EngineRequest, UnderstandingContext, process_request
from app.bobi_next.intent import SemanticIntent
from app.bobi_next.memory import BobiMemory
from app.bobi_next.models import DeviceRecord, EntityRecord
from app.bobi_next.request_ledger import RequestLedger


@dataclass
class StaticUnderstanding:
    result: SemanticIntent

    async def understand(self, text: str, *, context: UnderstandingContext) -> SemanticIntent:
        return self.result


class NoopHA:
    def __init__(self):
        self.calls = []

    async def get_state(self, entity_id):
        raise AssertionError("conditional creation must not read execution state")

    async def call_service(self, domain, service, data):
        self.calls.append((domain, service, data))
        raise AssertionError("conditional creation must not execute")


def _devices() -> tuple[DeviceRecord, ...]:
    temp = EntityRecord(
        entity_id="sensor.room_temperature",
        domain="sensor",
        unique_id="room-temperature",
        platform="demo",
        device_id="sensor-device",
        name="Room temperature",
        aliases=("temperature sensor",),
        state="25",
    )
    sensor = DeviceRecord(
        bobi_id="dev-sensor",
        stable_key="device:sensor-device",
        ha_device_id="sensor-device",
        name="Room sensor",
        entities=(temp,),
    )
    switch_entity = EntityRecord(
        entity_id="switch.fan",
        domain="switch",
        unique_id="fan-switch",
        platform="demo",
        device_id="fan-device",
        name="Fan",
        state="off",
        capabilities=frozenset({"power"}),
    )
    fan = DeviceRecord(
        bobi_id="dev-fan",
        stable_key="device:fan-device",
        ha_device_id="fan-device",
        name="Fan",
        entities=(switch_entity,),
        capabilities=switch_entity.capabilities,
    )
    return sensor, fan


async def _policy(user_key: str) -> UserPolicy:
    raise AssertionError("policy is checked when the rule fires, not when it is stored")


@pytest.mark.asyncio
async def test_conditional_intent_creates_durable_rule_without_side_effect(tmp_path):
    memory = BobiMemory(tmp_path / "bobi.db")
    requests = RequestLedger(tmp_path / "requests.db")
    rules = ConditionalRuleStore(tmp_path / "rules.db")
    ha = NoopHA()
    try:
        understanding = StaticUnderstanding(
            SemanticIntent(
                raw_text="when room temperature is above 27 turn fan on",
                family="device_control",
                domain="switch",
                operation="on",
                target_text="Fan",
                conditional=True,
                confidence=0.99,
                condition_payload={
                    "kind": "numeric",
                    "target_text": "Room temperature",
                    "domain_hint": "sensor",
                    "above": 27,
                    "cooldown_seconds": 60,
                },
            )
        )

        async def devices():
            return _devices()

        result = await process_request(
            EngineRequest(
                "conditional-1",
                "u1",
                "when room temperature is above 27 turn fan on",
                "worker",
                now_ts=100,
            ),
            understanding=understanding,
            list_devices=devices,
            policy_for=_policy,
            ha=ha,
            memory=memory,
            requests=requests,
            conditional_rules=rules,
        )

        assert result.outcome == "conditional_created"
        assert result.metadata["rule_id"] == "req-conditional-1"
        rule = rules.get("req-conditional-1")
        assert rule is not None
        assert rule.trigger.kind == "numeric"
        assert rule.trigger.above == 27
        assert rule.action_payload["device_ids"] == ["dev-fan"]
        assert rule.cooldown_seconds == 60
        assert ha.calls == []
        assert requests.get("conditional-1").terminal_kind == "conditional_created"
    finally:
        rules.close()
        requests.close()
        memory.close()


@pytest.mark.asyncio
async def test_conditional_without_store_is_retryable_not_silently_lost(tmp_path):
    memory = BobiMemory(tmp_path / "bobi.db")
    requests = RequestLedger(tmp_path / "requests.db")
    ha = NoopHA()
    try:
        understanding = StaticUnderstanding(
            SemanticIntent(
                raw_text="when hot fan on",
                family="device_control",
                domain="switch",
                operation="on",
                target_text="Fan",
                conditional=True,
                confidence=0.99,
                condition_payload={
                    "kind": "numeric",
                    "target_text": "Room temperature",
                    "domain_hint": "sensor",
                    "above": 27,
                },
            )
        )

        async def devices():
            return _devices()

        result = await process_request(
            EngineRequest("conditional-2", "u1", "when hot fan on", "worker", now_ts=100),
            understanding=understanding,
            list_devices=devices,
            policy_for=_policy,
            ha=ha,
            memory=memory,
            requests=requests,
        )

        assert result.outcome == "retry"
        assert result.reason == "runtime_error:RuntimeError"
        assert ha.calls == []
    finally:
        requests.close()
        memory.close()
