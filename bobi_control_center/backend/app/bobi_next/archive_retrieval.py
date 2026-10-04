"""Deterministic archive retrieval and outbound-dispatch preparation."""

from __future__ import annotations

from dataclasses import dataclass

from .archive_store import ArchiveRecord, ArchiveStore
from .authorization import UserPolicy
from .outbound_media import (
    OutboundMediaDispatch,
    OutboundMediaStore,
    media_dispatch_key,
)


@dataclass(slots=True, frozen=True)
class ArchiveCandidate:
    object_id: str
    title: str
    category: str
    kind: str
    filename: str


@dataclass(slots=True, frozen=True)
class ArchiveRetrievalResult:
    outcome: str
    reason: str
    dispatch: OutboundMediaDispatch | None = None
    candidates: tuple[ArchiveCandidate, ...] = ()


def archive_read_allowed(policy: UserPolicy, *, user_key: str) -> bool:
    if not policy.user_key.strip() or policy.user_key != user_key:
        return False
    capability = "archive.read"
    if capability in policy.denied_capabilities:
        return False
    if "*" not in policy.allowed_capabilities and capability not in policy.allowed_capabilities:
        return False
    if "*" not in policy.allowed_domains and "archive" not in policy.allowed_domains:
        return False
    return "archive.send" not in policy.denied_actions


def _candidate(record: ArchiveRecord) -> ArchiveCandidate:
    return ArchiveCandidate(
        object_id=record.object_id,
        title=record.title,
        category=record.category,
        kind=record.kind,
        filename=record.filename,
    )


def _deliverable(record: ArchiveRecord) -> bool:
    return bool(
        record.storage_uri.strip()
        and record.sha256.strip()
        and record.size_bytes > 0
        and record.mime_type.strip()
    )


class ArchiveRetrievalService:
    """Resolve private archive objects without letting AI choose arbitrary URIs."""

    def __init__(self, archive: ArchiveStore, outbox: OutboundMediaStore) -> None:
        self.archive = archive
        self.outbox = outbox

    def prepare_search(
        self,
        *,
        owner_key: str,
        policy: UserPolicy,
        provider: str,
        chat_id: str,
        request_id: str,
        query: str,
        kind: str = "",
        category: str = "",
        reply_to: str = "",
        caption: str = "",
        now_ts: int | None = None,
    ) -> ArchiveRetrievalResult:
        if not archive_read_allowed(policy, user_key=owner_key):
            return ArchiveRetrievalResult("blocked", "archive_read_denied")
        records = self.archive.search(
            owner_key=owner_key,
            query=query,
            kind=kind,
            category=category,
            limit=6,
        )
        if not records:
            return ArchiveRetrievalResult("not_found", "archive_not_found")
        if len(records) > 1:
            return ArchiveRetrievalResult(
                "clarification",
                "archive_ambiguous",
                candidates=tuple(_candidate(record) for record in records[:5]),
            )
        return self._prepare_record(
            records[0],
            owner_key=owner_key,
            provider=provider,
            chat_id=chat_id,
            request_id=request_id,
            reply_to=reply_to,
            caption=caption,
            now_ts=now_ts,
        )

    def prepare_object(
        self,
        *,
        owner_key: str,
        policy: UserPolicy,
        provider: str,
        chat_id: str,
        request_id: str,
        object_id: str,
        reply_to: str = "",
        caption: str = "",
        now_ts: int | None = None,
    ) -> ArchiveRetrievalResult:
        if not archive_read_allowed(policy, user_key=owner_key):
            return ArchiveRetrievalResult("blocked", "archive_read_denied")
        record = self.archive.get(object_id, owner_key=owner_key)
        if record is None:
            return ArchiveRetrievalResult("not_found", "archive_not_found")
        return self._prepare_record(
            record,
            owner_key=owner_key,
            provider=provider,
            chat_id=chat_id,
            request_id=request_id,
            reply_to=reply_to,
            caption=caption,
            now_ts=now_ts,
        )

    def _prepare_record(
        self,
        record: ArchiveRecord,
        *,
        owner_key: str,
        provider: str,
        chat_id: str,
        request_id: str,
        reply_to: str,
        caption: str,
        now_ts: int | None,
    ) -> ArchiveRetrievalResult:
        if record.owner_key != owner_key:
            return ArchiveRetrievalResult("blocked", "archive_owner_mismatch")
        if not _deliverable(record):
            return ArchiveRetrievalResult("unavailable", "archive_binary_unavailable")
        key = media_dispatch_key(provider, request_id, record.object_id)
        dispatch = self.outbox.prepare(
            dispatch_key=key,
            provider=provider,
            chat_id=chat_id,
            owner_key=owner_key,
            object_id=record.object_id,
            storage_uri=record.storage_uri,
            filename=record.filename or f"{record.title}.bin",
            mime_type=record.mime_type,
            size_bytes=record.size_bytes,
            sha256=record.sha256,
            caption=caption,
            reply_to=reply_to,
            now_ts=now_ts,
        )
        return ArchiveRetrievalResult("prepared", "archive_dispatch_prepared", dispatch)
