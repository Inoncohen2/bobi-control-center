from __future__ import annotations

import asyncio

import pytest

from app.bobi_next.ai_providers import AIProviderStore
from app.bobi_next.authorization import UserPolicy
from app.bobi_next.messaging import MessageResponse
from app.bobi_next.messaging_runtime import BobiNextMessagingRuntime
from app.bobi_next.pending_approval import PendingApprovalStore
from app.bobi_next.secret_vault import EncryptedSecretVault
from app.bobi_next.setup_store import SetupStore


class FakeHA:
    async def get_state(self, entity_id):
        del entity_id
        return None

    async def call_service(self, domain, service, data):
        del domain, service, data
        raise AssertionError("HA must not be called by these queue tests")


class RecordingTransport:
    def __init__(self):
        self.reactions = []
        self.typing = []
        self.sent = []

    async def react(self, message, emoji):
        self.reactions.append((message.message_id, emoji))

    async def set_typing(self, chat_id, enabled):
        self.typing.append((chat_id, enabled))

    async def send_text(self, chat_id, text, *, reply_to, idempotency_key):
        self.sent.append((chat_id, text, reply_to, idempotency_key))
        return f"provider-{reply_to}"


async def _devices():
    return ()


async def _policy(user_key: str):
    return UserPolicy(user_key)


def _configure_runtime(tmp_path, *, providers=("waha:a",)):
    setup = SetupStore(tmp_path / "bobi-next-setup.db")
    vault = EncryptedSecretVault(
        tmp_path / "bobi-next-secrets.db",
        tmp_path / "bobi-next-secrets.key",
    )
    ai = AIProviderStore(tmp_path / "bobi-next-ai.db")
    try:
        ai_ref = vault.put("ai:primary", "ai-secret", now_ts=1)
        ai.upsert(
            provider_key="ai:primary",
            provider_type="openai-compatible",
            display_name="AI",
            endpoint="https://ai.example.test/v1",
            model="intent-model",
            secret_ref=ai_ref,
            capabilities=frozenset({"intent"}),
            now_ts=1,
        )
        ai.select("ai:primary", now_ts=1)

        user = setup.create_user(display_name="Owner", role="owner", user_key="u1", now_ts=1)
        for index, provider_key in enumerate(providers):
            secret_ref = vault.put(f"messaging:{provider_key}", f"waha-secret-{index}", now_ts=1)
            setup.upsert_provider(
                provider_key=provider_key,
                provider_type="waha",
                display_name=provider_key,
                endpoint=f"http://waha-{index}:3000",
                session="default",
                engine="GOWS",
                secret_ref=secret_ref,
                now_ts=1,
            )
            setup.link_identity(
                provider_key=provider_key,
                external_id=f"{index + 1}@c.us",
                user_key=user.user_key,
                now_ts=1,
            )
    finally:
        ai.close()
        vault.close()

    pending = PendingApprovalStore(tmp_path / "bobi-next-pending-approvals.db")
    runtime = BobiNextMessagingRuntime(
        data_dir=tmp_path,
        setup=setup,
        ha=FakeHA(),
        list_devices=_devices,
        policy_for=_policy,
        pending_approvals=pending,
        poll_interval_seconds=0.01,
    )
    return runtime, setup, pending


def _event(sender: str, message_id: str, text: str):
    return {
        "event": "message",
        "session": "default",
        "payload": {
            "id": message_id,
            "timestamp": 100,
            "from": sender,
            "fromMe": False,
            "body": text,
            "hasMedia": False,
        },
    }


def test_prepare_builds_separate_durable_queue_per_provider(tmp_path):
    runtime, setup, pending = _configure_runtime(tmp_path, providers=("waha:a", "waha:b"))
    try:
        status = runtime.prepare()
        assert status.ready is True
        assert status.providers == ("waha:a", "waha:b")
        first = runtime.boundaries["waha:a"].messages.path
        second = runtime.boundaries["waha:b"].messages.path
        assert first != second
        assert first.exists()
        assert second.exists()
    finally:
        asyncio.run(runtime.aclose())
        pending.close()
        setup.close()


def test_ingest_deduplicates_within_provider_but_not_across_providers(tmp_path):
    runtime, setup, pending = _configure_runtime(tmp_path, providers=("waha:a", "waha:b"))
    try:
        assert runtime.prepare().ready is True
        first = runtime.ingest("waha:a", _event("1@c.us", "same-id", "hello"))
        duplicate = runtime.ingest("waha:a", _event("1@c.us", "same-id", "hello"))
        second_provider = runtime.ingest("waha:b", _event("2@c.us", "same-id", "hello"))
        assert first.accepted is True
        assert duplicate.accepted is False
        assert duplicate.duplicate is True
        assert second_provider.accepted is True
    finally:
        asyncio.run(runtime.aclose())
        pending.close()
        setup.close()


@pytest.mark.asyncio
async def test_worker_reacts_types_sends_once_and_completes_durable_message(tmp_path):
    runtime, setup, pending = _configure_runtime(tmp_path)
    try:
        assert runtime.prepare().ready is True
        boundary = runtime.boundaries["waha:a"]
        transport = RecordingTransport()

        async def handler(message):
            assert message.text == "hello"
            return MessageResponse("done")

        boundary.transport = transport
        boundary.handler = handler
        accepted = runtime.ingest("waha:a", _event("1@c.us", "m1", "hello"))
        assert accepted.accepted is True

        status = await runtime.start()
        assert status.ready is True
        for _ in range(100):
            message = boundary.messages.get_inbound("waha:a", "m1")
            if message is not None and message.state == "completed":
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("message_not_completed")

        assert transport.reactions == [("m1", "⚡")]
        assert transport.typing[0] == ("1@c.us", True)
        assert transport.typing[-1] == ("1@c.us", False)
        assert len(transport.sent) == 1
        assert transport.sent[0][1] == "done"
        assert transport.sent[0][2] == "m1"

        # A duplicate webhook cannot produce a second outbound reply.
        duplicate = runtime.ingest("waha:a", _event("1@c.us", "m1", "hello"))
        assert duplicate.duplicate is True
        await asyncio.sleep(0.03)
        assert len(transport.sent) == 1
    finally:
        await runtime.aclose()
        pending.close()
        setup.close()


def test_unknown_or_unprepared_provider_fails_closed(tmp_path):
    runtime, setup, pending = _configure_runtime(tmp_path)
    try:
        result = runtime.ingest("waha:unknown", _event("1@c.us", "m1", "hello"))
        assert result.accepted is False
        assert result.reason == "provider_not_runtime_enabled"
    finally:
        asyncio.run(runtime.aclose())
        pending.close()
        setup.close()
