from __future__ import annotations

import httpx
import pytest

from app.bobi_next.media_pipeline import (
    LoadedMedia,
    MediaAnalysis,
    MediaDescriptor,
    MediaPipeline,
    MediaPipelineError,
    descriptor_from_message,
)
from app.bobi_next.messaging import InboundMessage
from app.bobi_next.waha_adapter import WahaMediaLoader


def _message(
    *,
    kind: str = "voice",
    text: str = "",
    mimetype: str = "audio/ogg",
    url: str = "http://untrusted.example/api/files/message.ogg",
) -> InboundMessage:
    return InboundMessage(
        row_id=1,
        provider="waha-main",
        message_id="m1",
        chat_id="chat-1",
        user_key="u1",
        text=text,
        kind=kind,
        received_ts=100,
        state="running",
        metadata={
            "media": {
                "url": url,
                "mimetype": mimetype,
                "filename": "voice.ogg",
            }
        },
    )


class StaticLoader:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.seen: list[tuple[MediaDescriptor, int]] = []

    async def load(self, descriptor: MediaDescriptor, *, max_bytes: int) -> bytes:
        self.seen.append((descriptor, max_bytes))
        return self.content


class StaticAnalyzer:
    def __init__(self, text: str) -> None:
        self.text = text
        self.seen: list[LoadedMedia] = []

    async def analyze(self, media: LoadedMedia) -> MediaAnalysis:
        self.seen.append(media)
        return MediaAnalysis(text=self.text, metadata={"source": "test"})


def test_descriptor_rejects_unknown_mimetype() -> None:
    with pytest.raises(MediaPipelineError, match="media_mimetype_not_allowed"):
        descriptor_from_message(_message(kind="document", mimetype="application/x-executable"))


@pytest.mark.asyncio
async def test_pipeline_combines_caption_and_analyzed_media() -> None:
    loader = StaticLoader(b"voice-bytes")
    analyzer = StaticAnalyzer("turn the room switch off")
    pipeline = MediaPipeline(
        loader=loader,
        analyzer_for=lambda kind: analyzer if kind == "voice" else None,
        max_bytes=1024,
    )

    result = await pipeline.enrich(_message(text="please do this"))

    assert result.text == "please do this\n\n[Media content]\nturn the room switch off"
    assert result.media is not None
    assert result.loaded_media is analyzer.seen[0]
    assert result.loaded_media.content == b"voice-bytes"
    assert len(loader.seen) == 1
    assert analyzer.seen[0].sha256


@pytest.mark.asyncio
async def test_pipeline_enforces_byte_limit_even_if_loader_misbehaves() -> None:
    pipeline = MediaPipeline(
        loader=StaticLoader(b"x" * 11),
        analyzer_for=lambda kind: StaticAnalyzer("ok"),
        max_bytes=10,
    )
    with pytest.raises(MediaPipelineError, match="media_too_large"):
        await pipeline.enrich(_message())


class UnavailableAnalyzer:
    async def analyze(self, media):
        del media
        raise TimeoutError("analysis unavailable")


@pytest.mark.asyncio
@pytest.mark.parametrize("analyzer", [None, UnavailableAnalyzer()])
async def test_archive_preprocessing_preserves_trusted_bytes_without_analysis(analyzer):
    loader = StaticLoader(b"scanned-pdf-bytes")
    pipeline = MediaPipeline(loader=loader, analyzer_for=lambda kind: analyzer)
    message = _message(kind="document", mimetype="application/pdf", text="שמור את זה")

    result = await pipeline.enrich(message, analysis_required=False)

    assert result.loaded_media is not None
    assert result.loaded_media.content == b"scanned-pdf-bytes"
    assert result.loaded_media.descriptor.message_id == message.message_id
    assert result.media is None
    assert result.text == message.text
    assert len(loader.seen) == 1


@pytest.mark.asyncio
async def test_optional_analysis_never_relaxes_mime_or_size_boundary():
    loader = StaticLoader(b"x" * 11)
    pipeline = MediaPipeline(loader=loader, analyzer_for=lambda kind: None, max_bytes=10)
    with pytest.raises(MediaPipelineError, match="media_mimetype_not_allowed"):
        await pipeline.enrich(
            _message(kind="document", mimetype="application/x-executable"),
            analysis_required=False,
        )
    assert loader.seen == []
    with pytest.raises(MediaPipelineError, match="media_too_large"):
        await pipeline.enrich(
            _message(kind="document", mimetype="application/pdf"),
            analysis_required=False,
        )


@pytest.mark.asyncio
async def test_waha_loader_rewrites_host_to_configured_waha_and_sends_api_key() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"abc", headers={"content-length": "3"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        loader = WahaMediaLoader(
            base_url="http://waha.internal:3000",
            api_key="secret-key",
            client=client,
        )
        data = await loader.load(
            MediaDescriptor(
                provider="waha-main",
                message_id="m1",
                kind="image",
                mimetype="image/jpeg",
                provider_ref="https://attacker.example/api/files/random.jpg?download=1",
            ),
            max_bytes=1024,
        )

    assert data == b"abc"
    assert len(seen) == 1
    assert seen[0].url.host == "waha.internal"
    assert seen[0].url.port == 3000
    assert seen[0].url.path == "/api/files/random.jpg"
    assert seen[0].headers["x-api-key"] == "secret-key"


@pytest.mark.asyncio
async def test_waha_loader_rejects_non_file_path_and_traversal() -> None:
    loader = WahaMediaLoader(base_url="http://waha.internal:3000")
    descriptor = MediaDescriptor(
        provider="waha-main",
        message_id="m1",
        kind="document",
        mimetype="application/pdf",
        provider_ref="https://attacker.example/api/sessions/default",
    )
    with pytest.raises(MediaPipelineError, match="waha_media_path_not_allowed"):
        await loader.load(descriptor, max_bytes=100)

    traversal = MediaDescriptor(
        provider="waha-main",
        message_id="m2",
        kind="document",
        mimetype="application/pdf",
        provider_ref="http://waha/api/files/%2e%2e/secret",
    )
    with pytest.raises(MediaPipelineError, match="waha_media_path_not_allowed"):
        await loader.load(traversal, max_bytes=100)


@pytest.mark.asyncio
async def test_waha_loader_stops_when_content_length_is_too_large() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, content=b"0123456789", headers={"content-length": "10"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        loader = WahaMediaLoader(base_url="http://waha", client=client)
        with pytest.raises(MediaPipelineError, match="media_too_large"):
            await loader.load(
                MediaDescriptor(
                    provider="waha-main",
                    message_id="m1",
                    kind="image",
                    mimetype="image/jpeg",
                    provider_ref="http://localhost/api/files/photo.jpg",
                ),
                max_bytes=5,
            )
