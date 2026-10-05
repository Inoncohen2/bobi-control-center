from __future__ import annotations

import hashlib

import pytest

from app.bobi_next.archive_capture import ArchiveCaptureRequest
from app.bobi_next.archive_subsystem import ArchiveSubsystem
from app.bobi_next.authorization import UserPolicy
from app.bobi_next.media_pipeline import LoadedMedia, MediaDescriptor
from app.bobi_next.outbound_media import OutboundMediaPayload


class RecordingTransport:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send_file(
        self,
        chat_id: str,
        payload: OutboundMediaPayload,
        *,
        caption: str,
        reply_to: str,
    ) -> str:
        self.calls.append(
            {
                "chat_id": chat_id,
                "payload": payload,
                "caption": caption,
                "reply_to": reply_to,
            }
        )
        return "provider-file-id"


def loaded(content: bytes = b"private pdf") -> LoadedMedia:
    return LoadedMedia(
        descriptor=MediaDescriptor(
            provider="waha-main",
            message_id="incoming-1",
            kind="document",
            mimetype="application/pdf",
            filename="insurance.pdf",
        ),
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
    )


@pytest.mark.asyncio
async def test_archive_subsystem_save_find_and_send_end_to_end(tmp_path) -> None:
    subsystem = ArchiveSubsystem(tmp_path)
    media = loaded()
    saved = await subsystem.capture.capture(
        ArchiveCaptureRequest(
            owner_key="u1",
            kind="document",
            title="Car insurance",
            category="vehicle",
        ),
        media=media,
        now_ts=100,
    )

    retrieval = subsystem.retrieval("waha-main")
    prepared = retrieval.prepare_search(
        owner_key="u1",
        policy=UserPolicy(user_key="u1"),
        provider="waha-main",
        chat_id="chat-1",
        request_id="request-send-1",
        query="Car insurance",
        reply_to="incoming-2",
        caption="הנה ביטוח הרכב",
        now_ts=110,
    )
    assert prepared.outcome == "prepared"
    assert prepared.dispatch is not None
    assert prepared.dispatch.object_id == saved.object_id

    transport = RecordingTransport()
    sent = await subsystem.process_next(
        "waha-main",
        transport,
        owner_token="media-worker:waha-main",
        now_ts=120,
    )

    assert sent is not None
    assert sent.state == "sent"
    assert sent.provider_message_id == "provider-file-id"
    assert len(transport.calls) == 1
    assert transport.calls[0]["payload"].content == media.content
    assert transport.calls[0]["payload"].filename == "insurance.pdf"
    assert transport.calls[0]["caption"] == "הנה ביטוח הרכב"
    subsystem.close()


def test_archive_subsystem_keeps_provider_outboxes_isolated(tmp_path) -> None:
    subsystem = ArchiveSubsystem(tmp_path)
    first = subsystem.outbox("waha-main")
    second = subsystem.outbox("waha-secondary")
    again = subsystem.outbox("waha-main")

    assert first is again
    assert first is not second
    assert first.path != second.path
    subsystem.close()


def test_archive_subsystem_close_is_idempotent(tmp_path) -> None:
    subsystem = ArchiveSubsystem(tmp_path)
    subsystem.outbox("waha-main")
    subsystem.close()
    subsystem.close()

    with pytest.raises(RuntimeError, match="archive_subsystem_closed"):
        subsystem.outbox("waha-main")


@pytest.mark.asyncio
@pytest.mark.parametrize("when", ["before_read", "during_read", "permission_revoked"])
async def test_deleted_or_revoked_archive_dispatch_cannot_send(tmp_path, when):
    subsystem = ArchiveSubsystem(tmp_path)
    media = loaded()
    saved = await subsystem.capture.capture(
        ArchiveCaptureRequest(owner_key="u1", kind="document", title="Insurance"),
        media=media, now_ts=100,
    )
    subsystem.retrieval("waha").prepare_object(
        owner_key="u1", policy=UserPolicy("u1"), provider="waha", chat_id="chat",
        request_id="send", object_id=saved.object_id, now_ts=101,
    )
    original = subsystem.storage

    class Reader:
        async def read(self, uri, *, max_bytes):
            data = await original.read(uri, max_bytes=max_bytes)
            if when == "during_read":
                subsystem.index.soft_delete(saved.object_id, owner_key="u1", now_ts=102)
            return data

    subsystem.storage = Reader()
    if when == "before_read":
        subsystem.index.soft_delete(saved.object_id, owner_key="u1", now_ts=102)

    async def allowed(dispatch):
        return when != "permission_revoked"

    transport = RecordingTransport()
    try:
        result = await subsystem.process_next(
            "waha", transport, owner_token="worker", now_ts=103, dispatch_allowed=allowed,
        )
        assert result.state == "failed"
        assert result.last_error == "archive_delivery_not_authorized"
        assert transport.calls == []
    finally:
        subsystem.close()
