"""Composition root for Bobi Next's self-contained archive subsystem."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol

from .archive_capture import ArchiveBlobStorage, ArchiveCaptureService
from .archive_retrieval import ArchiveRetrievalService
from .archive_store import ArchiveStore
from .local_archive_storage import LocalArchiveStorage
from .outbound_media import (
    ArchiveBlobReader,
    OutboundMediaDispatch,
    OutboundMediaStore,
    OutboundMediaTransport,
    process_next_outbound_media,
)


class ArchiveBlobBackend(ArchiveBlobStorage, ArchiveBlobReader, Protocol):
    """One archive provider capable of both persistence and verified reads."""


def _provider_key(value: str) -> str:
    provider = value.strip()
    if not provider:
        raise ValueError("archive_provider_required")
    return hashlib.sha256(provider.encode()).hexdigest()[:20]


class ArchiveSubsystem:
    """Own archive semantics, private bytes and per-provider outbound journals."""

    def __init__(
        self,
        data_dir: str | Path,
        *,
        storage: ArchiveBlobBackend | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.index = ArchiveStore(self.data_dir / "bobi-next-archive.db")
        self.storage = storage or LocalArchiveStorage(
            self.data_dir / "bobi-next-archive-files"
        )
        self.capture = ArchiveCaptureService(self.index, self.storage)
        self._outboxes: dict[str, OutboundMediaStore] = {}
        self._closed = False

    def outbox(self, provider: str) -> OutboundMediaStore:
        if self._closed:
            raise RuntimeError("archive_subsystem_closed")
        key = provider.strip()
        if key not in self._outboxes:
            self._outboxes[key] = OutboundMediaStore(
                self.data_dir / f"bobi-next-outbound-media-{_provider_key(key)}.db"
            )
        return self._outboxes[key]

    def retrieval(self, provider: str) -> ArchiveRetrievalService:
        return ArchiveRetrievalService(self.index, self.outbox(provider))

    async def process_next(
        self,
        provider: str,
        transport: OutboundMediaTransport,
        *,
        owner_token: str,
        now_ts: int | None = None,
        lease_seconds: int = 90,
        max_bytes: int = 25 * 1024 * 1024,
    ) -> OutboundMediaDispatch | None:
        return await process_next_outbound_media(
            self.outbox(provider),
            self.storage,
            transport,
            owner_token=owner_token,
            now_ts=now_ts,
            lease_seconds=lease_seconds,
            max_bytes=max_bytes,
        )

    def close(self) -> None:
        if self._closed:
            return
        for outbox in self._outboxes.values():
            outbox.close()
        self._outboxes.clear()
        self.index.close()
        self._closed = True
