from __future__ import annotations

import hashlib

import pytest

from app.bobi_next.archive_capture import (
    ArchiveCaptureRequest,
    ArchiveCaptureService,
    StoredArchiveBlob,
)
from app.bobi_next.archive_store import ArchiveStore
from app.bobi_next.media_pipeline import LoadedMedia, MediaAnalysis, MediaDescriptor


class RecordingStorage:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def upload(
        self,
        *,
        owner_key: str,
        content: bytes,
        filename: str,
        mime_type: str,
        sha256: str,
        idempotency_key: str,
    ) -> StoredArchiveBlob:
        self.calls.append(
            {
                "owner_key": owner_key,
                "content": content,
                "filename": filename,
                "mime_type": mime_type,
                "sha256": sha256,
                "idempotency_key": idempotency_key,
            }
        )
        return StoredArchiveBlob(
            storage_uri=f"storage://objects/{sha256}",
            size_bytes=len(content),
            sha256=sha256,
        )


def loaded_media(content: bytes = b"%PDF-1.7 example") -> LoadedMedia:
    digest = hashlib.sha256(content).hexdigest()
    return LoadedMedia(
        descriptor=MediaDescriptor(
            provider="waha-main",
            message_id="msg-1",
            kind="document",
            mimetype="application/pdf",
            filename="policy.pdf",
            provider_ref="provider-private-ref",
        ),
        content=content,
        sha256=digest,
    )


@pytest.mark.asyncio
async def test_explicit_capture_uploads_and_registers_semantics(tmp_path) -> None:
    archive = ArchiveStore(tmp_path / "archive.db")
    storage = RecordingStorage()
    service = ArchiveCaptureService(archive, storage)

    record = await service.capture(
        ArchiveCaptureRequest(
            owner_key="u1",
            kind="document",
            title="Car insurance",
            category="vehicle",
            tags=("insurance", "car"),
            source_message_id="msg-1",
            metadata={"issuer": "Example"},
        ),
        media=loaded_media(),
        analysis=MediaAnalysis(
            text="Insurance policy valid until 2027",
            metadata={"pages": 3},
        ),
        now_ts=100,
    )

    assert record.title == "Car insurance"
    assert record.category == "vehicle"
    assert record.filename == "policy.pdf"
    assert record.mime_type == "application/pdf"
    assert record.storage_uri.startswith("storage://objects/")
    assert record.text_excerpt == "Insurance policy valid until 2027"
    assert record.metadata["source_provider"] == "waha-main"
    assert record.metadata["source_kind"] == "document"
    assert record.metadata["media_analysis"] == {"pages": 3}
    assert "provider-private-ref" not in str(record.metadata)
    assert len(storage.calls) == 1
    assert storage.calls[0]["idempotency_key"] != "u1"
    archive.close()


@pytest.mark.asyncio
async def test_same_owner_and_bytes_use_stable_storage_idempotency_key(tmp_path) -> None:
    archive = ArchiveStore(tmp_path / "archive.db")
    storage = RecordingStorage()
    service = ArchiveCaptureService(archive, storage)
    request = ArchiveCaptureRequest(owner_key="u1", kind="document", title="Policy")
    media = loaded_media()

    first = await service.capture(request, media=media, now_ts=100)
    second = await service.capture(request, media=media, now_ts=110)

    assert first.object_id == second.object_id
    assert len(storage.calls) == 2
    assert storage.calls[0]["idempotency_key"] == storage.calls[1]["idempotency_key"]
    archive.close()


@pytest.mark.asyncio
async def test_capture_rejects_mutated_media_digest_before_upload(tmp_path) -> None:
    archive = ArchiveStore(tmp_path / "archive.db")
    storage = RecordingStorage()
    service = ArchiveCaptureService(archive, storage)
    media = loaded_media()
    corrupted = LoadedMedia(
        descriptor=media.descriptor,
        content=media.content + b"changed",
        sha256=media.sha256,
    )

    with pytest.raises(ValueError, match="archive_media_digest_mismatch"):
        await service.capture(
            ArchiveCaptureRequest(owner_key="u1", kind="document", title="Policy"),
            media=corrupted,
        )

    assert storage.calls == []
    archive.close()


class BadStorage(RecordingStorage):
    async def upload(self, **kwargs) -> StoredArchiveBlob:
        result = await super().upload(**kwargs)
        return StoredArchiveBlob(
            storage_uri=result.storage_uri,
            size_bytes=result.size_bytes,
            sha256="0" * 64,
        )


@pytest.mark.asyncio
async def test_capture_rejects_storage_integrity_mismatch(tmp_path) -> None:
    archive = ArchiveStore(tmp_path / "archive.db")
    service = ArchiveCaptureService(archive, BadStorage())

    with pytest.raises(ValueError, match="archive_storage_digest_mismatch"):
        await service.capture(
            ArchiveCaptureRequest(owner_key="u1", kind="document", title="Policy"),
            media=loaded_media(),
        )

    assert archive.search(owner_key="u1") == ()
    archive.close()
