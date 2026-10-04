"""Ingress bridge from WAHA webhooks into the Bobi Next durable inbox.

This boundary is intentionally fail-closed: only an enabled configured WAHA
provider/session and an enabled linked Bobi user may enqueue a command. Unknown
senders are not silently treated as guests and outgoing/status events are
ignored by the WAHA parser before they reach the inbox.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .messaging import MessageStore
from .setup_store import SetupStore
from .waha_adapter import WahaWebhookError, parse_waha_webhook

_MAX_QUOTED_BODY = 4000


@dataclass(slots=True, frozen=True)
class IngestResult:
    accepted: bool
    reason: str
    message_id: str = ""
    user_key: str = ""
    duplicate: bool = False


def reply_context_from_waha_event(event: dict[str, Any]) -> dict[str, Any] | None:
    """Extract WAHA ``payload.replyTo`` into bounded provider-neutral metadata.

    WAHA documents ``replyTo`` as the original message context for replies. We
    deliberately do not persist participant identifiers or arbitrary internal
    ``_data`` fields. Media URLs remain transport metadata only and never reach
    the language model directly.
    """

    payload = event.get("payload")
    if not isinstance(payload, dict):
        return None
    raw = payload.get("replyTo")
    if not isinstance(raw, dict):
        return None

    media_raw = raw.get("media")
    media = media_raw if isinstance(media_raw, dict) else {}
    body = str(raw.get("body") or "").strip()[:_MAX_QUOTED_BODY]
    message_id = str(raw.get("id") or "").strip()[:512]
    has_media = bool(raw.get("hasMedia", False))
    mimetype = str(media.get("mimetype") or "").strip()[:256]
    filename = str(media.get("filename") or "").strip()[:255]
    media_url = str(media.get("url") or "").strip()

    if not body and not message_id and not has_media:
        return None
    result: dict[str, Any] = {
        "id": message_id,
        "body": body,
        "has_media": has_media,
        "mimetype": mimetype,
        "filename": filename,
    }
    if has_media and media_url:
        result["provider_ref"] = media_url
    return result


def ingest_waha_event(
    event: dict[str, Any],
    *,
    provider_key: str,
    setup: SetupStore,
    messages: MessageStore,
    now_ts: int | None = None,
) -> IngestResult:
    provider = setup.get_provider(provider_key)
    if provider is None:
        return IngestResult(False, "provider_not_configured")
    if not provider.enabled:
        return IngestResult(False, "provider_disabled")
    if provider.provider_type != "waha":
        return IngestResult(False, "provider_type_mismatch")

    try:
        parsed = parse_waha_webhook(event)
    except WahaWebhookError as exc:
        return IngestResult(False, f"invalid_webhook:{exc}")
    if parsed is None:
        return IngestResult(False, "ignored_event")
    if provider.session and parsed.session != provider.session:
        return IngestResult(False, "session_mismatch", parsed.message_id)

    user = setup.resolve_user(provider_key, parsed.sender_id)
    if user is None:
        return IngestResult(False, "unknown_or_disabled_sender", parsed.message_id)

    received_ts = parsed.timestamp if parsed.timestamp > 0 else int(now_ts or time.time())
    metadata: dict[str, Any] = {
        "session": parsed.session,
        "sender_fingerprint_scope": provider_key,
    }
    if parsed.has_media:
        metadata["media"] = {
            "url": parsed.media_url,
            "mimetype": parsed.media_mimetype,
            "filename": parsed.media_filename,
        }
    reply_to = reply_context_from_waha_event(event)
    if reply_to is not None:
        metadata["reply_to"] = reply_to

    inserted = messages.enqueue(
        provider=provider_key,
        message_id=parsed.message_id,
        chat_id=parsed.chat_id,
        user_key=user.user_key,
        text=parsed.text,
        kind=parsed.kind,
        metadata=metadata,
        received_ts=received_ts,
    )
    if not inserted:
        return IngestResult(
            False,
            "duplicate_message",
            parsed.message_id,
            user.user_key,
            duplicate=True,
        )
    return IngestResult(True, "accepted", parsed.message_id, user.user_key)
