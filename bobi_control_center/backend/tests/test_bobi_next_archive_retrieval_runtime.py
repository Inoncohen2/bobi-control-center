from __future__ import annotations

import hashlib

import pytest

from app.bobi_next.archive_messaging_runtime import ArchiveMessagingRuntime
from app.bobi_next.authorization import UserPolicy
from app.bobi_next.messaging import InboundMessage, MessageResponse
from app.bobi_next.outbound_media import media_dispatch_key
from app.bobi_next.pending_approval import PendingApprovalStore
from app.bobi_next.setup_store import SetupStore


class FakeHA:
    async def get_state(self, entity_id):
        del entity_id
        return None

    async def call_service(self, domain, service, data):
        del domain, service, data


async def _devices():
    return ()


async def _policy(user_key: str) -> UserPolicy:
    return UserPolicy(user_key)


def _message(text: str, *, message_id: str = "m1") -> InboundMessage:
    return InboundMessage(
        row_id=1,
        provider="waha-main",
        message_id=message_id,
        chat_id="972500000000@c.us",
        user_key="u1",
        text=text,
        kind="text",
        received_ts=100,
        state="running",
    )


async def _store_receipt(runtime: ArchiveMessagingRuntime, title: str, content: bytes):
    digest = hashlib.sha256(content).hexdigest()
    blob = await runtime.archive.storage.upload(
        owner_key="u1",
        content=content,
        filename=f"{title}.pdf",
        mime_type="application/pdf",
        sha256=digest,
        idempotency_key=f"test-{digest}",
    )
    return runtime.archive.index.register(
        owner_key="u1",
        kind="receipt",
        title=title,
        filename=f"{title}.pdf",
        mime_type="application/pdf",
        size_bytes=blob.size_bytes,
        sha256=blob.sha256,
        storage_uri=blob.storage_uri,
        now_ts=100,
    )


@pytest.mark.asyncio
async def test_explicit_retrieval_prepares_private_file_dispatch_without_ai(tmp_path):
    setup = SetupStore(tmp_path / "setup.db")
    pending = PendingApprovalStore(tmp_path / "pending.db")
    runtime = ArchiveMessagingRuntime(
        data_dir=tmp_path,
        setup=setup,
        ha=FakeHA(),
        list_devices=_devices,
        policy_for=_policy,
        pending_approvals=pending,
    )
    base_calls = 0

    async def base_handler(message):
        nonlocal base_calls
        base_calls += 1
        return MessageResponse(f"base:{message.text}")

    try:
        record = await _store_receipt(runtime, "איקאה", b"%PDF-test-ikea")
        handler = runtime._archive_retrieval_handler("waha-main", base_handler)
        response = await handler(_message("שלח לי את הקבלה של איקאה"))

        assert response.text == "📎 מצאתי. שולח את הקובץ עכשיו."
        assert base_calls == 0
        dispatch_key = media_dispatch_key(
            "waha-main",
            "archive:waha-main:m1",
            record.object_id,
        )
        dispatch = runtime.archive.outbox("waha-main").get(dispatch_key)
        assert dispatch is not None
        assert dispatch.owner_key == "u1"
        assert dispatch.reply_to == "m1"
        assert dispatch.storage_uri == record.storage_uri
    finally:
        await runtime.aclose()
        pending.close()
        setup.close()


@pytest.mark.asyncio
async def test_ambiguous_archive_retrieval_asks_for_detail_and_sends_nothing(tmp_path):
    setup = SetupStore(tmp_path / "setup.db")
    pending = PendingApprovalStore(tmp_path / "pending.db")
    runtime = ArchiveMessagingRuntime(
        data_dir=tmp_path,
        setup=setup,
        ha=FakeHA(),
        list_devices=_devices,
        policy_for=_policy,
        pending_approvals=pending,
    )

    async def base_handler(message):
        raise AssertionError(f"archive command reached base handler: {message.text}")

    try:
        first = await _store_receipt(runtime, "איקאה ינואר", b"%PDF-ikea-january")
        second = await _store_receipt(runtime, "איקאה פברואר", b"%PDF-ikea-february")
        handler = runtime._archive_retrieval_handler("waha-main", base_handler)
        response = await handler(_message("שלח לי את הקבלה של איקאה"))

        assert "כמה מסמכים" in response.text
        first_key = media_dispatch_key("waha-main", "archive:waha-main:m1", first.object_id)
        second_key = media_dispatch_key("waha-main", "archive:waha-main:m1", second.object_id)
        assert runtime.archive.outbox("waha-main").get(first_key) is None
        assert runtime.archive.outbox("waha-main").get(second_key) is None
    finally:
        await runtime.aclose()
        pending.close()
        setup.close()


@pytest.mark.asyncio
async def test_generic_picture_request_falls_through_to_normal_bobi_pipeline(tmp_path):
    setup = SetupStore(tmp_path / "setup.db")
    pending = PendingApprovalStore(tmp_path / "pending.db")
    runtime = ArchiveMessagingRuntime(
        data_dir=tmp_path,
        setup=setup,
        ha=FakeHA(),
        list_devices=_devices,
        policy_for=_policy,
        pending_approvals=pending,
    )
    base_calls = 0

    async def base_handler(message):
        nonlocal base_calls
        base_calls += 1
        return MessageResponse("normal-pipeline")

    try:
        handler = runtime._archive_retrieval_handler("waha-main", base_handler)
        response = await handler(_message("שלח לי תמונה של חתול"))
        assert response.text == "normal-pipeline"
        assert base_calls == 1
    finally:
        await runtime.aclose()
        pending.close()
        setup.close()


@pytest.mark.asyncio
async def test_shadow_retrieval_never_creates_private_file_dispatch(tmp_path):
    setup = SetupStore(tmp_path / "setup.db")
    pending = PendingApprovalStore(tmp_path / "pending.db")
    runtime = ArchiveMessagingRuntime(
        data_dir=tmp_path,
        setup=setup,
        ha=FakeHA(),
        list_devices=_devices,
        policy_for=_policy,
        pending_approvals=pending,
        dry_run=True,
    )

    async def base_handler(message):
        raise AssertionError("explicit retrieval must not reach AI")

    try:
        record = await _store_receipt(runtime, "איקאה", b"%PDF-shadow-ikea")
        response = await runtime._archive_retrieval_handler("waha-main", base_handler)(
            _message("שלח לי את הקבלה של איקאה"),
        )
        assert "Shadow" in response.text
        dispatch_key = media_dispatch_key("waha-main", "archive:waha-main:m1", record.object_id)
        assert runtime.archive.outbox("waha-main").get(dispatch_key) is None
    finally:
        await runtime.aclose()
        pending.close()
        setup.close()
