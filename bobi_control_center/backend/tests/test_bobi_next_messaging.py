from __future__ import annotations

import pytest

from app.bobi_next.messaging import (
    MessageResponse,
    MessageStore,
    process_next_message,
)


def test_duplicate_webhook_is_persisted_only_once(tmp_path):
    store = MessageStore(tmp_path / "messages.db")
    try:
        first = store.enqueue(
            provider="waha",
            message_id="m1",
            chat_id="chat-a",
            user_key="u1",
            text="hello",
            received_ts=10,
        )
        duplicate = store.enqueue(
            provider="waha",
            message_id="m1",
            chat_id="chat-a",
            user_key="u1",
            text="hello",
            received_ts=10,
        )
        assert first is True
        assert duplicate is False
    finally:
        store.close()


def test_claiming_preserves_order_per_chat_but_allows_other_chats(tmp_path):
    store = MessageStore(tmp_path / "messages.db")
    try:
        store.enqueue(
            provider="waha",
            message_id="a1",
            chat_id="chat-a",
            user_key="u1",
            text="first",
            received_ts=10,
        )
        store.enqueue(
            provider="waha",
            message_id="a2",
            chat_id="chat-a",
            user_key="u1",
            text="second",
            received_ts=11,
        )
        store.enqueue(
            provider="waha",
            message_id="b1",
            chat_id="chat-b",
            user_key="u2",
            text="parallel",
            received_ts=12,
        )

        first = store.claim_next(owner_token="worker-1", now_ts=20)
        parallel = store.claim_next(owner_token="worker-2", now_ts=20)
        assert first.message_id == "a1"
        assert parallel.message_id == "b1"

        store.complete(first, owner_token="worker-1", now_ts=21)
        second = store.claim_next(owner_token="worker-3", now_ts=21)
        assert second.message_id == "a2"
    finally:
        store.close()


class FakeTransport:
    def __init__(self):
        self.events = []
        self.send_count = 0

    async def react(self, message, emoji):
        self.events.append(("react", message.message_id, emoji))

    async def set_typing(self, chat_id, enabled):
        self.events.append(("typing", chat_id, enabled))

    async def send_text(self, chat_id, text, *, reply_to, idempotency_key):
        self.send_count += 1
        self.events.append(("send", chat_id, text, reply_to, idempotency_key))
        return f"provider-{self.send_count}"


@pytest.mark.asyncio
async def test_message_lifecycle_is_reaction_then_typing_then_reply(tmp_path):
    store = MessageStore(tmp_path / "messages.db")
    try:
        store.enqueue(
            provider="waha",
            message_id="m1",
            chat_id="chat-a",
            user_key="u1",
            text="turn on the light",
            received_ts=10,
        )
        transport = FakeTransport()

        async def handler(message):
            transport.events.append(("handler", message.message_id))
            return MessageResponse("done")

        result = await process_next_message(
            store,
            transport,
            handler,
            owner_token="worker-1",
            now_ts=20,
            reaction_for=lambda message: "💡",
        )

        assert result.state == "completed"
        assert transport.events[0] == ("react", "m1", "💡")
        assert transport.events[1] == ("typing", "chat-a", True)
        assert transport.events[2] == ("handler", "m1")
        assert transport.events[3][0] == "send"
        assert transport.events[4] == ("typing", "chat-a", False)
        assert transport.send_count == 1
    finally:
        store.close()


@pytest.mark.asyncio
async def test_known_sent_outbox_prevents_duplicate_reply_on_retry(tmp_path):
    store = MessageStore(tmp_path / "messages.db")
    try:
        store.enqueue(
            provider="waha",
            message_id="m1",
            chat_id="chat-a",
            user_key="u1",
            text="hello",
            received_ts=10,
        )
        claimed = store.claim_next(owner_token="old-worker", now_ts=20)
        outbound = store.prepare_outbound(claimed, text="same reply", now_ts=20)
        store.mark_outbound_sent(
            outbound.response_key,
            provider_message_id="provider-existing",
            now_ts=20,
        )
        store.fail(
            claimed,
            owner_token="old-worker",
            error="worker_restarted",
            retry_at_ts=21,
        )

        transport = FakeTransport()

        async def handler(message):
            raise AssertionError("a persisted sent reply must not reenter the handler")

        result = await process_next_message(
            store,
            transport,
            handler,
            owner_token="new-worker",
            now_ts=21,
        )

        assert result.state == "completed"
        assert transport.send_count == 0
    finally:
        store.close()


