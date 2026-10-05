"""Typed client for Bobi's narrow Supabase Edge storage boundaries.

Bobi Next never receives a generic Supabase client or service-role key. It talks
only to its configured voucher or archive Edge Function using the installation
token resolved from Bobi's encrypted local secret vault.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx


class BobiStorageError(RuntimeError):
    pass


def _validated_endpoint(value: str) -> str:
    endpoint = str(value or "").strip().rstrip("/")
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ValueError("storage_endpoint_invalid")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("storage_endpoint_invalid")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("storage_endpoint_https_required")
    return endpoint


class BobiStorageClient:
    """Minimal authenticated client for the typed Bobi storage operations."""

    def __init__(
        self,
        endpoint: str,
        token: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.endpoint = _validated_endpoint(endpoint)
        self.token = str(token or "")
        if len(self.token) < 32:
            raise ValueError("storage_token_invalid")
        self.timeout_seconds = max(1.0, min(float(timeout_seconds), 60.0))
        self._injected_client = client

    async def _call(
        self,
        op: str,
        *,
        external_id: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        operation = str(op or "").strip()
        if not operation or len(operation) > 128:
            raise ValueError("storage_operation_invalid")
        if payload is not None and not isinstance(payload, dict):
            raise TypeError("storage_payload_must_be_object")

        body = {
            "op": operation,
            "external_id": str(external_id or ""),
            "payload": payload or {},
        }
        headers = {
            "x-bobi-token": self.token,
            "content-type": "application/json",
            "accept": "application/json",
        }

        async def request(client: httpx.AsyncClient) -> httpx.Response:
            return await client.post(self.endpoint, json=body, headers=headers)

        try:
            if self._injected_client is not None:
                response = await request(self._injected_client)
            else:
                async with httpx.AsyncClient(
                    timeout=self.timeout_seconds,
                    follow_redirects=False,
                ) as client:
                    response = await request(client)
        except httpx.TimeoutException as exc:
            raise BobiStorageError("storage_timeout") from exc
        except httpx.HTTPError as exc:
            raise BobiStorageError("storage_transport_error") from exc

        if response.is_redirect:
            raise BobiStorageError("storage_redirect_rejected")
        if response.status_code == 401:
            raise BobiStorageError("storage_unauthorized")
        if response.status_code == 413:
            raise BobiStorageError("storage_request_too_large")
        if response.status_code == 415:
            raise BobiStorageError("storage_unsupported_media")
        if response.status_code >= 500:
            raise BobiStorageError("storage_unavailable")

        try:
            value = response.json()
        except ValueError as exc:
            raise BobiStorageError("storage_invalid_json") from exc
        if not isinstance(value, dict):
            raise BobiStorageError("storage_invalid_response")
        if not response.is_success or value.get("ok") is not True:
            error = str(value.get("error") or "storage_operation_failed")
            safe_error = error if error.replace("_", "").isalnum() else "storage_operation_failed"
            raise BobiStorageError(safe_error[:128])
        return value

    async def ping(self) -> dict[str, Any]:
        return await self._call("ping")

    async def archive_upload(
        self,
        *,
        external_id: str,
        media_base64: str,
        filename: str,
        mime_type: str,
        sha256: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Upload one archive blob through the narrow archive operation."""

        return await self._call(
            "archive.media.upload",
            external_id=external_id,
            payload={
                "media_base64": media_base64,
                "filename": filename,
                "mime_type": mime_type,
                "sha256": sha256,
                "idempotency_key": idempotency_key,
            },
        )

    async def archive_signed_url(
        self,
        *,
        external_id: str,
        media_id: str,
        expires_in: int = 120,
    ) -> dict[str, Any]:
        """Request a short-lived read URL for one archive object."""

        return await self._call(
            "archive.media.signed_url",
            external_id=external_id,
            payload={
                "media_id": str(media_id or ""),
                "expires_in": max(30, min(int(expires_in), 900)),
            },
        )
