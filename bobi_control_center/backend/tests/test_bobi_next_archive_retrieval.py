from __future__ import annotations

import hashlib

from app.bobi_next.archive_retrieval import ArchiveRetrievalService
from app.bobi_next.archive_store import ArchiveStore
from app.bobi_next.authorization import UserPolicy
from app.bobi_next.outbound_media import OutboundMediaStore


def register(
    archive: ArchiveStore,
    *,
    owner: str,
    title: str,
    category: str = "docs",
    content: bytes = b"pdf",
    storage_uri: str = "archive://file",
):
    return archive.register(
        owner_key=owner,
        kind="document",
        title=title,
        category=category,
        filename=f"{title}.pdf",
        mime_type="application/pdf",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        storage_uri=storage_uri,
        now_ts=100,
    )


def allow(user: str) -> UserPolicy:
    return UserPolicy(user_key=user)


def test_unique_search_prepares_owner_scoped_dispatch(tmp_path) -> None:
    archive = ArchiveStore(tmp_path / "archive.db")
    outbox = OutboundMediaStore(tmp_path / "outbox.db")
    service = ArchiveRetrievalService(archive, outbox)
    record = register(archive, owner="u1", title="Car insurance")
    register(archive, owner="u2", title="Car insurance")

    result = service.prepare_search(
        owner_key="u1",
        policy=allow("u1"),
        provider="waha-main",
        chat_id="chat-1",
        request_id="request-1",
        query="Car insurance",
        reply_to="incoming-1",
        caption="הנה המסמך",
        now_ts=110,
    )

    assert result.outcome == "prepared"
    assert result.dispatch is not None
    assert result.dispatch.object_id == record.object_id
    assert result.dispatch.owner_key == "u1"
    assert result.dispatch.storage_uri == "archive://file"
    assert result.dispatch.reply_to == "incoming-1"
    archive.close()
    outbox.close()


def test_ambiguous_search_never_chooses_for_user(tmp_path) -> None:
    archive = ArchiveStore(tmp_path / "archive.db")
    outbox = OutboundMediaStore(tmp_path / "outbox.db")
    service = ArchiveRetrievalService(archive, outbox)
    register(archive, owner="u1", title="Insurance 2026", content=b"one")
    register(archive, owner="u1", title="Insurance 2027", content=b"two")

    result = service.prepare_search(
        owner_key="u1",
        policy=allow("u1"),
        provider="waha-main",
        chat_id="chat-1",
        request_id="request-1",
        query="Insurance",
    )

    assert result.outcome == "clarification"
    assert len(result.candidates) == 2
    assert outbox.claim_next(owner_token="worker", now_ts=120) is None
    archive.close()
    outbox.close()


def test_exact_object_cannot_cross_owner_boundary(tmp_path) -> None:
    archive = ArchiveStore(tmp_path / "archive.db")
    outbox = OutboundMediaStore(tmp_path / "outbox.db")
    service = ArchiveRetrievalService(archive, outbox)
    other = register(archive, owner="u2", title="Private")

    result = service.prepare_object(
        owner_key="u1",
        policy=allow("u1"),
        provider="waha-main",
        chat_id="chat-1",
        request_id="request-1",
        object_id=other.object_id,
    )

    assert result.outcome == "not_found"
    assert outbox.claim_next(owner_token="worker", now_ts=120) is None
    archive.close()
    outbox.close()


def test_read_permission_is_fail_closed(tmp_path) -> None:
    archive = ArchiveStore(tmp_path / "archive.db")
    outbox = OutboundMediaStore(tmp_path / "outbox.db")
    service = ArchiveRetrievalService(archive, outbox)
    register(archive, owner="u1", title="Policy")
    policy = UserPolicy(
        user_key="u1",
        allowed_capabilities=frozenset({"power"}),
        allowed_domains=frozenset({"light"}),
    )

    result = service.prepare_search(
        owner_key="u1",
        policy=policy,
        provider="waha-main",
        chat_id="chat-1",
        request_id="request-1",
        query="Policy",
    )

    assert result.outcome == "blocked"
    assert result.reason == "archive_read_denied"
    archive.close()
    outbox.close()


def test_metadata_only_record_is_not_deliverable(tmp_path) -> None:
    archive = ArchiveStore(tmp_path / "archive.db")
    outbox = OutboundMediaStore(tmp_path / "outbox.db")
    service = ArchiveRetrievalService(archive, outbox)
    record = archive.register(
        owner_key="u1",
        kind="note",
        title="A note",
        text_excerpt="text only",
        now_ts=100,
    )

    result = service.prepare_object(
        owner_key="u1",
        policy=allow("u1"),
        provider="waha-main",
        chat_id="chat-1",
        request_id="request-1",
        object_id=record.object_id,
    )

    assert result.outcome == "unavailable"
    assert result.reason == "archive_binary_unavailable"
    archive.close()
    outbox.close()