@pytest.mark.asyncio
async def test_prepared_reply_resumes_exact_payload_after_send_failure_and_restart(tmp_path):
    path = tmp_path / "messages.db"
    store = MessageStore(path)
    store.enqueue(
        provider="waha",
        message_id="save",
        chat_id="chat-a",
        user_key="u1",
        text="save document",
        received_ts=10,
    )
    executions = []

    async def handler(message):
        executions.append(message.message_id)
        return MessageResponse("original verified confirmation")

    class FlakyTransport(FakeTransport):
        async def send_text(self, *args, **kwargs):
            result = await super().send_text(*args, **kwargs)
            if self.send_count == 1:
                raise RuntimeError("provider_unavailable")
            return result

    transport = FlakyTransport()
    try:
        first = await process_next_message(
            store, transport, handler, owner_token="old-worker", now_ts=20
        )
        assert first.state == "retry" and executions == ["save"]
    finally:
        store.close()
    restarted = MessageStore(path)
    try:

        async def no_reentry(message):
            raise AssertionError("retry may not execute a command or regenerate its reply")

        second = await process_next_message(
            restarted, transport, no_reentry, owner_token="new-worker", now_ts=40
        )
        assert second.state == "completed" and second.attempts == 2
        sends = [event for event in transport.events if event[0] == "send"]
        assert len(sends) == 2 and sends[0] == sends[1]
        assert sends[1][2] == "original verified confirmation"
        assert executions == ["save"]
    finally:
        restarted.close()


@pytest.mark.asyncio
async def test_cached_reply_cannot_resume_in_a_different_chat(tmp_path):
    store = MessageStore(tmp_path / "messages.db")
    store.enqueue(
        provider="waha",
        message_id="m1",
        chat_id="chat-a",
        user_key="u1",
        text="private request",
        received_ts=10,
    )
    claimed = store.claim_next(owner_token="old", now_ts=20)
    reply = store.prepare_outbound(claimed, text="private reply", now_ts=20)
    with store._db:
        store._db.execute(
            "UPDATE outbound_messages SET chat_id=? WHERE response_key=?",
            ("different-chat", reply.response_key),
        )
    store.fail(claimed, owner_token="old", error="restart", retry_at_ts=21)
    transport = FakeTransport()

    async def no_reentry(message):
        raise AssertionError("changed reply context must fail before handler execution")

    try:
        result = await process_next_message(
            store, transport, no_reentry, owner_token="new", now_ts=21
        )
        assert result.state == "retry" and result.last_error.endswith("outbound_context_changed")
        assert transport.send_count == 0
    finally:
        store.close()


@pytest.mark.asyncio
async def test_cached_private_reply_is_terminally_blocked_after_authorization_revocation(tmp_path):
    path = tmp_path / "messages.db"
    store = MessageStore(path)
    store.enqueue(
        provider="waha", message_id="private", chat_id="chat-a", user_key="u1",
        text="private read", received_ts=10,
    )
    claimed = store.claim_next(owner_token="old", now_ts=20)
    cached = store.prepare_outbound(claimed, text="private financial fields", now_ts=20)
    store.fail(claimed, owner_token="old", error="outage", retry_at_ts=21)
    store.close()
    restarted = MessageStore(path)
    transport = FakeTransport()
    checks = []

    async def no_handler(message):
        raise AssertionError("cached reply may not reenter its handler")

    async def denied(message, outbound):
        checks.append((message.message_id, outbound.response_key))
        return False

    try:
        result = await process_next_message(
            restarted, transport, no_handler, reply_allowed=denied,
            owner_token="new", now_ts=21,
        )
        assert result.state == "failed" and result.last_error.endswith("reply_authorization_denied")
        assert checks == [("private", cached.response_key)]
        assert transport.send_count == 0
        assert transport.events[-1] == ("typing", "chat-a", False)
        assert restarted.outbound_for(result).text == cached.text
        assert await process_next_message(
            restarted, transport, no_handler, reply_allowed=denied,
            owner_token="new", now_ts=22,
        ) is None
    finally:
        restarted.close()


@pytest.mark.asyncio
async def test_transient_reply_authorizer_failure_preserves_exact_payload_for_safe_retry(tmp_path):
    store = MessageStore(tmp_path / "messages.db")
    store.enqueue(
        provider="waha", message_id="private", chat_id="chat-a", user_key="u1",
        text="private read", received_ts=10,
    )
    transport = FakeTransport()
    executions = []

    async def handler(message):
        executions.append(message.message_id)
        return MessageResponse("original private reply")

    async def unavailable(message, outbound):
        raise TimeoutError("policy_unavailable")

    async def allowed(message, outbound):
        assert outbound.text == "original private reply"
        return True

    try:
        first = await process_next_message(
            store, transport, handler, reply_allowed=unavailable, owner_token="old", now_ts=20,
        )
        assert first.state == "retry" and transport.send_count == 0
        recovered = await process_next_message(
            store, transport, handler, reply_allowed=allowed, owner_token="new", now_ts=40,
        )
        assert recovered.state == "completed" and executions == ["private"]
        assert transport.send_count == 1
    finally:
        store.close()


@pytest.mark.asyncio
async def test_handler_failure_retries_without_sending_and_clears_typing(tmp_path):
    store = MessageStore(tmp_path / "messages.db")
    try:
        store.enqueue(
            provider="waha",
            message_id="m1",
            chat_id="chat-a",
            user_key="u1",
            text="hello",
            received_ts=10,
        )
        transport = FakeTransport()

        async def handler(message):
            raise RuntimeError("brain unavailable")

        result = await process_next_message(
            store,
            transport,
            handler,
            owner_token="worker-1",
            now_ts=20,
            retry_delay_seconds=5,
        )

        assert result.state == "retry"
        assert transport.send_count == 0
        assert transport.events[-1] == ("typing", "chat-a", False)
    finally:
        store.close()
