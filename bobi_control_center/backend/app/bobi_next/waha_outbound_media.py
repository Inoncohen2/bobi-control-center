"""WAHA outbound-file adapter for Bobi Next.

WAHA 2026.8 exposes /api/sendFile with RemoteFile or BinaryFile payloads. Bobi
uses BinaryFile here so a private archive never needs a public URL. The current
schema has no caller-defined message id, so exactly-once crash handling remains
owned by OutboundMediaStore rather than pretending the provider can dedupe it.
"""

from __future__ import annotations

import base64
from typing import Any, Protocol

import httpx

from .outbound_media import OutboundMediaPayload, OutboundMediaTransport


class AsyncHttpClient(Protocol):
    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response: ...


def _provider_message_id(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    raw_id = data.get("id")
    if isinstance(raw_id, str) and raw_id.strip():
        return raw_id.strip()
    if isinstance(raw_id, dict):
        for key in ("_serialized", "$1", "id"):
            value = raw_id.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    key_data = data.get("key")
    if isinstance(key_data, dict):
        for key in ("_serialized", "id"):
            value = key_data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


class WahaOutboundMediaTransport(OutboundMediaTransport):
    def __init__(
        self,
        *,
        base_url: str,
        session: str,
        api_key: str = "",
        client: AsyncHttpClient | None = None,
        timeout: float = 45.0,
    ) -> None:
        normalized = base_url.strip().rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("invalid_waha_base_url")
        self.base_url = normalized
        self.session = session.strip() or "default"
        self.api_key = api_key
        self.client = client
        self.timeout = max(1.0, float(timeout))

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        return headers

    async def send_file(
        self,
        chat_id: str,
        payload: OutboundMediaPayload,
        *,
        caption: str,
        reply_to: str,
    ) -> str:
        chat = chat_id.strip()
        mime = payload.mime_type.strip().lower().split(";", 1)[0]
        if not chat:
            raise ValueError("waha_file_chat_required")
        if not isinstance(payload.content, bytes) or not payload.content:
            raise ValueError("waha_file_content_required")
        if not mime:
            raise ValueError("waha_file_mimetype_required")

        body: dict[str, Any] = {
            "session": self.session,
            "chatId": chat,
            "file": {
                "mimetype": mime,
                "filename": payload.filename.strip()[:255] or None,
                "data": base64.b64encode(payload.content).decode("ascii"),
            },
            "caption": caption.strip()[:4000],
            "reply_to": reply_to.strip()[:512] or None,
        }
        url = f"{self.base_url}/api/sendFile"
        kwargs = {
            "json": body,
            "headers": self._headers(),
            "timeout": self.timeout,
        }
        if self.client is not None:
            response = await self.client.request("POST", url, **kwargs)
        else:
            async with httpx.AsyncClient() as client:
                response = await client.request("POST", url, **kwargs)
        response.raise_for_status()
        try:
            data = response.json() if response.content else {}
        except ValueError:
            data = {}
        provider_id = _provider_message_id(data)
        if not provider_id:
            raise RuntimeError("waha_file_message_id_missing")
        return provider_id
