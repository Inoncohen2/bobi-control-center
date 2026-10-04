from __future__ import annotations

import hashlib
import io
import zipfile

import pytest

from app.bobi_next.media_analyzers import (
    AudioAnalyzer,
    DocumentAnalyzer,
    ImageAnalyzer,
    MediaAnalyzerRegistry,
)
from app.bobi_next.media_pipeline import LoadedMedia, MediaDescriptor, MediaPipelineError


def _loaded(content: bytes, *, kind: str, mimetype: str, filename: str = "") -> LoadedMedia:
    return LoadedMedia(
        descriptor=MediaDescriptor(
            provider="test",
            message_id="m1",
            kind=kind,
            mimetype=mimetype,
            filename=filename,
        ),
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
    )


class Transcriber:
    async def transcribe(self, content: bytes, *, mimetype: str, filename: str) -> str:
        assert content == b"audio"
        assert mimetype == "audio/ogg"
        assert filename == "note.ogg"
        return "turn the light off"


class Vision:
    async def describe(self, content: bytes, *, mimetype: str, filename: str) -> str:
        assert content == b"image"
        assert mimetype == "image/jpeg"
        return "A photo of the living room thermostat display"


@pytest.mark.asyncio
async def test_audio_and_image_adapters_only_return_semantic_text() -> None:
    audio = AudioAnalyzer(Transcriber())
    image = ImageAnalyzer(Vision())

    audio_result = await audio.analyze(
        _loaded(b"audio", kind="voice", mimetype="audio/ogg", filename="note.ogg")
    )
    image_result = await image.analyze(
        _loaded(b"image", kind="image", mimetype="image/jpeg", filename="photo.jpg")
    )

    assert audio_result.text == "turn the light off"
    assert audio_result.metadata["kind"] == "voice"
    assert image_result.text.startswith("A photo")
    assert image_result.metadata["kind"] == "image"


@pytest.mark.asyncio
async def test_document_analyzer_extracts_text_json_and_docx() -> None:
    analyzer = DocumentAnalyzer()

    text = await analyzer.analyze(
        _loaded(b"hello\nworld", kind="document", mimetype="text/plain", filename="a.txt")
    )
    assert text.text == "hello\nworld"

    parsed = await analyzer.analyze(
        _loaded(
            b'{"name":"Bobi","ok":true}',
            kind="document",
            mimetype="application/json",
            filename="a.json",
        )
    )
    assert '"name": "Bobi"' in parsed.text

    xml = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b'<w:body><w:p><w:r><w:t>Hello DOCX</w:t></w:r></w:p></w:body></w:document>'
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    docx = await analyzer.analyze(
        _loaded(
            buffer.getvalue(),
            kind="document",
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename="a.docx",
        )
    )
    assert docx.text == "Hello DOCX"


@pytest.mark.asyncio
async def test_document_analyzer_rejects_legacy_doc_and_invalid_pdf() -> None:
    analyzer = DocumentAnalyzer()
    with pytest.raises(MediaPipelineError, match="document_format_not_supported"):
        await analyzer.analyze(
            _loaded(
                b"legacy",
                kind="document",
                mimetype="application/msword",
                filename="a.doc",
            )
        )

    with pytest.raises(MediaPipelineError, match="document_pdf_invalid"):
        await analyzer.analyze(
            _loaded(
                b"not a pdf",
                kind="document",
                mimetype="application/pdf",
                filename="a.pdf",
            )
        )


def test_registry_defaults_to_local_document_analyzer() -> None:
    registry = MediaAnalyzerRegistry()
    assert registry.get("document") is not None
    assert registry.get("voice") is None
    assert registry.get("image") is None
