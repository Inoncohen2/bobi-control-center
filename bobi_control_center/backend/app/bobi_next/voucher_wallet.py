"""Voucher wallet adapter for Bobi Next.

The legacy cloud boundary currently models voucher media explicitly.  This module
keeps that compatibility behind typed methods so the engine is not coupled to
Edge Function operation strings or raw response shapes.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from .supabase_storage import BobiStorageClient, BobiStorageError

_MAX_MEDIA_BYTES = 10 * 1024 * 1024
_ALLOWED_MIME = frozenset({"image/jpeg", "image/png", "image/webp", "application/pdf"})


@dataclass(slots=True, frozen=True)
class VoucherRecord:
    voucher_id: str
    local_id: str = ""
    name: str = ""
    merchant: str = ""
    code: str = ""
    amount: Decimal | None = None
    remaining_amount: Decimal | None = None
    currency: str = "ILS"
    expires_at: str = ""
    status: str = "active"
    notes: str = ""
    source_message_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class VoucherMedia:
    media_id: str
    voucher_id: str
    filename: str = ""
    content_type: str = ""
    size_bytes: int = 0
    sha256: str = ""
    status: str = "active"
    storage_uri: str = ""


def _decimal(value: Any) -> Decimal | None:
    if value in {None, ""}:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise BobiStorageError("voucher_invalid_amount") from exc


def _object(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _voucher(value: Any) -> VoucherRecord:
    row = _object(value)
    identifier = str(row.get("id") or "").strip()
    if not identifier:
        raise BobiStorageError("voucher_invalid_response")
    metadata = row.get("metadata")
    return VoucherRecord(
        voucher_id=identifier,
        local_id=str(row.get("local_id") or ""),
        name=str(row.get("name") or ""),
        merchant=str(row.get("merchant") or ""),
        code=str(row.get("code") or ""),
        amount=_decimal(row.get("amount")),
        remaining_amount=_decimal(row.get("remaining_amount")),
        currency=str(row.get("currency") or "ILS"),
        expires_at=str(row.get("expires_at") or ""),
        status=str(row.get("status") or "active"),
        notes=str(row.get("notes") or ""),
        source_message_id=str(row.get("source_message_id") or ""),
        metadata=dict(metadata) if isinstance(metadata, dict) else {},
    )


def _media(value: Any) -> VoucherMedia:
    row = _object(value)
    identifier = str(row.get("id") or "").strip()
    voucher_id = str(row.get("voucher_id") or "").strip()
    if not identifier or not voucher_id:
        raise BobiStorageError("voucher_media_invalid_response")
    return VoucherMedia(
        media_id=identifier,
        voucher_id=voucher_id,
        filename=str(row.get("original_filename") or ""),
        content_type=str(row.get("content_type") or ""),
        size_bytes=max(0, int(row.get("size_bytes") or 0)),
        sha256=str(row.get("sha256") or ""),
        status=str(row.get("status") or "active"),
        storage_uri=str(row.get("storage_uri") or ""),
    )


def _detected_mime(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    return ""


class VoucherWallet:
    def __init__(self, storage: BobiStorageClient, *, profile_external_id: str) -> None:
        self.storage = storage
        self.profile_external_id = str(profile_external_id or "").strip()
        if not self.profile_external_id:
            raise ValueError("voucher_profile_external_id_required")

    async def list(self, *, status: str = "active", limit: int = 50) -> tuple[VoucherRecord, ...]:
        result = await self.storage._call(
            "voucher.list",
            external_id=self.profile_external_id,
            payload={"status": status, "limit": max(1, min(int(limit), 200))},
        )
        items = result.get("items")
        if not isinstance(items, list):
            raise BobiStorageError("voucher_list_invalid_response")
        return tuple(_voucher(item) for item in items)

    async def get(self, voucher_id: str, *, include_code: bool = False) -> VoucherRecord:
        result = await self.storage._call(
            "voucher.get",
            external_id=self.profile_external_id,
            payload={"voucher_id": voucher_id, "include_code": bool(include_code)},
        )
        return _voucher(result.get("item"))

    async def upsert(self, payload: dict[str, Any]) -> VoucherRecord:
        result = await self.storage._call(
            "voucher.upsert",
            external_id=self.profile_external_id,
            payload=dict(payload),
        )
        return _voucher(result.get("item"))

    async def update(self, payload: dict[str, Any]) -> VoucherRecord:
        result = await self.storage._call(
            "voucher.update",
            external_id=self.profile_external_id,
            payload=dict(payload),
        )
        return _voucher(result.get("item"))

    async def upload_media(
        self,
        voucher_id: str,
        data: bytes,
        *,
        filename: str,
        content_type: str,
    ) -> VoucherMedia:
        if not isinstance(data, bytes) or not data:
            raise ValueError("voucher_media_bytes_required")
        if len(data) > _MAX_MEDIA_BYTES:
            raise ValueError("voucher_media_too_large")
        declared = str(content_type or "").lower().split(";", 1)[0].strip()
        if declared not in _ALLOWED_MIME:
            raise ValueError("voucher_media_type_unsupported")
        if _detected_mime(data) != declared:
            raise ValueError("voucher_media_signature_mismatch")
        result = await self.storage._call(
            "voucher.media.upload",
            external_id=self.profile_external_id,
            payload={
                "voucher_id": voucher_id,
                "filename": str(filename or "voucher")[:255],
                "mime_type": declared,
                "media_base64": base64.b64encode(data).decode("ascii"),
            },
        )
        return _media(result.get("media"))

    async def list_media(
        self,
        voucher_id: str,
        *,
        status: str = "all",
        limit: int = 20,
    ) -> tuple[VoucherMedia, ...]:
        result = await self.storage._call(
            "voucher.media.list",
            external_id=self.profile_external_id,
            payload={
                "voucher_id": voucher_id,
                "status": status,
                "limit": max(1, min(int(limit), 100)),
            },
        )
        items = result.get("items")
        if not isinstance(items, list):
            raise BobiStorageError("voucher_media_list_invalid_response")
        return tuple(_media(item) for item in items)

    async def signed_url(self, *, media_id: str, expires_in: int = 120) -> str:
        result = await self.storage._call(
            "voucher.media.signed_url",
            external_id=self.profile_external_id,
            payload={
                "media_id": media_id,
                "expires_in": max(30, min(int(expires_in), 900)),
            },
        )
        signed_url = str(result.get("signed_url") or "").strip()
        if not signed_url.startswith("https://"):
            raise BobiStorageError("voucher_signed_url_invalid")
        return signed_url

    async def delete_media(self, *, media_id: str) -> VoucherMedia:
        result = await self.storage._call(
            "voucher.media.delete",
            external_id=self.profile_external_id,
            payload={"media_id": media_id},
        )
        return _media(result.get("media"))

    async def restore_media(self, *, media_id: str) -> VoucherMedia:
        result = await self.storage._call(
            "voucher.media.restore",
            external_id=self.profile_external_id,
            payload={"media_id": media_id},
        )
        return _media(result.get("media"))
