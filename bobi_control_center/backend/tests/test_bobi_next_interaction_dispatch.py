from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.bobi_next.interaction_dispatch import (
    InteractionDispatchStore,
    InteractionHandlerResult,
    process_next_interaction,
)


class FakeTransport:
    def __init__(self, *, fail_once: bool = False) -> None:
        self.fail_once = fail_once
        self.sent: list[tuple[str, str, str, str]] = []

    async def react(self, message, emoji: str) -> None:  # pragma: no cover - protocol only
        del message, emoji

    async def set_typing(self, chat_id: str, enabled: bool) -> None:  # pragma: no cover
        del chat_id, enabled

    async def send_text(
        self,
        chat_id: str,
        text: str,
        *,
        reply_to: str,
        idempotency_key: str,
    ) -> str:
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("temporary transport failure")
        self.sent.append((chat_id, text, reply_to, idempotency_key))
        return "provider-reply-1"


def _enqueue(store: InteractionDispatchStore, *, event_id: str = "vote-1", key: str = "yes"):
    return store.enqueue(
        provider="waha-main",
        interaction_id="interaction-1",
        poll_message_id="poll-1",
        chat_id="1@c.us",
        user_key="u1",
        context_key="dialog:confirm-boiler",
        selected_keys=(key,),
        source_event_id=event_id,
        provider_timestamp=100,
        now_ts=10,
    )


def test_first_selection_wins_for_action_interaction(tmp_path) -> None:
    store = InteractionDispatchStore(tmp_path / "dispatch.db")
    try:
        first = _enqueue(store, event_id="vote-1", key="yes")
        second = _enqueue(store, event_id="vote-2", key="no")

        assert second.dispatch_id == first.dispatch_id
        assert second.source_event_id == "vote-1"
        assert second.selected_keys == ("yes",)
    finally:
        store.close()


@pytest.mark.asyncio
async def test_registered_namespace_dispatches_without_ai(tmp_path) -> None:
    store = InteractionDispatchStore(tmp_path / "dispatch.db")
    transport = FakeTransport()
    calls = []

    async def handler(selection):
        calls.append(selection)
        return InteractionHandlerResult(
            outcome="confirmed",
            response_text="✅ הבחירה התקבלה.",
        )

    try:
        queued = _enqueue(store)
        result = await process_next_interaction(
            store,
            {"dialog": handler},
            lambda provider: transport,
            owner_token="worker-1",
            now_ts=20,
        )

        assert result is not None
        assert result.state == "completed"
        assert result.outcome == "confirmed"
        assert len(calls) == 1
        assert calls[0].selected_keys == ("yes",)
        assert calls[0].context_key == "dialog:confirm-boiler"
        assert transport.sent == [
            ("1@c.us", "✅ הבחירה התקבלה.", "poll-1", queued.dispatch_id)
        ]
        stored = store.get(queued.dispatch_id)
        assert stored is not None
        assert stored.provider_message_id == "provider-reply-1"
    finally:
        store.close()


@pytest.mark.asyncio
async def test_retry_after_response_transport_failure_does_not_reinvoke_handler(tmp_path) -> None:
    store = InteractionDispatchStore(tmp_path / "dispatch.db")
    transport = FakeTransport(fail_once=True)
    call_count = 0

    async def handler(selection):
        nonlocal call_count
        call_count += 1
        assert selection.dispatch_id
        return InteractionHandlerResult(outcome="done", response_text="done")

    try:
        queued = _enqueue(store)
        first = await process_next_interaction(
            store,
            {"dialog": handler},
            lambda provider: transport,
            owner_token="worker-1",
            now_ts=20,
            retry_delay_seconds=1,
        )
        assert first is not None
        assert first.state == "retry"
        assert call_count == 1
        after_first = store.get(queued.dispatch_id)
        assert after_first is not None
        assert after_first.handler_done is True

        second = await process_next_interaction(
            store,
            {"dialog": handler},
            lambda provider: transport,
            owner_token="worker-2",
            now_ts=21,
            retry_delay_seconds=1,
        )
        assert second is not None
        assert second.state == "completed"
        assert call_count == 1
        assert len(transport.sent) == 1
    finally:
        store.close()


@pytest.mark.asyncio
async def test_unknown_context_namespace_fails_closed_without_transport(tmp_path) -> None:
    store = InteractionDispatchStore(tmp_path / "dispatch.db")
    transport = FakeTransport()
    try:
        queued = store.enqueue(
            provider="waha-main",
            interaction_id="interaction-2",
            poll_message_id="poll-2",
            chat_id="1@c.us",
            user_key="u1",
            context_key="missing:opaque",
            selected_keys=("a",),
            source_event_id="vote-2",
            provider_timestamp=200,
            now_ts=10,
        )
        result = await process_next_interaction(
            store,
            {},
            lambda provider: transport,
            owner_token="worker-1",
            now_ts=20,
        )

        assert result is not None
        assert result.state == "completed"
        assert result.outcome == "unhandled_context"
        assert transport.sent == []
        stored = store.get(queued.dispatch_id)
        assert stored is not None
        assert stored.handler_done is True
    finally:
        store.close()
