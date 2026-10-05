"""Private cloud blob adapter for Bobi Next archives.

The adapter talks only to Bobi's narrow storage boundary and never exposes a
Supabase service-role key to the brain. Raw user identifiers are converted to a
stable privacy-preserving cloud subject before leaving the installation.
"""

from __future__ import annotations

import base64
import hashlib
import re
from urllib.parse import urlsplit

import httpx

from .archive_capture import StoredArchiveBlob
from .cloud_identity import cloud_subject
from .supabase_storage import BobiStorageClient, BobiStorageError

_SCHEME = "bobi-storage"
_SUBJECT_RE = re.compile(r"^bobi2_[0-9a-f]{48}$")
_MEDIA_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,200}$")


class BobiCloudArchiveStorage:
    """ArchiveBlobStorage + ArchiveBlobReader backed by ``bobi-storage``."""

    def __init__(
        self,
        storage: BobiStorageClient,
        *,
        installation_id: str,
        client: httpx.AsyncClient | None = None,
        max_upload_bytes: int = 10 * 1024 * 1024,
    ) -> None:
        installation = str(installation_id or "").strip()
        if not installation:
            raise ValueError("archive_installation_id_required")
        self.storage = storage
        self.installation_id = installation
        self._client = client
        self.max_upload_bytes = max(1, int(max_upload_bytes))
        endpoint = urlsplit(storage.endpoint)
        self._storage_scheme = endpoint.scheme
        self._storage_host = endpoint.hostname or ""
        self._storage_port = endpoint.port

    def _subject(self, owner_key: str) -> str:
        return cloud_subject(self.installation_id, owner_key)

    @staticmethod
    def _uri(external_id: str, media_id: str) -> str:
        if _SUBJECT_RE.fullmatch(external_id) is None:
            raise ValueError("archive_cloud_subject_invalid")
        if _MEDIA_ID_RE.fullmatch(media_id) is None:
            raise ValueError("archive_cloud_media_id_invalid")
        return f"{_SCHEME}://{external_id}/{media_id}"

    @staticmethod
    def _parse_uri(storage_uri: str) -> tuple[str, str]:
        parsed = urlsplit(str(storage_uri or ""))
        external_id = parsed.netloc.strip()
        media_id = parsed.path.lstrip("/").strip()
        if parsed.scheme != _SCHEME or parsed.query or parsed.fragment:
            raise ValueError("archive_cloud_uri_invalid")
        if "/" in media_id or "\\" in media_id:
            raise ValueError("archive_cloud_uri_invalid")
        if _SUBJECT_RE.fullmatch(external_id) is None:
            raise ValueError("archive_cloud_uri_invalid")
        if _MEDIA_ID_RE.fullmatch(media_id) is None:
            raise ValueError("archive_cloud_uri_invalid")
        return external_id, media_id

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
        if not isinstance(content, bytes) or not content:
            raise ValueError("archive_bytes_required")
        if len(content) > self.max_upload_bytes:
            raise ValueError("archive_blob_too_large")
        digest = str(sha256 or "").strip().lower()
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("archive_media_digest_mismatch")

        external_id = self._subject(owner_key)
        result = await self.storage.archive_upload(
            external_id=external_id,
            media_base64=base64.b64encode(content).decode("ascii"),
            filename=str(filename or "")[:255],
            mime_type=str(mime_type or "").lower().split(";", 1)[0].strip(),
            sha256=digest,
            idempotency_key=str(idempotency_key or "")[:128],
        )
        media = result.get("media")
        if not isinstance(media, dict):
            raise BobiStorageError("archive_storage_invalid_response")
        media_id = str(media.get("id") or "").strip()
        server_sha = str(media.get("sha256") or "").strip().lower()
        size = int(media.get("size_bytes") or 0)
        if server_sha != digest:
            raise BobiStorageError("archive_storage_digest_mismatch")
        if size != len(content):
            raise BobiStorageError("archive_storage_size_mismatch")
        return StoredArchiveBlob(
            storage_uri=self._uri(external_id, media_id),
            size_bytes=size,
            sha256=digest,
        )

    def _validate_signed_url(self, value: str) -> str:
        raw = str(value or "").strip()
        parsed = urlsplit(raw)
        if parsed.scheme != self._storage_scheme or parsed.hostname != self._storage_host:
            raise BobiStorageError("archive_signed_url_origin_invalid")
        if parsed.port != self._storage_port:
            raise BobiStorageError("archive_signed_url_origin_invalid")
        if not parsed.path.startswith("/storage/v1/object/sign/"):
            raise BobiStorageError("archive_signed_url_path_invalid")
        if parsed.fragment:
            raise BobiStorageError("archive_signed_url_invalid")
        return raw

    async def read(self, storage_uri: str, *, max_bytes: int) -> bytes:
        external_id, media_id = self._parse_uri(storage_uri)
        signed = await self.storage.archive_signed_url(
            external_id=external_id,
            media_id=media_id,
            expires_in=120,
        )
        url = self._validate_signed_url(str(signed.get("signed_url") or ""))
        limit = max(1, int(max_bytes))

        async def fetch(client: httpx.AsyncClient) -> bytes:
            try:
                async with client.stream("GET", url) as response:
                    if response.is_redirect:
                        raise BobiStorageError("archive_blob_redirect_rejected")
                    if response.status_code == 404:
                        raise FileNotFoundError("archive_blob_not_found")
                    if not response.is_success:
                        raise BobiStorageError("archive_blob_download_failed")
                    length = int(response.headers.get("content-length") or 0)
                    if length > limit:
                        raise ValueError("archive_blob_too_large")
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > limit:
                            raise ValueError("archive_blob_too_large")
                        chunks.append(chunk)
            except httpx.TimeoutException as exc:
                raise BobiStorageError("archive_blob_timeout") from exc
            except httpx.HTTPError as exc:
                raise BobiStorageError("archive_blob_transport_error") from exc
            content = b"".join(chunks)
            if not content:
                raise ValueError("archive_blob_empty")
            return content

        if self._client is not None:
            return await fetch(self._client)
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
            return await fetch(client)
