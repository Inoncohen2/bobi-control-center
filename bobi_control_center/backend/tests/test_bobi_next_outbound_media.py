from __future__ import annotations

import hashlib

import pytest

from app.bobi_next.outbound_media import (
    OutboundMediaPayload,
    OutboundMediaStore,
    media_dispatch_key,
    process_next_outbound_media,
)


class StaticReader:
    def __init__(self, content: bytes, *, fail: bool = False) -> None:
        self.content = content
        self.fail = fail
        self.calls: list[tuple[str, int]] = []

    async def read(self, storage_uri: str, *, max_bytes: int) -> bytes:
        self.calls.append((storage_uri, max_bytes))
        if self.fail:
            raise RuntimeError("storage offline")
        return self.content


class RecordingTransport:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
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
        if self.fail:
            raise TimeoutError("ambiguous provider timeout")
        return "provider-message-1"


def prepare(store: OutboundMediaStore, content: bytes, *, now_ts: int = 100):
    digest = hashlib.sha256(content).hexdigest()
    key = media_dispatch_key("waha-main", "request-1", "object-1")
    dispatch = store.prepare(
        dispatch_key=key,
        provider="waha-main",
        chat_id="chat-1",
        owner_key="u1",
        object_id="object-1",
        storage_uri="archive://object-1",
        filename="policy.pdf",
        mime_type="application/pdf",
        size_bytes=len(content),
        sha256=digest,
        caption="Here is the policy",
        reply_to="incoming-1",
        now_ts=now_ts,
    )
    return key, dispatch


@pytest.mark.asyncio
async def test_successful_media_dispatch_is_sent_once(tmp_path) -> None:
    store = OutboundMediaStore(tmp_path / "outbound-media.db")
    content = b"pdf bytes"
    key, first = prepare(store, content)
    duplicate = store.prepare(
        dispatch_key=key,
        provider=first.provider,
        chat_id=first.chat_id,
        owner_key=first.owner_key,
        object_id=first.object_id,
        storage_uri=first.storage_uri,
        filename=first.filename,
        mime_type=first.mime_type,
        size_bytes=first.size_bytes,
        sha256=first.sha256,
        now_ts=101,
    )
    assert duplicate.dispatch_key == key

    transport = RecordingTransport()
    result = await process_next_outbound_media(
        store,
        StaticReader(content),
        transport,
        owner_token="worker-1",
        now_ts=110,
    )

    assert result is not None
    assert result.state == "sent"
    assert result.provider_message_id == "provider-message-1"
    assert len(transport.calls) == 1
    assert transport.calls[0]["payload"].content == content
    assert await process_next_outbound_media(
        store,
        StaticReader(content),
        transport,
        owner_token="worker-1",
        now_ts=120,
    ) is None
    assert len(transport.calls) == 1
    store.close()


@pytest.mark.asyncio
async def test_blob_failure_before_provider_call_is_retryable(tmp_path) -> None:
    store = OutboundMediaStore(tmp_path / "outbound-media.db")
    content = b"pdf bytes"
    key, _ = prepare(store, content)
    transport = RecordingTransport()

    result = await process_next_outbound_media(
        store,
        StaticReader(content, fail=True),
        transport,
        owner_token="worker-1",
        now_ts=110,
    )

    assert result is not None
    assert result.state == "retry"
    assert result.next_attempt_ts == 140
    assert transport.calls == []
    assert store.get(key).last_error == "blob_read:RuntimeError"
    store.close()


@pytest.mark.asyncio
async def test_provider_error_after_send_boundary_becomes_uncertain(tmp_path) -> None:
    store = OutboundMediaStore(tmp_path / "outbound-media.db")
    content = b"pdf bytes"
    key, _ = prepare(store, content)
    transport = RecordingTransport(fail=True)

    result = await process_next_outbound_media(
        store,
        StaticReader(content),
        transport,
        owner_token="worker-1",
        now_ts=110,
    )

    assert result is not None
    assert result.state == "uncertain"
    assert len(transport.calls) == 1
    # The normal worker never retries ambiguous provider sends.
    assert await process_next_outbound_media(
        store,
        StaticReader(content),
        transport,
        owner_token="worker-2",
        now_ts=1000,
    ) is None
    assert len(transport.calls) == 1

    resolved = store.resolve_uncertain(
        key,
        resolution="sent",
        provider_message_id="reconciled-provider-id",
        now_ts=1001,
    )
    assert resolved.state == "sent"
    assert resolved.provider_message_id == "reconciled-provider-id"
    store.close()


def test_expired_loading_retries_but_expired_sending_becomes_uncertain(tmp_path) -> None:
    store = OutboundMediaStore(tmp_path / "outbound-media.db")
    content = b"pdf bytes"
    key, _ = prepare(store, content)

    loading = store.claim_next(owner_token="worker-1", now_ts=110, lease_seconds=5)
    assert loading is not None and loading.state == "loading"
    reclaimed = store.claim_next(owner_token="worker-2", now_ts=116, lease_seconds=5)
    assert reclaimed is not None
    assert reclaimed.dispatch_key == key
    assert reclaimed.state == "loading"
    assert reclaimed.attempts == 2

    sending = store.begin_send(
        reclaimed,
        owner_token="worker-2",
        now_ts=116,
        lease_seconds=5,
    )
    assert sending.state == "sending"
    assert store.claim_next(owner_token="worker-3", now_ts=122, lease_seconds=5) is None
    uncertain = store.get(key)
    assert uncertain is not None
    assert uncertain.state == "uncertain"
    assert uncertain.last_error == "sending_lease_expired"
    store.close()


@pytest.mark.asyncio
async def test_integrity_mismatch_fails_before_send(tmp_path) -> None:
    store = OutboundMediaStore(tmp_path / "outbound-media.db")
    original = b"original bytes"
    _, _ = prepare(store, original)
    transport = RecordingTransport()

    result = await process_next_outbound_media(
        store,
        StaticReader(b"tampered bytes"),
        transport,
        owner_token="worker-1",
        now_ts=110,
    )

    assert result is not None
    assert result.state == "failed"
    assert result.last_error in {"blob_size_mismatch", "blob_digest_mismatch"}
    assert transport.calls == []
    store.close()
