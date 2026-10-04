from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.bobi_next.engine import UnderstandingContext
from app.bobi_next.intent import SemanticIntent
from app.bobi_next.quoted_context import (
    QuotedContextUnderstanding,
    quote_from_metadata,
)
from app.bobi_next.waha_ingest import reply_context_from_waha_event


def test_waha_reply_context_is_bounded_and_drops_participant_identity() -> None:
    reply = reply_context_from_waha_event(
        {
            "payload": {
                "replyTo": {
                    "id": "false_chat_ABC",
                    "participant": "972500000000@c.us",
                    "body": "x" * 5000,
                    "hasMedia": True,
                    "media": {
                        "url": "http://waha:3000/api/files/original.jpg",
                        "mimetype": "image/jpeg",
                        "filename": "original.jpg",
                    },
                    "_data": {"internal": "must-not-leak"},
                }
            }
        }
    )

    assert reply is not None
    assert reply["id"] == "false_chat_ABC"
    assert len(reply["body"]) == 4000
    assert reply["has_media"] is True
    assert reply["mimetype"] == "image/jpeg"
    assert reply["filename"] == "original.jpg"
    assert reply["provider_ref"].endswith("/api/files/original.jpg")
    assert "participant" not in reply
    assert "_data" not in reply


def test_quote_from_metadata_keeps_provider_ref_out_of_ai_context() -> None:
    quote = quote_from_metadata(
        {
            "reply_to": {
                "id": "m0",
                "body": "turn off the kitchen light",
                "has_media": True,
                "mimetype": "image/jpeg",
                "filename": "photo.jpg",
                "provider_ref": "http://waha/api/files/private.jpg",
            }
        }
    )

    assert quote is not None
    assert quote.message_id == "m0"
    assert quote.as_turn() == {
        "direction": "quoted_reference",
        "text": "turn off the kitchen light",
    }
    assert "provider_ref" not in quote.as_turn()


@dataclass
class RecordingUnderstanding:
    seen_text: str = ""
    seen_context: UnderstandingContext | None = None

    async def understand(self, text: str, *, context: UnderstandingContext) -> SemanticIntent:
        self.seen_text = text
        self.seen_context = context
        return SemanticIntent(
            raw_text=text,
            family="device_control",
            domain="switch",
            operation="off",
            target_text="kitchen light",
            confidence=0.99,
        )


@pytest.mark.asyncio
async def test_quoted_understanding_keeps_current_command_separate() -> None:
    base = RecordingUnderstanding()
    quote = quote_from_metadata(
        {"reply_to": {"id": "m0", "body": "the kitchen light", "has_media": False}}
    )
    assert quote is not None
    wrapped = QuotedContextUnderstanding(base, quote)
    original = UnderstandingContext(
        user_key="u1",
        recent_turns=({"direction": "inbound", "text": "earlier"},),
        active_context={"display_name": "Kitchen"},
    )

    intent = await wrapped.understand("turn it off too", context=original)

    assert base.seen_text == "turn it off too"
    assert base.seen_context is not None
    assert base.seen_context.recent_turns[-1] == {
        "direction": "quoted_reference",
        "text": "the kitchen light",
    }
    assert base.seen_context.active_context == {"display_name": "Kitchen"}
    assert intent.metadata["quoted_context_available"] is True


def test_empty_reply_context_is_ignored() -> None:
    assert reply_context_from_waha_event({"payload": {"replyTo": {}}}) is None
    assert quote_from_metadata({"reply_to": {}}) is None
