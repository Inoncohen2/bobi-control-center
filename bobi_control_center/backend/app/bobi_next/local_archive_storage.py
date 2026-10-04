"""Private local blob storage for Bobi Next archives.

This is the zero-configuration archive provider for self-hosted installs. Files
live under Bobi's private data directory, keyed by owner fingerprint + SHA-256,
and are written atomically. The URI contains no original filename or user text.
"""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from .archive_capture import StoredArchiveBlob

_SCHEME = "local-archive"
_OWNER_RE = re.compile(r"^[0-9a-f]{32}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _owner_fingerprint(owner_key: str) -> str:
    owner = owner_key.strip()
    if not owner:
        raise ValueError("archive_owner_required")
    return hashlib.sha256(owner.encode()).hexdigest()[:32]


class LocalArchiveStorage:
    """Implements both ArchiveBlobStorage.upload and ArchiveBlobReader.read."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            self.root.chmod(0o700)
        except OSError:
            pass
        self._root = self.root.resolve()

    def _owner_dir(self, owner_key: str) -> tuple[str, Path]:
        owner_hash = _owner_fingerprint(owner_key)
        directory = self._root / owner_hash
        directory.mkdir(parents=True, exist_ok=True)
        resolved = directory.resolve()
        if resolved.parent != self._root:
            raise ValueError("archive_local_path_invalid")
        try:
            resolved.chmod(0o700)
        except OSError:
            pass
        return owner_hash, resolved

    @staticmethod
    def _validate_digest(digest: str) -> str:
        normalized = digest.strip().lower()
        if _SHA_RE.fullmatch(normalized) is None:
            raise ValueError("archive_sha256_invalid")
        return normalized

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
        del filename, mime_type, idempotency_key
        if not isinstance(content, bytes) or not content:
            raise ValueError("archive_bytes_required")
        digest = self._validate_digest(sha256)
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("archive_media_digest_mismatch")
        owner_hash, directory = self._owner_dir(owner_key)
        target = directory / f"{digest}.blob"

        if target.exists():
            if target.is_symlink() or not target.is_file():
                raise ValueError("archive_local_path_invalid")
            existing = target.read_bytes()
            if len(existing) != len(content) or hashlib.sha256(existing).hexdigest() != digest:
                raise ValueError("archive_local_existing_corrupt")
        else:
            temp = directory / f".{digest}.{uuid.uuid4().hex}.tmp"
            try:
                with temp.open("xb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                try:
                    temp.chmod(0o600)
                except OSError:
                    pass
                os.replace(temp, target)
                try:
                    target.chmod(0o600)
                except OSError:
                    pass
            finally:
                if temp.exists():
                    temp.unlink(missing_ok=True)

        return StoredArchiveBlob(
            storage_uri=f"{_SCHEME}://{owner_hash}/{digest}",
            size_bytes=len(content),
            sha256=digest,
        )

    def _path_from_uri(self, storage_uri: str) -> tuple[Path, str]:
        parsed = urlsplit(storage_uri)
        owner_hash = parsed.netloc.strip().lower()
        digest = parsed.path.lstrip("/").strip().lower()
        if parsed.scheme != _SCHEME or parsed.query or parsed.fragment:
            raise ValueError("archive_local_uri_invalid")
        if _OWNER_RE.fullmatch(owner_hash) is None or _SHA_RE.fullmatch(digest) is None:
            raise ValueError("archive_local_uri_invalid")
        if "/" in digest or "\\" in digest:
            raise ValueError("archive_local_uri_invalid")
        owner_dir = self._root / owner_hash
        resolved_owner = owner_dir.resolve()
        if resolved_owner.parent != self._root:
            raise ValueError("archive_local_path_invalid")
        path = resolved_owner / f"{digest}.blob"
        return path, digest

    async def read(self, storage_uri: str, *, max_bytes: int) -> bytes:
        limit = max(1, int(max_bytes))
        path, digest = self._path_from_uri(storage_uri)
        if not path.exists() or path.is_symlink() or not path.is_file():
            raise FileNotFoundError("archive_blob_not_found")
        size = path.stat().st_size
        if size <= 0:
            raise ValueError("archive_blob_empty")
        if size > limit:
            raise ValueError("archive_blob_too_large")
        content = path.read_bytes()
        if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("archive_blob_corrupt")
        return content
