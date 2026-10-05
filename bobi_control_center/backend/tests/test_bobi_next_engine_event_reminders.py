from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.bobi_next.authorization import UserPolicy
from app.bobi_next.engine import EngineRequest, process_request
from app.bobi_next.event_reminders import EventReminderStore
from app.bobi_next.intent import SemanticIntent
from app.bobi_next.memory import BobiMemory
from app.bobi_next.models import DeviceRecord, EntityRecord
from app.bobi_next.request_ledger import RequestLedger


class NoopHA:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def get_state(self, entity_id):
        self.calls.append(("get_state", entity_id))
        return None

    async def call_service(self, domain, service, data):
        self.calls.append((domain, service, dict(data)))
        raise AssertionError("event_reminder_must_not_call_ha")


@dataclass
class StaticUnderstanding:
    intent: SemanticIntent

    async def understand(self, text, *, context):
        del text, context
        return self.intent


def _door() -> DeviceRecord:
    entity = EntityRecord(
        entity_id="binary_sensor.front_door",
        domain="binary_sensor",
        name="Front door",
        state="off",
        device_id="door-device",
        platform="zha",
        unique_id="front-door-1",
        capabilities=frozenset(),
    )
    return DeviceRecord(
        bobi_id="device:door-device",
        stable_key="device:door-device",
        name="Front door",
        entities=(entity,),
        capabilities=frozenset(),
    )


def _intent() -> SemanticIntent:
    return SemanticIntent(
        raw_text="תזכיר לי לבדוק מי נכנס כשהדלת נפתחת",
        family="reminder",
        domain="reminder",
        operation="create",
        target_text="לבדוק מי נכנס",
        conditional=True,
        confidence=0.99,
        condition_payload={
            "kind": "state",
            "trigger_target_text": "Front door",
            "trigger_domain": "binary_sensor",
            "to_state": "on",
            "once": True,
        },
    )


async def _devices():
    return (_door(),)


async def _policy(user_key: str) -> UserPolicy:
    return UserPolicy(user_key)


@pytest.mark.asyncio
async def test_engine_creates_event_reminder_without_ha_side_effect(tmp_path) -> None:
    memory = BobiMemory(tmp_path / "memory.db")
    requests = RequestLedger(tmp_path / "requests.db")
    event_reminders = EventReminderStore(tmp_path / "event-reminders.db")
    ha = NoopHA()
    try:
        result = await process_request(
            EngineRequest(
                request_id="req-event-1",
                user_key="u1",
                text="תזכיר לי לבדוק מי נכנס כשהדלת נפתחת",
                owner_token="worker",
                message_id="m1",
                now_ts=100,
                provider_key="wa-main",
                chat_id="chat-1",
            ),
            understanding=StaticUnderstanding(_intent()),
            list_devices=_devices,
            policy_for=_policy,
            ha=ha,
            memory=memory,
            requests=requests,
            event_reminders=event_reminders,
        )

        assert result.outcome == "event_reminder_created"
        definitions = event_reminders.list_enabled()
        assert len(definitions) == 1
        definition = definitions[0]
        assert definition.user_key == "u1"
        assert definition.provider_key == "wa-main"
        assert definition.chat_id == "chat-1"
        assert definition.text == "לבדוק מי נכנס"
        assert definition.trigger.to_state == "on"
        assert definition.trigger.entity.stable_key.startswith("device:door-device:entity:")
        assert ha.calls == []
    finally:
        event_reminders.close()
        requests.close()
        memory.close()


@pytest.mark.asyncio
async def test_engine_event_reminder_dry_run_does_not_persist(tmp_path) -> None:
    memory = BobiMemory(tmp_path / "memory.db")
    requests = RequestLedger(tmp_path / "requests.db")
    event_reminders = EventReminderStore(tmp_path / "event-reminders.db")
    try:
        result = await process_request(
            EngineRequest(
                request_id="req-event-shadow",
                user_key="u1",
                text="remind me when the door opens",
                owner_token="worker",
                message_id="m1",
                now_ts=100,
                provider_key="wa-main",
                chat_id="chat-1",
            ),
            understanding=StaticUnderstanding(_intent()),
            list_devices=_devices,
            policy_for=_policy,
            ha=NoopHA(),
            memory=memory,
            requests=requests,
            event_reminders=event_reminders,
            dry_run=True,
        )

        assert result.outcome == "shadow"
        assert result.metadata["trigger_kind"] == "state"
        assert event_reminders.list_enabled() == ()
    finally:
        event_reminders.close()
        requests.close()
        memory.close()


@pytest.mark.asyncio
async def test_engine_event_reminder_without_store_retries_fail_closed(tmp_path) -> None:
    memory = BobiMemory(tmp_path / "memory.db")
    requests = RequestLedger(tmp_path / "requests.db")
    try:
        result = await process_request(
            EngineRequest(
                request_id="req-no-store",
                user_key="u1",
                text="remind me when the door opens",
                owner_token="worker",
                now_ts=100,
                provider_key="wa-main",
                chat_id="chat-1",
            ),
            understanding=StaticUnderstanding(_intent()),
            list_devices=_devices,
            policy_for=_policy,
            ha=NoopHA(),
            memory=memory,
            requests=requests,
        )

        assert result.outcome == "retry"
        assert result.reason == "runtime_error:RuntimeError"
    finally:
        requests.close()
        memory.close()
