"""WAHA provider adapter for the Bobi Next messaging boundary.

The adapter deliberately contains no brain, Home Assistant or authorization
logic. It normalizes WAHA webhooks, implements the provider-neutral transport,
and exposes a bounded media loader that only reads WAHA's own /api/files path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import unquote, urlsplit, urlunsplit

import httpx

from .media_pipeline import MediaDescriptor, MediaPipelineError
from .messaging import InboundMessage, MessageTransport

_WA_DIRECT_SUFFIX = "@" + "c.us"
_WA_INTERNAL_SUFFIX = "@" + "s.whatsapp.net"
_MAX_POLL_OPTIONS = 32
_MAX_POLL_OPTION_TEXT = 256
_MAX_POLL_QUESTION = 1000


class WahaWebhookError(ValueError):
    pass


@dataclass(slots=True, frozen=True)
class WahaInbound:
    session: str
    message_id: str
    chat_id: str
    sender_id: str
    text: str
    kind: str
    timestamp: int
    has_media: bool = False
    media_url: str = ""
    media_mimetype: str = ""
    media_filename: str = ""


class AsyncHttpClient(Protocol):
    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response: ...


def _normalize_chat_id(value: Any) -> str:
    chat_id = str(value or "").strip()
    if chat_id.endswith(_WA_INTERNAL_SUFFIX):
        return f"{chat_id.removesuffix(_WA_INTERNAL_SUFFIX)}{_WA_DIRECT_SUFFIX}"
    return chat_id


def parse_waha_webhook(event: dict[str, Any]) -> WahaInbound | None:
    """Normalize one incoming WAHA `message` event.

    Outgoing/self events and non-message events are intentionally ignored so a
    Bobi reply can never re-enter the inbox as a new user command.
    """

    if str(event.get("event", "")) != "message":
        return None
    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise WahaWebhookError("invalid_payload")
    if bool(payload.get("fromMe")):
        return None

    message_id = str(payload.get("id") or "").strip()
    chat_id = _normalize_chat_id(payload.get("from") or payload.get("chatId"))
    participant = _normalize_chat_id(payload.get("participant"))
    sender_id = participant or chat_id
    if not message_id or not chat_id or not sender_id:
        raise WahaWebhookError("missing_message_identity")
    if chat_id == "status@broadcast" or chat_id.endswith("@newsletter"):
        return None

    text = str(payload.get("body") or "")
    has_media = bool(payload.get("hasMedia"))
    media = payload.get("media")
    media_data = media if isinstance(media, dict) else {}
    mimetype = str(media_data.get("mimetype") or "")
    if has_media:
        if mimetype.startswith("audio/"):
            kind = "voice"
        elif mimetype.startswith("image/"):
            kind = "image"
        elif mimetype.startswith("video/"):
            kind = "video"
        else:
            kind = "document"
    else:
        kind = "text"

    try:
        timestamp = int(float(payload.get("timestamp") or 0))
    except (TypeError, ValueError):
        timestamp = 0

    return WahaInbound(
        session=str(event.get("session") or "default"),
        message_id=message_id,
        chat_id=chat_id,
        sender_id=sender_id,
        text=text,
        kind=kind,
        timestamp=timestamp,
        has_media=has_media,
        media_url=str(media_data.get("url") or ""),
        media_mimetype=mimetype,
        media_filename=str(media_data.get("filename") or ""),
    )


def deterministic_waha_message_id(idempotency_key: str) -> str:
    """Build a stable WAHA-safe message id for engines that accept custom ids."""

    compact = "".join(ch for ch in idempotency_key.upper() if ch.isalnum())
    if len(compact) < 16:
        raise ValueError("idempotency_key_too_short")
    return compact[:22]


def _extract_provider_message_id(data: Any, fallback: str) -> str:
    if not isinstance(data, dict):
        return fallback
    raw_id = data.get("id")
    if isinstance(raw_id, str) and raw_id:
        return raw_id
    if isinstance(raw_id, dict):
        for key in ("_serialized", "$1", "id"):
            value = raw_id.get(key)
            if isinstance(value, str) and value:
                return value
    key_data = data.get("key")
    if isinstance(key_data, dict):
        for key in ("_serialized", "id"):
            value = key_data.get(key)
            if isinstance(value, str) and value:
                return value
    return fallback


def _normalize_poll_options(options: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    normalized = tuple(str(option).strip() for option in options)
    if not 1 <= len(normalized) <= _MAX_POLL_OPTIONS:
        raise ValueError("waha_poll_options_invalid")
    if any(not option or len(option) > _MAX_POLL_OPTION_TEXT for option in normalized):
        raise ValueError("waha_poll_options_invalid")
    if len(set(normalized)) != len(normalized):
        raise ValueError("waha_poll_options_not_unique")
    return normalized


class WahaTransport(MessageTransport):
    """HTTP implementation of the Bobi Next MessageTransport contract."""

    def __init__(
        self,
        *,
        base_url: str,
        session: str,
        api_key: str = "",
        engine: str = "GOWS",
        client: AsyncHttpClient | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = session or "default"
        self.api_key = api_key
        self.engine = engine.upper()
        self._client = client
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        return headers

    async def _request(self, method: str, path: str, body: dict[str, Any]) -> Any:
        url = f"{self.base_url}{path}"
        kwargs = {"json": body, "headers": self._headers(), "timeout": self.timeout}
        if self._client is not None:
            response = await self._client.request(method, url, **kwargs)
        else:
            async with httpx.AsyncClient() as client:
                response = await client.request(method, url, **kwargs)
        response.raise_for_status()
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return {}

    async def react(self, message: InboundMessage, emoji: str) -> None:
        await self._request(
            "PUT",
            "/api/reaction",
            {
                "session": self.session,
                "messageId": message.message_id,
                "reaction": emoji,
            },
        )

    async def set_typing(self, chat_id: str, enabled: bool) -> None:
        await self._request(
            "POST",
            f"/api/{self.session}/presence",
            {
                "chatId": chat_id,
                "presence": "typing" if enabled else "paused",
            },
        )

    async def send_text(
        self,
        chat_id: str,
        text: str,
        *,
        reply_to: str,
        idempotency_key: str,
    ) -> str:
        custom_id = deterministic_waha_message_id(idempotency_key)
        body: dict[str, Any] = {
            "session": self.session,
            "chatId": chat_id,
            "text": text,
            "reply_to": reply_to,
        }
        # WAHA >= 2026.4.3 accepts caller-provided message IDs for NOWEB/GOWS.
        # Reusing the same deterministic ID narrows the crash-window in which
        # Bobi could otherwise repeat an already accepted outbound message.
        if self.engine in {"GOWS", "NOWEB"}:
            body["id"] = custom_id
        data = await self._request("POST", "/api/sendText", body)
        return _extract_provider_message_id(data, custom_id)

    async def send_poll(
        self,
        chat_id: str,
        question: str,
        options: tuple[str, ...] | list[str],
        *,
        multiple_answers: bool = False,
    ) -> str:
        """Send a poll and return WAHA's real provider message id.

        Unlike ``send_text``, the documented WAHA poll API does not expose a
        caller-defined message id. Bobi therefore never invents one: a missing
        provider id is a hard failure and no interaction may be registered.
        """

        normalized_chat = chat_id.strip()
        normalized_question = question.strip()
        normalized_options = _normalize_poll_options(options)
        if not normalized_chat:
            raise ValueError("waha_poll_chat_required")
        if not normalized_question or len(normalized_question) > _MAX_POLL_QUESTION:
            raise ValueError("waha_poll_question_invalid")

        data = await self._request(
            "POST",
            "/api/sendPoll",
            {
                "session": self.session,
                "chatId": normalized_chat,
                "poll": {
                    "name": normalized_question,
                    "options": list(normalized_options),
                    "multipleAnswers": bool(multiple_answers),
                },
            },
        )
        provider_id = _extract_provider_message_id(data, "").strip()
        if not provider_id:
            raise RuntimeError("waha_poll_message_id_missing")
        return provider_id


class WahaMediaLoader:
    """Download only WAHA-owned /api/files objects with a hard byte ceiling."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("invalid_waha_base_url")
        self._scheme = parsed.scheme
        self._netloc = parsed.netloc
        self.api_key = api_key
        self._client = client
        self.timeout = timeout

    def _trusted_url(self, provider_ref: str) -> str:
        parsed = urlsplit(provider_ref)
        decoded_path = unquote(parsed.path)
        parts = [part for part in decoded_path.split("/") if part]
        if len(parts) < 3 or parts[:2] != ["api", "files"]:
            raise MediaPipelineError("waha_media_path_not_allowed")
        if any(part in {".", ".."} for part in parts):
            raise MediaPipelineError("waha_media_path_not_allowed")
        return urlunsplit((self._scheme, self._netloc, parsed.path, parsed.query, ""))

    async def load(self, descriptor: MediaDescriptor, *, max_bytes: int) -> bytes:
        if not descriptor.provider_ref:
            raise MediaPipelineError("waha_media_not_downloaded")
        url = self._trusted_url(descriptor.provider_ref)
        headers = {"Accept": "*/*"}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.timeout)
        content = bytearray()
        try:
            async with client.stream("GET", url, headers=headers) as response:
                response.raise_for_status()
                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        if int(content_length) > max_bytes:
                            raise MediaPipelineError("media_too_large")
                    except ValueError:
                        pass
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > max_bytes:
                        raise MediaPipelineError("media_too_large")
        except MediaPipelineError:
            raise
        except httpx.TimeoutException as exc:
            raise MediaPipelineError("waha_media_timeout") from exc
        except httpx.HTTPError as exc:
            raise MediaPipelineError("waha_media_download_failed") from exc
        finally:
            if owns_client:
                await client.aclose()
        return bytes(content)
