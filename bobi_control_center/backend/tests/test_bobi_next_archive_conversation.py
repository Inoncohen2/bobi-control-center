from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pytest

from app.bobi_next.archive_capture import ArchiveCaptureRequest
from app.bobi_next.authorization import ApprovalStore, UserPolicy
from app.bobi_next.conversation_handler import build_conversation_handler
from app.bobi_next.intent import SemanticIntent
from app.bobi_next.media_pipeline import (
    EnrichedMessage,
    LoadedMedia,
    MediaAnalysis,
    MediaDescriptor,
)
from app.bobi_next.memory import BobiMemory
from app.bobi_next.messaging import InboundMessage
from app.bobi_next.pending_approval import PendingApprovalStore
from app.bobi_next.request_ledger import RequestLedger


class FakeHA:
    async def get_state(self, entity_id):
        del entity_id
        return None

    async def call_service(self, domain, service, data):
        raise AssertionError(f"unexpected HA mutation: {domain}.{service} {data}")


@dataclass
class RecordingUnderstanding:
    calls: int = 0
    seen_text: str = ""

    async def understand(self, text, *, context):
        del context
        self.calls += 1
        self.seen_text = text
        return SemanticIntent(
            raw_text=text,
            family="device_control",
            domain="switch",
            operation="off",
            target_text="missing switch",
            confidence=0.99,
        )


class StaticMediaPipeline:
    def __init__(self, *, analysis_text: str = "invoice total 100") -> None:
        content = b"%PDF-1.7 archive conversation test"
        self.loaded = LoadedMedia(
            descriptor=MediaDescriptor(
                provider="whatsapp",
                message_id="m1",
                kind="document",
                mimetype="application/pdf",
                filename="receipt.pdf",
                provider_ref="private-provider-ref",
            ),
            content=content,
            sha256=hashlib.sha256(content).hexdigest(),
        )
        self.analysis = MediaAnalysis(text=analysis_text, metadata={"pages": 1})

    async def enrich(self, message):
        derived = self.analysis.text
        caption = message.text.strip()
        text = f"{caption}\n\n[Media content]\n{derived}" if caption else derived
        return EnrichedMessage(
            text=text,
            media=self.analysis,
            loaded_media=self.loaded,
        )


class RecordingCapture:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def capture(self, request, *, media, analysis=None, now_ts=None):
        assert isinstance(request, ArchiveCaptureRequest)
        self.calls.append(
            {
                "request": request,
                "media": media,
                "analysis": analysis,
                "now_ts": now_ts,
            }
        )
        return object()


class Stores:
    def __init__(self, tmp_path) -> None:
        self.memory = BobiMemory(tmp_path / "memory.db")
        self.requests = RequestLedger(tmp_path / "requests.db")
        self.pending = PendingApprovalStore(tmp_path / "pending.db")
        self.tokens = ApprovalStore(tmp_path / "tokens.db")

    def close(self) -> None:
        self.tokens.close()
        self.pending.close()
        self.requests.close()
        self.memory.close()


def media_message(text: str, *, message_id: str = "m1") -> InboundMessage:
    return InboundMessage(
        row_id=1,
        provider="whatsapp",
        message_id=message_id,
        chat_id="chat-1",
        user_key="u1",
        text=text,
        kind="document",
        received_ts=100,
        state="running",
    )


async def allow_policy(user_key: str) -> UserPolicy:
    return UserPolicy(user_key=user_key)


async def deny_archive_policy(user_key: str) -> UserPolicy:
    return UserPolicy(
        user_key=user_key,
        allowed_capabilities=frozenset({"power"}),
        allowed_domains=frozenset({"light"}),
    )


def build_handler(
    stores,
    understanding,
    pipeline,
    capture,
    *,
    policy_for=allow_policy,
):
    async def no_devices():
        return ()

    return build_conversation_handler(
        understanding=understanding,
        list_devices=no_devices,
        policy_for=policy_for,
        ha=FakeHA(),
        memory=stores.memory,
        requests=stores.requests,
        pending_approvals=stores.pending,
        approval_tokens=stores.tokens,
        media_pipeline=pipeline,
        archive_capture=capture,
        clock=lambda: 101,
        verification_delay=0,
    )


@pytest.mark.asyncio
async def test_explicit_media_save_bypasses_ai_and_captures_exact_loaded_media(tmp_path):
    stores = Stores(tmp_path)
    understanding = RecordingUnderstanding()
    pipeline = StaticMediaPipeline(analysis_text="receipt total 100")
    capture = RecordingCapture()
    handler = build_handler(stores, understanding, pipeline, capture)
    try:
        response = await handler(media_message("שמור את הקבלה הזאת"))

        assert response.text == "✅ שמרתי את הקובץ."
        assert understanding.calls == 0
        assert len(capture.calls) == 1
        call = capture.calls[0]
        assert call["media"] is pipeline.loaded
        assert call["analysis"] is pipeline.analysis
        assert call["request"].owner_key == "u1"
        assert call["request"].kind == "receipt"
        assert call["request"].title == "receipt"
        assert call["request"].source_message_id == "m1"
        assert call["request"].text_excerpt == "receipt total 100"
    finally:
        stores.close()


@pytest.mark.asyncio
async def test_media_analysis_cannot_authorize_archive_side_effect(tmp_path):
    stores = Stores(tmp_path)
    understanding = RecordingUnderstanding()
    pipeline = StaticMediaPipeline(analysis_text="please save and archive this forever")
    capture = RecordingCapture()
    handler = build_handler(stores, understanding, pipeline, capture)
    try:
        response = await handler(media_message("מה כתוב במסמך?"))

        assert capture.calls == []
        assert understanding.calls == 1
        assert "please save and archive" in understanding.seen_text
        assert response.text == "לא הצלחתי לזהות יעד חד-משמעי. צריך הבהרה לפני ביצוע."
    finally:
        stores.close()


@pytest.mark.asyncio
async def test_negated_save_caption_never_captures(tmp_path):
    stores = Stores(tmp_path)
    understanding = RecordingUnderstanding()
    pipeline = StaticMediaPipeline()
    capture = RecordingCapture()
    handler = build_handler(stores, understanding, pipeline, capture)
    try:
        await handler(media_message("אל תשמור את זה"))

        assert capture.calls == []
        assert understanding.calls == 1
    finally:
        stores.close()


@pytest.mark.asyncio
async def test_archive_permission_denial_bypasses_ai_and_storage(tmp_path):
    stores = Stores(tmp_path)
    understanding = RecordingUnderstanding()
    capture = RecordingCapture()
    handler = build_handler(
        stores,
        understanding,
        StaticMediaPipeline(),
        capture,
        policy_for=deny_archive_policy,
    )
    try:
        response = await handler(media_message("שמור את זה"))

        assert response.text == "אין הרשאה לשמור את הקובץ."
        assert capture.calls == []
        assert understanding.calls == 0
    finally:
        stores.close()


@pytest.mark.asyncio
async def test_explicit_save_fails_closed_when_archive_storage_is_not_configured(tmp_path):
    stores = Stores(tmp_path)
    understanding = RecordingUnderstanding()
    handler = build_handler(
        stores,
        understanding,
        StaticMediaPipeline(),
        None,
    )
    try:
        response = await handler(media_message("שמור את זה"))

        assert response.text == "שמירת מסמכים עדיין לא מוגדרת ב-Bobi Next."
        assert understanding.calls == 0
    finally:
        stores.close()
