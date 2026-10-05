from __future__ import annotations

import base64
import hashlib
import json

import httpx
import pytest

from app.bobi_next.cloud_archive_storage import BobiCloudArchiveStorage
from app.bobi_next.supabase_storage import BobiStorageClient, BobiStorageError


class FakeStorage:
    endpoint = "https://project.supabase.co/functions/v1/bobi-storage"

    def __init__(self) -> None:
        self.uploads: list[dict] = []
        self.signed: list[dict] = []
        self.signed_url = (
            "https://project.supabase.co/storage/v1/object/sign/bobi-archive/u/file?token=abc"
        )

    async def archive_upload(self, **kwargs):
        self.uploads.append(dict(kwargs))
        content = base64.b64decode(kwargs["media_base64"])
        return {
            "ok": True,
            "media": {
                "id": "media-123",
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            },
        }

    async def archive_signed_url(self, **kwargs):
        self.signed.append(dict(kwargs))
        return {"ok": True, "signed_url": self.signed_url}


@pytest.mark.asyncio
async def test_cloud_archive_upload_uses_private_subject_and_validates_blob() -> None:
    storage = FakeStorage()
    adapter = BobiCloudArchiveStorage(storage, installation_id="install-1")
    content = b"private document"
    digest = hashlib.sha256(content).hexdigest()

    result = await adapter.upload(
        owner_key="972501234567@c.us",
        content=content,
        filename="invoice.pdf",
        mime_type="application/pdf",
        sha256=digest,
        idempotency_key="idem-1",
    )

    assert result.sha256 == digest
    assert result.size_bytes == len(content)
    assert result.storage_uri.startswith("bobi-storage://bobi2_")
    assert "972501234567" not in result.storage_uri
    assert len(storage.uploads) == 1
    upload = storage.uploads[0]
    assert upload["external_id"].startswith("bobi2_")
    assert "972501234567" not in upload["external_id"]
    assert base64.b64decode(upload["media_base64"]) == content
    assert upload["idempotency_key"] == "idem-1"


@pytest.mark.asyncio
async def test_cloud_archive_upload_rejects_storage_digest_mismatch() -> None:
    class BadStorage(FakeStorage):
        async def archive_upload(self, **kwargs):
            return {
                "ok": True,
                "media": {"id": "media-123", "sha256": "0" * 64, "size_bytes": 3},
            }

    content = b"abc"
    adapter = BobiCloudArchiveStorage(BadStorage(), installation_id="install-1")
    with pytest.raises(BobiStorageError, match="archive_storage_digest_mismatch"):
        await adapter.upload(
            owner_key="u1",
            content=content,
            filename="a.pdf",
            mime_type="application/pdf",
            sha256=hashlib.sha256(content).hexdigest(),
            idempotency_key="idem",
        )


@pytest.mark.asyncio
async def test_cloud_archive_read_uses_only_same_origin_signed_url() -> None:
    storage = FakeStorage()
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"document", headers={"content-length": "8"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = BobiCloudArchiveStorage(
            storage,
            installation_id="install-1",
            client=client,
        )
        subject = adapter._subject("u1")
        data = await adapter.read(
            f"bobi-storage://{subject}/media-123",
            max_bytes=100,
        )

    assert data == b"document"
    assert len(seen) == 1
    assert seen[0].url.host == "project.supabase.co"
    assert storage.signed[0]["media_id"] == "media-123"


@pytest.mark.asyncio
async def test_cloud_archive_read_rejects_foreign_signed_url_before_fetch() -> None:
    storage = FakeStorage()
    storage.signed_url = "https://attacker.example/storage/v1/object/sign/x?token=abc"
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"bad")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = BobiCloudArchiveStorage(
            storage,
            installation_id="install-1",
            client=client,
        )
        subject = adapter._subject("u1")
        with pytest.raises(BobiStorageError, match="archive_signed_url_origin_invalid"):
            await adapter.read(f"bobi-storage://{subject}/media-123", max_bytes=100)

    assert calls == 0


@pytest.mark.asyncio
async def test_cloud_archive_read_enforces_stream_byte_limit() -> None:
    storage = FakeStorage()

    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, content=b"0123456789", headers={"content-length": "10"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = BobiCloudArchiveStorage(
            storage,
            installation_id="install-1",
            client=client,
        )
        subject = adapter._subject("u1")
        with pytest.raises(ValueError, match="archive_blob_too_large"):
            await adapter.read(f"bobi-storage://{subject}/media-123", max_bytes=5)


@pytest.mark.asyncio
async def test_storage_client_emits_narrow_archive_operation() -> None:
    seen: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content.decode()))
        return httpx.Response(
            200,
            json={
                "ok": True,
                "media": {"id": "media-1", "sha256": "a" * 64, "size_bytes": 1},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        storage = BobiStorageClient(
            "https://project.supabase.co/functions/v1/bobi-storage",
            "x" * 40,
            client=client,
        )
        await storage.archive_upload(
            external_id="bobi2_" + "a" * 48,
            media_base64="YQ==",
            filename="a.pdf",
            mime_type="application/pdf",
            sha256="a" * 64,
            idempotency_key="idem",
        )

    assert seen[0]["op"] == "archive.media.upload"
    assert seen[0]["payload"]["idempotency_key"] == "idem"
