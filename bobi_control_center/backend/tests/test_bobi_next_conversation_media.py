from __future__ import annotations

import pytest

from app.bobi_next.conversation_handler import build_conversation_handler
from app.bobi_next.engine import EngineResult
from app.bobi_next.media_pipeline import EnrichedMessage
from app.bobi_next.messaging import InboundMessage


class MemoryStub:
    def __init__(self) -> None:
        self.turns = []

    def store_turn(self, *args, **kwargs) -> None:
        self.turns.append((args, kwargs))


class ExplodingPending:
    def latest_pending_for_user(self, *args, **kwargs):
        raise AssertionError("media must never enter approval continuation")


class MediaStub:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    async def enrich(self, message: InboundMessage) -> EnrichedMessage:
        self.calls += 1
        return EnrichedMessage(self.text)


def _media_message(text: str = "כן") -> InboundMessage:
    return InboundMessage(
        row_id=1,
        provider="waha-main",
        message_id="voice-1",
        chat_id="chat-1",
        user_key="u1",
        text=text,
        kind="voice",
        received_ts=100,
        state="running",
        metadata={
            "media": {
                "url": "http://waha/api/files/voice.ogg",
                "mimetype": "audio/ogg",
            }
        },
    )


@pytest.mark.asyncio
async def test_media_text_that_says_yes_cannot_approve_pending_action(monkeypatch) -> None:
    captured = []

    async def fake_process(request, **kwargs):
        del kwargs
        captured.append(request)
        return EngineResult(request.request_id, "shadow", "dry_run")

    monkeypatch.setattr(
        "app.bobi_next.conversation_handler.process_request",
        fake_process,
    )
    media = MediaStub("turn the room light off")
    handler = build_conversation_handler(
        understanding=object(),  # type: ignore[arg-type]
        list_devices=object(),  # type: ignore[arg-type]
        policy_for=object(),  # type: ignore[arg-type]
        ha=object(),  # type: ignore[arg-type]
        memory=MemoryStub(),  # type: ignore[arg-type]
        requests=object(),  # type: ignore[arg-type]
        pending_approvals=ExplodingPending(),  # type: ignore[arg-type]
        approval_tokens=object(),  # type: ignore[arg-type]
        media_pipeline=media,  # type: ignore[arg-type]
        dry_run=True,
        clock=lambda: 100,
    )

    response = await handler(_media_message("כן"))

    assert response.text == "הפקודה נבדקה במצב Shadow ולא בוצעה בפועל."
    assert media.calls == 1
    assert len(captured) == 1
    assert captured[0].text == "turn the room light off"


@pytest.mark.asyncio
async def test_media_without_pipeline_fails_closed_before_understanding(monkeypatch) -> None:
    async def should_not_run(*args, **kwargs):
        del args, kwargs
        raise AssertionError("engine must not receive raw unprocessed media")

    monkeypatch.setattr(
        "app.bobi_next.conversation_handler.process_request",
        should_not_run,
    )
    handler = build_conversation_handler(
        understanding=object(),  # type: ignore[arg-type]
        list_devices=object(),  # type: ignore[arg-type]
        policy_for=object(),  # type: ignore[arg-type]
        ha=object(),  # type: ignore[arg-type]
        memory=MemoryStub(),  # type: ignore[arg-type]
        requests=object(),  # type: ignore[arg-type]
        pending_approvals=ExplodingPending(),  # type: ignore[arg-type]
        approval_tokens=object(),  # type: ignore[arg-type]
        media_pipeline=None,
        clock=lambda: 100,
    )

    response = await handler(_media_message("caption"))

    assert "עיבוד המדיה" in response.text
