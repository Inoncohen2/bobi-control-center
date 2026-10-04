"""Quoted-message context support for Bobi Next.

A WhatsApp reply is context, not a second user command. This module keeps the
quoted payload separate from ``EngineRequest.text`` and exposes it to language
understanding as a bounded synthetic context turn. Raw provider identifiers and
media URLs are never sent to the AI boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .intent import SemanticIntent

_MAX_QUOTED_TEXT = 4000


class UnderstandingLike(Protocol):
    async def understand(self, text: str, *, context: Any) -> SemanticIntent: ...


@dataclass(slots=True, frozen=True)
class QuotedContext:
    text: str = ""
    message_id: str = ""
    has_media: bool = False
    mimetype: str = ""
    filename: str = ""

    def as_turn(self) -> dict[str, str]:
        detail = self.text.strip()
        if not detail and self.has_media:
            media_type = self.mimetype or "media"
            name = f" ({self.filename})" if self.filename else ""
            detail = f"[quoted {media_type}{name}]"
        return {
            "direction": "quoted_reference",
            "text": detail[:_MAX_QUOTED_TEXT],
        }


@dataclass(slots=True, frozen=True)
class _ContextProxy:
    user_key: str
    recent_turns: tuple[dict, ...]
    active_context: dict | None


def quote_from_metadata(metadata: dict[str, Any] | None) -> QuotedContext | None:
    if not isinstance(metadata, dict):
        return None
    raw = metadata.get("reply_to")
    if not isinstance(raw, dict):
        return None
    text = str(raw.get("body") or "").strip()[:_MAX_QUOTED_TEXT]
    message_id = str(raw.get("id") or "").strip()[:512]
    has_media = bool(raw.get("has_media", False))
    mimetype = str(raw.get("mimetype") or "").strip()[:256]
    filename = str(raw.get("filename") or "").strip()[:255]
    if not text and not message_id and not has_media:
        return None
    return QuotedContext(
        text=text,
        message_id=message_id,
        has_media=has_media,
        mimetype=mimetype,
        filename=filename,
    )


class QuotedContextUnderstanding:
    """Decorate understanding with one transient, context-only quoted turn."""

    def __init__(self, base: UnderstandingLike, quoted: QuotedContext) -> None:
        self.base = base
        self.quoted = quoted

    async def understand(self, text: str, *, context: Any) -> SemanticIntent:
        recent = tuple(getattr(context, "recent_turns", ()) or ())
        proxy = _ContextProxy(
            user_key=str(getattr(context, "user_key", "")),
            recent_turns=recent + (self.quoted.as_turn(),),
            active_context=getattr(context, "active_context", None),
        )
        intent = await self.base.understand(text, context=proxy)
        metadata = dict(intent.metadata)
        metadata["quoted_context_available"] = True
        intent.metadata = metadata
        return intent
