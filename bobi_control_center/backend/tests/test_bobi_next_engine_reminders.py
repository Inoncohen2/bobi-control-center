from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.bobi_next.authorization import UserPolicy
from app.bobi_next.engine import EngineRequest, process_request
from app.bobi_next.intent import SemanticIntent
from app.bobi_next.memory import BobiMemory
from app.bobi_next.reminders import ReminderStore
from app.bobi_next.request_ledger import RequestLedger


class NoopHA:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def get_state(self, entity_id):
        self.calls.append(("get_state", entity_id))
        return None

    async def call_service(self, domain, service, data):
        self.calls.append((domain, service, dict(data)))
        raise AssertionError("reminder_must_not_call_ha")


@dataclass
class StaticUnderstanding:
    intent: SemanticIntent

    async def understand(self, text, *, context):
        del text, context
        return self.intent


def _intent(
    *,
    text: str = "לקחת מפתח",
    delay: int = 60,
    operation: str = "create",
    negated: bool = False,
) -> SemanticIntent:
    return SemanticIntent(
        raw_text="תזכיר לי לקחת מפתח בעוד דקה",
        family="reminder",
        domain="reminder",
        operation=operation,
        target_text=text,
        scheduled=True,
        negated=negated,
        confidence=0.99,
        schedule_kind="relative",
        schedule_payload={"delay_seconds": delay},
    )


async def _devices():
    return ()


async def _policy(user_key: str) -> UserPolicy:
    return UserPolicy(user_key)


async def _blocked_policy(user_key: str) -> UserPolicy:
    return UserPolicy(
        user_key,
        allowed_capabilities=frozenset({"device.control"}),
        allowed_domains=frozenset({"light"}),
    )


@pytest.mark.asyncio
async def test_reminder_is_created_without_device_resolution_or_ha_calls(tmp_path) -> None:
    memory = BobiMemory(tmp_path / "memory.db")
    requests = RequestLedger(tmp_path / "requests.db")
    reminders = ReminderStore(tmp_path / "reminders.db")
    ha = NoopHA()
    try:
        result = await process_request(
            EngineRequest(
                request_id="req-1",
                user_key="u1",
                text="תזכיר לי לקחת מפתח בעוד דקה",
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
            reminders=reminders,
        )

        assert result.outcome == "reminder_created"
        reminder = reminders.list_for_user("u1")[0]
        assert reminder.text == "לקחת מפתח"
        assert reminder.run_at_ts == 160
        assert reminder.provider_key == "wa-main"
        assert reminder.chat_id == "chat-1"
        assert reminder.source_message_id == "m1"
        assert ha.calls == []
    finally:
        reminders.close()
        requests.close()
        memory.close()


@pytest.mark.asyncio
async def test_reminder_dry_run_is_shadow_and_does_not_persist(tmp_path) -> None:
    memory = BobiMemory(tmp_path / "memory.db")
    requests = RequestLedger(tmp_path / "requests.db")
    reminders = ReminderStore(tmp_path / "reminders.db")
    try:
        result = await process_request(
            EngineRequest(
                request_id="req-1",
                user_key="u1",
                text="remind me",
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
            reminders=reminders,
            dry_run=True,
        )

        assert result.outcome == "shadow"
        assert result.metadata["would_create_reminder"] is True
        assert reminders.list_for_user("u1") == ()
    finally:
        reminders.close()
        requests.close()
        memory.close()


@pytest.mark.asyncio
async def test_negated_reminder_is_ignored(tmp_path) -> None:
    memory = BobiMemory(tmp_path / "memory.db")
    requests = RequestLedger(tmp_path / "requests.db")
    reminders = ReminderStore(tmp_path / "reminders.db")
    try:
        result = await process_request(
            EngineRequest(
                request_id="req-1",
                user_key="u1",
                text="אל תזכיר לי",
                owner_token="worker",
                now_ts=100,
                provider_key="wa-main",
                chat_id="chat-1",
            ),
            understanding=StaticUnderstanding(_intent(negated=True)),
            list_devices=_devices,
            policy_for=_policy,
            ha=NoopHA(),
            memory=memory,
            requests=requests,
            reminders=reminders,
        )

        assert result.outcome == "ignored"
        assert reminders.list_for_user("u1") == ()
    finally:
        reminders.close()
        requests.close()
        memory.close()


@pytest.mark.asyncio
async def test_reminder_policy_can_block_creation(tmp_path) -> None:
    memory = BobiMemory(tmp_path / "memory.db")
    requests = RequestLedger(tmp_path / "requests.db")
    reminders = ReminderStore(tmp_path / "reminders.db")
    try:
        result = await process_request(
            EngineRequest(
                request_id="req-1",
                user_key="u1",
                text="remind me",
                owner_token="worker",
                now_ts=100,
                provider_key="wa-main",
                chat_id="chat-1",
            ),
            understanding=StaticUnderstanding(_intent()),
            list_devices=_devices,
            policy_for=_blocked_policy,
            ha=NoopHA(),
            memory=memory,
            requests=requests,
            reminders=reminders,
        )

        assert result.outcome == "blocked"
        assert result.reason == "capability_not_allowed"
        assert reminders.list_for_user("u1") == ()
    finally:
        reminders.close()
        requests.close()
        memory.close()


@pytest.mark.asyncio
async def test_reminder_missing_text_requests_clarification(tmp_path) -> None:
    memory = BobiMemory(tmp_path / "memory.db")
    requests = RequestLedger(tmp_path / "requests.db")
    reminders = ReminderStore(tmp_path / "reminders.db")
    try:
        result = await process_request(
            EngineRequest(
                request_id="req-1",
                user_key="u1",
                text="תזכיר לי",
                owner_token="worker",
                now_ts=100,
                provider_key="wa-main",
                chat_id="chat-1",
            ),
            understanding=StaticUnderstanding(_intent(text="")),
            list_devices=_devices,
            policy_for=_policy,
            ha=NoopHA(),
            memory=memory,
            requests=requests,
            reminders=reminders,
        )

        assert result.outcome == "clarification"
        assert result.reason == "reminder_text_missing"
        assert reminders.list_for_user("u1") == ()
    finally:
        reminders.close()
        requests.close()
        memory.close()


@pytest.mark.asyncio
async def test_duplicate_request_does_not_create_second_reminder(tmp_path) -> None:
    memory = BobiMemory(tmp_path / "memory.db")
    requests = RequestLedger(tmp_path / "requests.db")
    reminders = ReminderStore(tmp_path / "reminders.db")
    request = EngineRequest(
        request_id="same-request",
        user_key="u1",
        text="remind me",
        owner_token="worker",
        now_ts=100,
        provider_key="wa-main",
        chat_id="chat-1",
    )
    kwargs = dict(
        understanding=StaticUnderstanding(_intent()),
        list_devices=_devices,
        policy_for=_policy,
        ha=NoopHA(),
        memory=memory,
        requests=requests,
        reminders=reminders,
    )
    try:
        first = await process_request(request, **kwargs)
        second = await process_request(request, **kwargs)

        assert first.outcome == "reminder_created"
        assert second.outcome == "duplicate"
        assert len(reminders.list_for_user("u1")) == 1
    finally:
        reminders.close()
        requests.close()
        memory.close()
