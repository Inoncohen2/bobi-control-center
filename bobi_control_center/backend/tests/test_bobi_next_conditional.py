from __future__ import annotations

import pytest

from app.bobi_next.authorization import UserPolicy
from app.bobi_next.conditional import (
    ConditionalRuleStore,
    StateChangeEvent,
    TriggerSpec,
    entity_stable_key,
    event_matches,
    trigger_ref,
)
from app.bobi_next.conditional_runner import run_conditional_event
from app.bobi_next.models import DeviceRecord, EntityRecord
from app.bobi_next.pending_approval import PendingApprovalStore
from app.bobi_next.scheduled_actions import ScheduledDeviceAction


def _sensor(*, entity_id: str = "sensor.temp") -> DeviceRecord:
    entity = EntityRecord(
        entity_id=entity_id,
        domain="sensor",
        unique_id="temperature-main",
        platform="demo",
        device_id="sensor-device",
        name="Room temperature",
        state="26",
        attributes={},
    )
    return DeviceRecord(
        bobi_id="dev-sensor",
        stable_key="device:sensor-device",
        ha_device_id="sensor-device",
        name="Room sensor",
        entities=(entity,),
    )


def _switch() -> DeviceRecord:
    entity = EntityRecord(
        entity_id="switch.fan",
        domain="switch",
        unique_id="fan-power",
        platform="demo",
        device_id="fan-device",
        name="Fan power",
        state="off",
        capabilities=frozenset({"power"}),
    )
    return DeviceRecord(
        bobi_id="dev-fan",
        stable_key="device:fan-device",
        ha_device_id="fan-device",
        name="Fan",
        entities=(entity,),
        capabilities=entity.capabilities,
    )


def _lock() -> DeviceRecord:
    entity = EntityRecord(
        entity_id="lock.entry",
        domain="lock",
        unique_id="entry-lock",
        platform="demo",
        device_id="lock-device",
        name="Entry lock",
        state="locked",
        capabilities=frozenset({"lock", "unlock"}),
    )
    return DeviceRecord(
        bobi_id="dev-lock",
        stable_key="device:lock-device",
        ha_device_id="lock-device",
        name="Entry lock",
        entities=(entity,),
        capabilities=entity.capabilities,
    )


def _trigger(*, above: float | None = 27, to_state: str | None = None) -> TriggerSpec:
    entity = _sensor().entities[0]
    if above is not None:
        return TriggerSpec(kind="numeric", entity=trigger_ref(entity), above=above)
    return TriggerSpec(kind="state", entity=trigger_ref(entity), to_state=to_state)


def _event(
    *,
    event_id: str = "e1",
    entity_id: str = "sensor.temp",
    old_state: str = "26",
    new_state: str = "28",
    occurred_ts: int = 100,
) -> StateChangeEvent:
    return StateChangeEvent(
        event_id=event_id,
        entity_id=entity_id,
        old_state=old_state,
        new_state=new_state,
        old_attributes={},
        new_attributes={},
        occurred_ts=occurred_ts,
    )


def _action(device: DeviceRecord, capability: str, operation: str) -> dict:
    action = ScheduledDeviceAction(
        schema_version=2,
        source_text="conditional test",
        device_ids=(device.bobi_id,),
        domain_hint=device.entities[0].domain,
        capability=capability,
        operation=operation,
        provenance_source_kind="direct",
        provenance_same_text=True,
        provenance_explicit_device_ids=(device.bobi_id,),
        provenance_reference_only=False,
    )
    return action.to_payload()


class FakeHA:
    def __init__(self):
        self.states = {
            "switch.fan": {"state": "off", "attributes": {}},
            "lock.entry": {"state": "locked", "attributes": {}},
        }
        self.calls: list[tuple[str, str, dict]] = []

    async def get_state(self, entity_id):
        value = self.states.get(entity_id)
        if value is None:
            return None
        return {"state": value["state"], "attributes": dict(value["attributes"])}

    async def call_service(self, domain, service, data):
        self.calls.append((domain, service, dict(data)))
        entity_id = data["entity_id"]
        if service == "turn_on":
            self.states[entity_id]["state"] = "on"
        elif service == "turn_off":
            self.states[entity_id]["state"] = "off"
        elif service == "unlock":
            self.states[entity_id]["state"] = "unlocked"
        elif service == "lock":
            self.states[entity_id]["state"] = "locked"


async def _policy(user_key: str) -> UserPolicy:
    return UserPolicy(user_key)


def test_numeric_trigger_fires_only_on_threshold_crossing():
    devices = (_sensor(),)
    trigger = _trigger(above=27)

    assert event_matches(trigger, _event(old_state="26", new_state="28"), devices)
    assert not event_matches(trigger, _event(old_state="28", new_state="29"), devices)
    assert not event_matches(trigger, _event(old_state="26", new_state="27"), devices)


def test_trigger_survives_entity_id_rename_using_stable_identity():
    original = _sensor(entity_id="sensor.temp").entities[0]
    renamed_device = _sensor(entity_id="sensor.bedroom_temperature")
    trigger = TriggerSpec(kind="numeric", entity=trigger_ref(original), above=27)
    event = _event(entity_id="sensor.bedroom_temperature")

    assert entity_stable_key(original) == entity_stable_key(renamed_device.entities[0])
    assert event_matches(trigger, event, (renamed_device,))


