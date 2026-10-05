"""Explicit, provider-neutral archive capture for Bobi Next.

Receiving media does not imply saving it. This service is called only after the
normal intent/policy path has decided the user explicitly asked Bobi to keep an
object. Trusted media bytes come from the existing MediaPipeline boundary; the
storage adapter owns binary persistence and ArchiveStore owns Bobi semantics.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Protocol

from .archive_store import ArchiveRecord, ArchiveStore
from .media_pipeline import LoadedMedia, MediaAnalysis
from .receipt_metadata import extract_financial_document


@dataclass(slots=True, frozen=True)
class StoredArchiveBlob:
    storage_uri: str
    size_bytes: int
    sha256: str


class ArchiveBlobStorage(Protocol):
    async def upload(
        self,
        *,
        owner_key: str,
        content: bytes,
        filename: str,
        mime_type: str,
        sha256: str,
        idempotency_key: str,
    ) -> StoredArchiveBlob: ...


@dataclass(slots=True, frozen=True)
class ArchiveCaptureRequest:
    owner_key: str
    kind: str
    title: str
    category: str = ""
    tags: tuple[str, ...] = ()
    source_message_id: str = ""
    text_excerpt: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def _idempotency_key(owner_key: str, digest: str) -> str:
    raw = f"{owner_key}\0{digest}".encode()
    return hashlib.sha256(raw).hexdigest()


class ArchiveCaptureService:
    """Persist one explicitly requested object through a typed storage adapter."""

    def __init__(self, archive: ArchiveStore, storage: ArchiveBlobStorage) -> None:
        self.archive = archive
        self.storage = storage

    async def capture(
        self,
        request: ArchiveCaptureRequest,
        *,
        media: LoadedMedia,
        analysis: MediaAnalysis | None = None,
        now_ts: int | None = None,
    ) -> ArchiveRecord:
        owner = str(request.owner_key or "").strip()
        if not owner:
            raise ValueError("archive_owner_required")
        if not isinstance(media.content, bytes) or not media.content:
            raise ValueError("archive_bytes_required")

        digest = hashlib.sha256(media.content).hexdigest()
        if media.sha256 and media.sha256.lower() != digest:
            raise ValueError("archive_media_digest_mismatch")

        descriptor = media.descriptor
        filename = str(descriptor.filename or "").strip()[:255]
        mime_type = str(descriptor.mimetype or "").strip().lower()
        stored = await self.storage.upload(
            owner_key=owner,
            content=media.content,
            filename=filename,
            mime_type=mime_type,
            sha256=digest,
            idempotency_key=_idempotency_key(owner, digest),
        )
        if not isinstance(stored, StoredArchiveBlob):
            raise TypeError("archive_storage_invalid_result")
        if stored.sha256.lower() != digest:
            raise ValueError("archive_storage_digest_mismatch")
        if int(stored.size_bytes) != len(media.content):
            raise ValueError("archive_storage_size_mismatch")
        if not str(stored.storage_uri or "").strip():
            raise ValueError("archive_storage_uri_required")

        derived_text = str(request.text_excerpt or "").strip()
        metadata = dict(request.metadata)
        if analysis is not None:
            if not derived_text:
                derived_text = str(analysis.text or analysis.summary or "").strip()
            if analysis.metadata:
                metadata.setdefault("media_analysis", dict(analysis.metadata))

        metadata.setdefault("source_provider", descriptor.provider)
        metadata.setdefault("source_kind", descriptor.kind)
        analysis_text = ""
        if analysis is not None and analysis.metadata.get("sha256", digest) == digest:
            analysis_text = analysis.text
        extraction = extract_financial_document(analysis_text, requested_kind=request.kind)
        metadata.pop("financial_document", None)
        kind = request.kind
        if extraction is not None:
            # Advisory metadata cannot replace explicit save/category authority
            # or create expenses/reminders. Do not accept a caller's forged
            # verified extraction under this reserved key.
            metadata["financial_document"] = extraction.metadata(media_sha256=digest)
            if kind in {"document", "image", "other"}:
                kind = extraction.kind

        return self.archive.register(
            owner_key=owner,
            kind=kind,
            title=request.title,
            category=request.category,
            filename=filename,
            mime_type=mime_type,
            size_bytes=len(media.content),
            sha256=digest,
            storage_uri=stored.storage_uri,
            source_message_id=request.source_message_id or descriptor.message_id,
            text_excerpt=derived_text,
            tags=request.tags,
            metadata=metadata,
            now_ts=now_ts,
        )
