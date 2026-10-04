from __future__ import annotations

import asyncio

import pytest

from app.bobi_next.ai_providers import AIProviderStore
from app.bobi_next.authorization import UserPolicy
from app.bobi_next.interaction_dispatch import InteractionHandlerResult
from app.bobi_next.messaging_runtime import BobiNextMessagingRuntime
from app.bobi_next.pending_approval import PendingApprovalStore
from app.bobi_next.poll_interactions import PollVoteEvent
from app.bobi_next.secret_vault import EncryptedSecretVault
from app.bobi_next.setup_store import SetupStore


class FakeHA:
    async def get_state(self, entity_id):
        del entity_id
        return None

    async def call_service(self, domain, service, data):
        del domain, service, data
        raise AssertionError("HA must not be called by poll continuation tests")


class RecordingTransport:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str, str]] = []

    async def react(self, message, emoji: str) -> None:  # pragma: no cover
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
        self.sent.append((chat_id, text, reply_to, idempotency_key))
        return "provider-reply-1"


async def _devices():
    return ()


async def _policy(user_key: str):
    return UserPolicy(user_key)


def _configure_runtime(tmp_path, *, handlers=None):
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

        user = setup.create_user(
            display_name="Owner",
            role="owner",
            user_key="u1",
            now_ts=1,
        )
        secret_ref = vault.put("messaging:waha:a", "waha-secret", now_ts=1)
        setup.upsert_provider(
            provider_key="waha:a",
            provider_type="waha",
            display_name="WAHA",
            endpoint="http://waha:3000",
            session="default",
            engine="GOWS",
            secret_ref=secret_ref,
            now_ts=1,
        )
        setup.link_identity(
            provider_key="waha:a",
            external_id="1@c.us",
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
        interaction_handlers=handlers or {},
        poll_interval_seconds=0.01,
    )
    return runtime, setup, pending


def _poll_vote_event(*, vote_id: str = "vote-1", selected: str = "Yes") -> dict:
    return {
        "event": "poll.vote",
        "session": "default",
        "payload": {
            "poll": {"id": "poll-1", "fromMe": True},
            "vote": {
                "id": vote_id,
                "from": "1@c.us",
                "timestamp": 100,
                "selectedOptions": [selected],
            },
        },
    }


def test_live_poll_ingest_reconciles_contextual_selection_without_ai(tmp_path) -> None:
    runtime, setup, pending = _configure_runtime(tmp_path)
    try:
        assert runtime.prepare().ready is True
        interaction = runtime.interactions.register(
            provider="waha:a",
            poll_message_id="poll-1",
            chat_id="1@c.us",
            user_key="u1",
            question="Proceed?",
            option_keys={"Yes": "yes", "No": "no"},
            context_key="dialog:confirm-boiler",
            now_ts=1,
        )

        result = runtime.ingest("waha:a", _poll_vote_event())

        assert result.accepted is True
        dispatch = runtime.interaction_dispatches.get_for_interaction(
            interaction.interaction_id
        )
        assert dispatch is not None
        assert dispatch.selected_keys == ("yes",)
        assert dispatch.source_event_id == "vote-1"
    finally:
        asyncio.run(runtime.aclose())
        pending.close()
        setup.close()


@pytest.mark.asyncio
async def test_start_recovers_crash_window_and_dispatches_exactly_once(tmp_path) -> None:
    calls = []

    async def dialog_handler(selection):
        calls.append(selection)
        return InteractionHandlerResult(
            outcome="confirmed",
            response_text="✅ הבחירה התקבלה.",
        )

    runtime, setup, pending = _configure_runtime(
        tmp_path,
        handlers={"dialog": dialog_handler},
    )
    try:
        assert runtime.prepare().ready is True
        boundary = runtime.boundaries["waha:a"]
        transport = RecordingTransport()
        boundary.transport = transport

        interaction = runtime.interactions.register(
            provider="waha:a",
            poll_message_id="poll-1",
            chat_id="1@c.us",
            user_key="u1",
            question="Proceed?",
            option_keys={"Yes": "yes", "No": "no"},
            context_key="dialog:confirm-boiler",
            now_ts=1,
        )
        vote = runtime.interactions.apply_vote(
            PollVoteEvent(
                provider="waha:a",
                vote_id="vote-before-crash",
                poll_message_id="poll-1",
                voter_identity="1@c.us",
                selected_options=("Yes",),
                provider_timestamp=100,
            ),
            user_key="u1",
            now_ts=2,
        )
        assert vote.accepted is True
        assert runtime.interaction_dispatches.get_for_interaction(
            interaction.interaction_id
        ) is None

        status = await runtime.start()
        assert status.ready is True
        assert status.reason == "started"

        for _ in range(100):
            dispatch = runtime.interaction_dispatches.get_for_interaction(
                interaction.interaction_id
            )
            if dispatch is not None and dispatch.state == "completed":
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("interaction_dispatch_not_completed")

        assert len(calls) == 1
        assert calls[0].selected_keys == ("yes",)
        assert len(transport.sent) == 1
        assert transport.sent[0][0] == "1@c.us"
        assert transport.sent[0][1] == "✅ הבחירה התקבלה."
        assert transport.sent[0][2] == "poll-1"

        # Reconciliation and worker time cannot produce a second continuation.
        await asyncio.sleep(0.03)
        assert len(calls) == 1
        assert len(transport.sent) == 1
    finally:
        await runtime.aclose()
        pending.close()
        setup.close()