def test_duration_trigger_fails_closed_until_delayed_recheck_is_connected():
    entity = _sensor().entities[0]
    trigger = TriggerSpec(
        kind="state",
        entity=trigger_ref(entity),
        to_state="on",
        for_seconds=30,
    )
    event = _event(old_state="off", new_state="on")

    assert not event_matches(trigger, event, (_sensor(),))


def test_rule_store_deduplicates_event_and_enforces_cooldown(tmp_path):
    store = ConditionalRuleStore(tmp_path / "rules.db")
    try:
        store.create(
            rule_id="r1",
            user_key="u1",
            source_text="when hot turn fan on",
            trigger=_trigger(),
            action_payload=_action(_switch(), "power", "on"),
            cooldown_seconds=60,
            now_ts=10,
        )
        assert store.claim_fire(rule_id="r1", event_id="e1", now_ts=100)
        store.finish_fire(rule_id="r1", event_id="e1", success=True, now_ts=100)
        assert not store.claim_fire(rule_id="r1", event_id="e1", now_ts=101)
        assert not store.claim_fire(rule_id="r1", event_id="e2", now_ts=120)
        assert store.claim_fire(rule_id="r1", event_id="e3", now_ts=161)
    finally:
        store.close()


def test_once_rule_disables_after_success(tmp_path):
    store = ConditionalRuleStore(tmp_path / "rules.db")
    try:
        store.create(
            rule_id="once",
            user_key="u1",
            source_text="once",
            trigger=_trigger(),
            action_payload=_action(_switch(), "power", "on"),
            once=True,
            now_ts=10,
        )
        assert store.claim_fire(rule_id="once", event_id="e1", now_ts=100)
        store.finish_fire(rule_id="once", event_id="e1", success=True, now_ts=100)
        assert store.get("once").enabled is False
        assert not store.claim_fire(rule_id="once", event_id="e2", now_ts=200)
    finally:
        store.close()


@pytest.mark.asyncio
async def test_runner_executes_matching_rule_once_and_verifies(tmp_path):
    store = ConditionalRuleStore(tmp_path / "rules.db")
    ha = FakeHA()
    devices_snapshot = (_sensor(), _switch())
    try:
        store.create(
            rule_id="fan-hot",
            user_key="u1",
            source_text="when temperature is above 27 turn fan on",
            trigger=_trigger(),
            action_payload=_action(_switch(), "power", "on"),
            now_ts=10,
        )

        async def devices():
            return devices_snapshot

        first = await run_conditional_event(
            store,
            ha,
            event=_event(),
            list_devices=devices,
            policy_for=_policy,
            verification_delay=0,
        )
        duplicate = await run_conditional_event(
            store,
            ha,
            event=_event(),
            list_devices=devices,
            policy_for=_policy,
            verification_delay=0,
        )

        assert len(first) == 1
        assert first[0].outcome == "completed"
        assert first[0].executed_count == 1
        assert first[0].verified_count == 1
        assert duplicate[0].outcome == "duplicate_or_cooldown"
        assert ha.calls == [("switch", "turn_on", {"entity_id": "switch.fan"})]
    finally:
        store.close()


@pytest.mark.asyncio
async def test_sensitive_conditional_action_is_held_for_user_approval(tmp_path):
    store = ConditionalRuleStore(tmp_path / "rules.db")
    pending = PendingApprovalStore(tmp_path / "pending.db")
    ha = FakeHA()
    devices_snapshot = (_sensor(), _lock())
    try:
        store.create(
            rule_id="unlock-hot",
            user_key="u1",
            source_text="when hot unlock entry",
            trigger=_trigger(),
            action_payload=_action(_lock(), "unlock", "unlock"),
            now_ts=10,
        )

        async def devices():
            return devices_snapshot

        results = await run_conditional_event(
            store,
            ha,
            event=_event(),
            list_devices=devices,
            policy_for=_policy,
            pending_approvals=pending,
            verification_delay=0,
        )

        assert results[0].outcome == "approval_required"
        assert results[0].approval_request_id
        assert ha.calls == []
        assert pending.get(results[0].approval_request_id) is not None
    finally:
        pending.close()
        store.close()


@pytest.mark.asyncio
async def test_nonmatching_event_has_no_side_effect(tmp_path):
    store = ConditionalRuleStore(tmp_path / "rules.db")
    ha = FakeHA()
    try:
        store.create(
            rule_id="fan-hot",
            user_key="u1",
            source_text="hot",
            trigger=_trigger(),
            action_payload=_action(_switch(), "power", "on"),
            now_ts=10,
        )

        async def devices():
            return (_sensor(), _switch())

        results = await run_conditional_event(
            store,
            ha,
            event=_event(old_state="25", new_state="26"),
            list_devices=devices,
            policy_for=_policy,
            verification_delay=0,
        )

        assert results == ()
        assert ha.calls == []
    finally:
        store.close()
