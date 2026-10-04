from __future__ import annotations

import hashlib

import pytest

from app.bobi_next.local_archive_storage import LocalArchiveStorage


@pytest.mark.asyncio
async def test_local_archive_round_trip_and_dedupe(tmp_path) -> None:
    storage = LocalArchiveStorage(tmp_path / "archive")
    content = b"private document bytes"
    digest = hashlib.sha256(content).hexdigest()

    first = await storage.upload(
        owner_key="u1",
        content=content,
        filename="insurance.pdf",
        mime_type="application/pdf",
        sha256=digest,
        idempotency_key="request-1",
    )
    second = await storage.upload(
        owner_key="u1",
        content=content,
        filename="renamed.pdf",
        mime_type="application/pdf",
        sha256=digest,
        idempotency_key="request-2",
    )

    assert first == second
    assert first.storage_uri.startswith("local-archive://")
    assert "insurance" not in first.storage_uri
    assert await storage.read(first.storage_uri, max_bytes=1024) == content


@pytest.mark.asyncio
async def test_same_bytes_for_different_owners_use_different_private_paths(tmp_path) -> None:
    storage = LocalArchiveStorage(tmp_path / "archive")
    content = b"same bytes"
    digest = hashlib.sha256(content).hexdigest()

    u1 = await storage.upload(
        owner_key="u1",
        content=content,
        filename="a.pdf",
        mime_type="application/pdf",
        sha256=digest,
        idempotency_key="1",
    )
    u2 = await storage.upload(
        owner_key="u2",
        content=content,
        filename="a.pdf",
        mime_type="application/pdf",
        sha256=digest,
        idempotency_key="2",
    )

    assert u1.storage_uri != u2.storage_uri
    assert await storage.read(u1.storage_uri, max_bytes=1024) == content
    assert await storage.read(u2.storage_uri, max_bytes=1024) == content


@pytest.mark.asyncio
async def test_local_archive_rejects_bad_digest_and_uri_traversal(tmp_path) -> None:
    storage = LocalArchiveStorage(tmp_path / "archive")

    with pytest.raises(ValueError, match="archive_media_digest_mismatch"):
        await storage.upload(
            owner_key="u1",
            content=b"content",
            filename="x.pdf",
            mime_type="application/pdf",
            sha256="0" * 64,
            idempotency_key="1",
        )

    invalid = (
        "local-archive://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/"
        "%2e%2e%2fbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    )
    with pytest.raises(ValueError, match="archive_local_uri_invalid"):
        await storage.read(invalid, max_bytes=1024)


@pytest.mark.asyncio
async def test_local_archive_detects_corruption(tmp_path) -> None:
    storage = LocalArchiveStorage(tmp_path / "archive")
    content = b"original"
    digest = hashlib.sha256(content).hexdigest()
    saved = await storage.upload(
        owner_key="u1",
        content=content,
        filename="x.pdf",
        mime_type="application/pdf",
        sha256=digest,
        idempotency_key="1",
    )

    path, _ = storage._path_from_uri(saved.storage_uri)
    path.write_bytes(b"tampered")

    with pytest.raises(ValueError, match="archive_blob_corrupt"):
        await storage.read(saved.storage_uri, max_bytes=1024)


@pytest.mark.asyncio
async def test_local_archive_enforces_read_limit(tmp_path) -> None:
    storage = LocalArchiveStorage(tmp_path / "archive")
    content = b"1234567890"
    digest = hashlib.sha256(content).hexdigest()
    saved = await storage.upload(
        owner_key="u1",
        content=content,
        filename="x.pdf",
        mime_type="application/pdf",
        sha256=digest,
        idempotency_key="1",
    )

    with pytest.raises(ValueError, match="archive_blob_too_large"):
        await storage.read(saved.storage_uri, max_bytes=5)
