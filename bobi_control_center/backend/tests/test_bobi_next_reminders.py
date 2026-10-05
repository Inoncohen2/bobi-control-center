from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.bobi_next.reminders import (
    ReminderStore,
    process_next_reminder,
    reminder_delivery_key,
)


@dataclass
class FakeTransport:
    fail: bool = False
    calls: list[tuple[str, str, str, str]] = field(default_factory=list)

    async def react(self, message, emoji):
        del message, emoji

    async def set_typing(self, chat_id, enabled):
        del chat_id, enabled

    async def send_text(self, chat_id, text, *, reply_to, idempotency_key):
        self.calls.append((chat_id, text, reply_to, idempotency_key))
        if self.fail:
            raise RuntimeError("provider_down")
        return f"provider-{len(self.calls)}"


def _create(store: ReminderStore, **overrides):
    values = {
        "reminder_id": "r1",
        "user_key": "u1",
        "provider_key": "wa",
        "chat_id": "chat-1",
        "text": "לקחת מפתח",
        "run_at_ts": 100,
        "now_ts": 50,
    }
    values.update(overrides)
    return store.create(**values)


def test_reminder_store_create_list_and_cancel(tmp_path) -> None:
    store = ReminderStore(tmp_path / "reminders.db")
    try:
        reminder = _create(store)
        assert reminder.state == "pending"
        assert store.list_for_user("u1") == (reminder,)

        cancelled = store.cancel("r1", user_key="u1", now_ts=60)
        assert cancelled.state == "cancelled"
        assert store.list_for_user("u1") == ()
        assert store.list_for_user("u1", include_terminal=True)[0].state == "cancelled"
    finally:
        store.close()


def test_expired_loading_is_retryable_but_expired_sending_is_uncertain(tmp_path) -> None:
    store = ReminderStore(tmp_path / "reminders.db")
    try:
        _create(store, reminder_id="loading")
        claimed = store.claim_due(owner_token="w1", now_ts=100, lease_seconds=5)
        assert claimed is not None
        assert claimed.state == "loading"

        reclaimed = store.claim_due(owner_token="w2", now_ts=106, lease_seconds=5)
        assert reclaimed is not None
        assert reclaimed.reminder_id == "loading"
        assert reclaimed.owner_token == "w2"

        store.begin_send(reclaimed, owner_token="w2", now_ts=106, lease_seconds=5)
        assert store.claim_due(owner_token="w3", now_ts=112) is None
        uncertain = store.get("loading")
        assert uncertain is not None
        assert uncertain.state == "uncertain"
        assert uncertain.last_error == "sending_lease_expired"
    finally:
        store.close()


@pytest.mark.asyncio
async def test_one_shot_reminder_sends_with_stable_idempotency_key(tmp_path) -> None:
    store = ReminderStore(tmp_path / "reminders.db")
    transport = FakeTransport()
    try:
        original = _create(store)
        expected_key = reminder_delivery_key(original)
        result = await process_next_reminder(
            store,
            lambda provider: transport,
            owner_token="worker",
            now_ts=100,
        )

        assert result is not None
        assert result.state == "sent"
        assert result.provider_message_id == "provider-1"
        assert transport.calls == [
            ("chat-1", "⏰ לקחת מפתח", "", expected_key),
        ]
        assert await process_next_reminder(
            store,
            lambda provider: transport,
            owner_token="worker",
            now_ts=101,
        ) is None
    finally:
        store.close()


@pytest.mark.asyncio
async def test_recurring_reminder_advances_without_catchup_spam(tmp_path) -> None:
    store = ReminderStore(tmp_path / "reminders.db")
    transport = FakeTransport()
    try:
        _create(store, recurrence_seconds=60)
        result = await process_next_reminder(
            store,
            lambda provider: transport,
            owner_token="worker",
            now_ts=250,
        )

        assert result is not None
        assert result.state == "pending"
        assert result.occurrence == 1
        assert result.run_at_ts == 280
        assert result.attempts == 0
        assert len(transport.calls) == 1
    finally:
        store.close()


@pytest.mark.asyncio
async def test_provider_failure_becomes_uncertain_and_is_not_auto_retried(tmp_path) -> None:
    store = ReminderStore(tmp_path / "reminders.db")
    transport = FakeTransport(fail=True)
    try:
        _create(store)
        result = await process_next_reminder(
            store,
            lambda provider: transport,
            owner_token="worker",
            now_ts=100,
        )

        assert result is not None
        assert result.state == "uncertain"
        assert len(transport.calls) == 1
        assert await process_next_reminder(
            store,
            lambda provider: transport,
            owner_token="worker-2",
            now_ts=200,
        ) is None
    finally:
        store.close()


@pytest.mark.asyncio
async def test_missing_transport_retries_before_any_send(tmp_path) -> None:
    store = ReminderStore(tmp_path / "reminders.db")
    try:
        _create(store)

        def missing(provider):
            raise KeyError(provider)

        result = await process_next_reminder(
            store,
            missing,
            owner_token="worker",
            now_ts=100,
            retry_delay_seconds=20,
        )

        assert result is not None
        assert result.state == "retry"
        assert result.run_at_ts == 120
    finally:
        store.close()


@pytest.mark.asyncio
async def test_disabled_user_fails_before_provider_boundary(tmp_path) -> None:
    store = ReminderStore(tmp_path / "reminders.db")
    transport = FakeTransport()
    try:
        _create(store)
        result = await process_next_reminder(
            store,
            lambda provider: transport,
            owner_token="worker",
            now_ts=100,
            user_enabled=lambda user_key: False,
        )

        assert result is not None
        assert result.state == "failed"
        assert result.last_error == "reminder_user_disabled"
        assert transport.calls == []
    finally:
        store.close()


def test_uncertain_can_be_reconciled_as_sent_or_retry(tmp_path) -> None:
    store = ReminderStore(tmp_path / "reminders.db")
    try:
        _create(store)
        claimed = store.claim_due(owner_token="w", now_ts=100, lease_seconds=5)
        assert claimed is not None
        sending = store.begin_send(claimed, owner_token="w", now_ts=100, lease_seconds=5)
        uncertain = store.mark_uncertain(
            sending,
            owner_token="w",
            error="transport",
            now_ts=100,
        )
        assert uncertain.state == "uncertain"

        sent = store.resolve_uncertain(
            "r1",
            resolution="sent",
            provider_message_id="provider-1",
            now_ts=101,
        )
        assert sent.state == "sent"
        assert sent.provider_message_id == "provider-1"
    finally:
        store.close()
