from __future__ import annotations

import time

import pytest
import pytest_asyncio

from app.bobi_next.archive_capture import ArchiveCaptureRequest
from app.bobi_next.archive_messaging_runtime import ArchiveMessagingRuntime
from app.bobi_next.authorization import UserPolicy
from app.bobi_next.interaction_dispatch import InteractionSelection
from app.bobi_next.media_pipeline import LoadedMedia, MediaDescriptor
from app.bobi_next.messaging import InboundMessage, MessageResponse
from app.bobi_next.pending_approval import PendingApprovalStore
from app.bobi_next.setup_store import SetupStore


class NeverHA:
    async def get_state(self, entity_id):
        raise AssertionError("archive approval may not query HA")

    async def call_service(self, *args):
        raise AssertionError("archive mutations may not invoke HA")


async def devices():
    return ()


async def policy(user):
    return UserPolicy(user)


@pytest_asyncio.fixture
async def runtime(tmp_path):
    setup = SetupStore(tmp_path / "setup.db")
    pending = PendingApprovalStore(tmp_path / "pending.db")
    result = ArchiveMessagingRuntime(
        data_dir=tmp_path, setup=setup, ha=NeverHA(), list_devices=devices,
        policy_for=policy, pending_approvals=pending,
    )
    yield result
    await result.aclose()
    pending.close()
    setup.close()


def message(text, key="m1", *, kind="text", metadata=None):
    return InboundMessage(
        row_id=1, provider="waha", message_id=key, chat_id="chat", user_key="u1",
        text=text, kind=kind, received_ts=100, state="running", metadata=metadata or {},
    )


async def saved(runtime):
    return await runtime.archive.capture.capture(
        ArchiveCaptureRequest(owner_key="u1", kind="document", title="ביטוח", category="ביטוחים"),
        media=LoadedMedia(
            descriptor=MediaDescriptor(
                provider="waha", message_id="attachment", kind="document",
                mimetype="application/pdf", filename="insurance.pdf",
            ), content=b"%PDF private bytes", sha256="",
        ), now_ts=100,
    )


@pytest.mark.asyncio
async def test_conversation_move_delete_approval_restore_and_retrieval(runtime):
    item = await saved(runtime)

    async def base(msg):
        raise AssertionError("archive request must not reach AI")

    handler = runtime._archive_retrieval_handler("waha", base)
    assert "רכב" in (await handler(message("העבר את המסמך ביטוח לתיקיית רכב"))).text
    assert "כן או לא" in (await handler(message("מחק את המסמך ביטוח", "delete"))).text
    assert "סל המחזור" in (await handler(message("כן", "confirm"))).text
    assert "לא מצאתי" in (await handler(message("שלח לי את המסמך ביטוח", "retrieve"))).text
    assert "שחזרתי" in (await handler(message("שחזר את המסמך ביטוח", "restore"))).text
    assert "שולח" in (await handler(message("שלח לי את המסמך ביטוח", "retrieved"))).text
    current = runtime.archive.index.get(item.object_id, owner_key="u1")
    assert current.category == "רכב" and current.status == "active"
    assert await runtime.archive.storage.read(current.storage_uri, max_bytes=100) == b"%PDF private bytes"


@pytest.mark.asyncio
async def test_media_and_quoted_content_do_not_confirm_archive_mutation(runtime):
    item = await saved(runtime)
    calls = []

    async def base(msg):
        calls.append(msg)
        return MessageResponse("normal context")

    handler = runtime._archive_retrieval_handler("waha", base)
    await handler(message("מחק את המסמך ביטוח"))
    await handler(message("כן", "voice", kind="voice"))
    await handler(message("תסביר", "quote", metadata={"quoted": {"text": "כן"}}))
    assert len(calls) == 2
    assert runtime.archive.index.get(item.object_id, owner_key="u1")


@pytest.mark.asyncio
async def test_exact_poll_approval_uses_archive_executor_and_replays_safely(runtime):
    item = await saved(runtime)

    async def base(msg):
        raise AssertionError("archive command reached AI")

    await runtime._archive_retrieval_handler("waha", base)(message("מחק את המסמך ביטוח"))
    pending = runtime.pending_approvals.peek_latest(user_key="u1")
    selection = InteractionSelection(
        dispatch_id="dispatch", provider="waha", interaction_id="poll", poll_message_id="poll-id",
        chat_id="chat", user_key="u1", context_key=f"approval:{pending.approval_request_id}",
        selected_keys=("approve",), source_event_id="vote", provider_timestamp=100,
    )
    handler = runtime.interaction_handlers["approval"]
    assert "סל המחזור" in (await handler(selection)).response_text
    assert "סל המחזור" in (await handler(selection)).response_text
    assert runtime.archive.index.get(item.object_id, owner_key="u1", include_deleted=True).revision == 1


@pytest.mark.asyncio
async def test_shadow_confirmation_leaves_pending_and_archive_intact(runtime):
    item = await saved(runtime)

    async def base(msg):
        return MessageResponse("base")

    handler = runtime._archive_retrieval_handler("waha", base)
    await handler(message("מחק את המסמך ביטוח"))
    pending = runtime.pending_approvals.peek_latest(user_key="u1")
    runtime.dry_run = True
    assert "Shadow" in (await handler(message("כן", "confirm"))).text
    assert runtime.pending_approvals.get(pending.approval_request_id).state == "pending"
    assert runtime.archive.index.get(item.object_id, owner_key="u1").revision == 0


@pytest.mark.asyncio
async def test_ha_approval_path_rejects_archive_before_any_ha_call(runtime):
    from app.bobi_next.approval_continuation import approve_latest_pending

    item = await saved(runtime)

    async def base(msg):
        return MessageResponse("base")

    await runtime._archive_retrieval_handler("waha", base)(message("מחק את המסמך ביטוח"))
    result = await approve_latest_pending(
        runtime.pending_approvals, runtime.approvals, NeverHA(), user_key="u1",
        policy_for=policy, owner_token="HA-approver", now_ts=int(time.time()),
    )
    assert result.reason == "non_ha_approval_plan"
    assert runtime.archive.index.get(item.object_id, owner_key="u1")
