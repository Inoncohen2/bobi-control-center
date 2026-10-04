from __future__ import annotations

from pathlib import Path

import pytest

from app.bobi_next.authorization import UserPolicy
from app.bobi_next.conditional import (
    ConditionalRuleStore,
    StateChangeEvent,
    TriggerEntityRef,
    TriggerSpec,
)
from app.bobi_next.conditional_duration import (
    ConditionalDurationRuntime,
    DurationCheckStore,
    condition_holds,
)
from app.bobi_next.conditional_runner import ConditionalRunResult
from app.bobi_next.models import DeviceRecord, EntityRecord


def _devices(state: str = "off") -> tuple[DeviceRecord, ...]:
    entity = EntityRecord(
        entity_id="binary_sensor.door",
        domain="binary_sensor",
        unique_id="door-uid",
        platform="demo",
        device_id="door-device",
        name="Door",
        state=state,
    )
    return (
        DeviceRecord(
            bobi_id="dev-door",
            stable_key="device:door-device",
            ha_device_id="door-device",
            name="Door",
            entities=(entity,),
        ),
    )


def _trigger(seconds: int = 30) -> TriggerSpec:
    return TriggerSpec(
        kind="state",
        entity=TriggerEntityRef(
            stable_key="device:door-device:entity:demo:door-uid",
            entity_id="binary_sensor.door",
            domain="binary_sensor",
            device_id="door-device",
            platform="demo",
            unique_id="door-uid",
        ),
        to_state="on",
        for_seconds=seconds,
    )


def _create_rule(store: ConditionalRuleStore, *, seconds: int = 30) -> None:
    store.create(
        rule_id="rule-door",
        user_key="u1",
        source_text="if door stays open",
        trigger=_trigger(seconds),
        action_payload={"device_ids": ["dev-door"]},
        now_ts=90,
    )


class FakeClient:
    def __init__(self, state: str = "on") -> None:
        self.state = state

    async def get_state(self, entity_id: str):
        return {"entity_id": entity_id, "state": self.state, "attributes": {}}

    async def call_service(self, domain: str, service: str, data: dict):
        raise AssertionError("duration unit test should stub secure runner")


async def _policy(user_key: str) -> UserPolicy:
    return UserPolicy(user_key=user_key)


def test_condition_holds_is_current_state_based() -> None:
    trigger = _trigger()
    assert condition_holds(trigger, state="on", attributes={}) is True
    assert condition_holds(trigger, state="off", attributes={}) is False


@pytest.mark.asyncio
async def test_duration_arms_without_firing_and_survives_restart(tmp_path: Path) -> None:
    rules = ConditionalRuleStore(tmp_path / "rules.db")
    checks_path = tmp_path / "duration.db"
    checks = DurationCheckStore(checks_path)
    _create_rule(rules)

    async def devices():
        return _devices("on")

    runtime = ConditionalDurationRuntime(
        checks=checks,
        rules=rules,
        client=FakeClient("on"),
        list_devices=devices,
        policy_for=_policy,
    )
    event = StateChangeEvent(
        event_id="evt-open",
        entity_id="binary_sensor.door",
        old_state="off",
        new_state="on",
        old_attributes={},
        new_attributes={},
        occurred_ts=100,
    )
    try:
        await runtime.observe_event(event)
        armed = checks.get("rule-door")
        assert armed is not None
        assert armed.due_ts == 130
        assert await runtime.run_due_once(owner_token="worker", now_ts=129) == ()
    finally:
        checks.close()

    reopened = DurationCheckStore(checks_path)
    try:
        armed = reopened.get("rule-door")
        assert armed is not None
        assert armed.source_event_id == "evt-open"
        assert armed.due_ts == 130
    finally:
        reopened.close()
        rules.close()


@pytest.mark.asyncio
async def test_duration_is_cancelled_when_condition_breaks(tmp_path: Path) -> None:
    rules = ConditionalRuleStore(tmp_path / "rules.db")
    checks = DurationCheckStore(tmp_path / "duration.db")
    _create_rule(rules)

    async def devices():
        return _devices()

    runtime = ConditionalDurationRuntime(
        checks=checks,
        rules=rules,
        client=FakeClient("off"),
        list_devices=devices,
        policy_for=_policy,
    )
    try:
        await runtime.observe_event(
            StateChangeEvent(
                "evt-open",
                "binary_sensor.door",
                "off",
                "on",
                {},
                {},
                100,
            )
        )
        assert checks.get("rule-door") is not None
        await runtime.observe_event(
            StateChangeEvent(
                "evt-close",
                "binary_sensor.door",
                "on",
                "off",
                {},
                {},
                110,
            )
        )
        assert checks.get("rule-door") is None
    finally:
        checks.close()
        rules.close()


@pytest.mark.asyncio
async def test_due_duration_rechecks_live_state_before_secure_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rules = ConditionalRuleStore(tmp_path / "rules.db")
    checks = DurationCheckStore(tmp_path / "duration.db")
    _create_rule(rules, seconds=5)
    client = FakeClient("on")
    seen: list[StateChangeEvent] = []

    async def devices():
        return _devices("on")

    async def fake_run(store, rule, event, **kwargs):
        del store, rule, kwargs
        seen.append(event)
        return ConditionalRunResult(
            rule_id="rule-door",
            event_id=event.event_id,
            outcome="completed",
            reason="verified",
            executed_count=1,
            verified_count=1,
        )

    monkeypatch.setattr(
        "app.bobi_next.conditional_duration._run_matched_rule",
        fake_run,
    )
    runtime = ConditionalDurationRuntime(
        checks=checks,
        rules=rules,
        client=client,
        list_devices=devices,
        policy_for=_policy,
    )
    try:
        await runtime.observe_event(
            StateChangeEvent(
                "evt-open",
                "binary_sensor.door",
                "off",
                "on",
                {},
                {},
                100,
            )
        )
        results = await runtime.run_due_once(owner_token="worker", now_ts=105)
        assert len(results) == 1
        assert results[0].outcome == "completed"
        assert seen and seen[0].event_id == "duration:rule-door:evt-open"
        assert checks.get("rule-door") is None
    finally:
        checks.close()
        rules.close()


@pytest.mark.asyncio
async def test_due_duration_does_not_fire_if_live_state_changed(tmp_path: Path) -> None:
    rules = ConditionalRuleStore(tmp_path / "rules.db")
    checks = DurationCheckStore(tmp_path / "duration.db")
    _create_rule(rules, seconds=5)

    async def devices():
        return _devices("on")

    runtime = ConditionalDurationRuntime(
        checks=checks,
        rules=rules,
        client=FakeClient("off"),
        list_devices=devices,
        policy_for=_policy,
    )
    try:
        await runtime.observe_event(
            StateChangeEvent(
                "evt-open",
                "binary_sensor.door",
                "off",
                "on",
                {},
                {},
                100,
            )
        )
        assert await runtime.run_due_once(owner_token="worker", now_ts=105) == ()
        assert checks.get("rule-door") is None
    finally:
        checks.close()
        rules.close()
