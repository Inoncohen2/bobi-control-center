"""Media analyzers for Bobi Next.

Documents have a deterministic local extractor. Audio and image understanding
stay provider-neutral: setup may inject any transcription/vision backend without
letting that backend resolve Home Assistant targets or execute side effects.
"""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol
from xml.etree import ElementTree

from pypdf import PdfReader

from .media_pipeline import LoadedMedia, MediaAnalysis, MediaAnalyzer, MediaPipelineError

_MAX_EXTRACTED_CHARS = 120_000


class AudioTranscriber(Protocol):
    async def transcribe(
        self,
        content: bytes,
        *,
        mimetype: str,
        filename: str,
    ) -> str: ...


class ImageInterpreter(Protocol):
    async def describe(
        self,
        content: bytes,
        *,
        mimetype: str,
        filename: str,
    ) -> str: ...


@dataclass(slots=True)
class AudioAnalyzer(MediaAnalyzer):
    transcriber: AudioTranscriber

    async def analyze(self, media: LoadedMedia) -> MediaAnalysis:
        text = await self.transcriber.transcribe(
            media.content,
            mimetype=media.descriptor.mimetype,
            filename=media.descriptor.filename,
        )
        clean = str(text or "").strip()
        if not clean:
            raise MediaPipelineError("audio_transcription_empty")
        return MediaAnalysis(
            text=clean,
            metadata={"kind": "voice", "sha256": media.sha256},
        )


@dataclass(slots=True)
class ImageAnalyzer(MediaAnalyzer):
    interpreter: ImageInterpreter

    async def analyze(self, media: LoadedMedia) -> MediaAnalysis:
        text = await self.interpreter.describe(
            media.content,
            mimetype=media.descriptor.mimetype,
            filename=media.descriptor.filename,
        )
        clean = str(text or "").strip()
        if not clean:
            raise MediaPipelineError("image_analysis_empty")
        return MediaAnalysis(
            text=clean,
            metadata={"kind": "image", "sha256": media.sha256},
        )


def _bounded(text: str) -> str:
    compact = text.replace("\x00", "").strip()
    if len(compact) > _MAX_EXTRACTED_CHARS:
        return compact[:_MAX_EXTRACTED_CHARS]
    return compact


def _extract_text(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("utf-8", errors="replace")


def _extract_json(content: bytes) -> str:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MediaPipelineError("document_json_invalid") from exc
    return json.dumps(value, ensure_ascii=False, indent=2)


def _extract_pdf(content: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(content))
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except Exception as exc:
        raise MediaPipelineError("document_pdf_invalid") from exc
    text = "\n\n".join(page for page in pages if page)
    if not text:
        raise MediaPipelineError("document_pdf_no_text")
    return text


def _extract_docx(content: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            xml = archive.read("word/document.xml")
        root = ElementTree.fromstring(xml)
    except (KeyError, OSError, ValueError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise MediaPipelineError("document_docx_invalid") from exc

    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs: list[str] = []
    for paragraph in root.iter(f"{namespace}p"):
        pieces = [node.text or "" for node in paragraph.iter(f"{namespace}t")]
        text = "".join(pieces).strip()
        if text:
            paragraphs.append(text)
    if not paragraphs:
        raise MediaPipelineError("document_docx_no_text")
    return "\n".join(paragraphs)


class DocumentAnalyzer(MediaAnalyzer):
    async def analyze(self, media: LoadedMedia) -> MediaAnalysis:
        mimetype = media.descriptor.mimetype
        if mimetype in {"text/plain", "text/csv"}:
            text = _extract_text(media.content)
        elif mimetype == "application/json":
            text = _extract_json(media.content)
        elif mimetype == "application/pdf":
            text = _extract_pdf(media.content)
        elif mimetype == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            text = _extract_docx(media.content)
        else:
            raise MediaPipelineError("document_format_not_supported")
        clean = _bounded(text)
        if not clean:
            raise MediaPipelineError("document_text_empty")
        return MediaAnalysis(
            text=clean,
            metadata={
                "kind": "document",
                "mimetype": mimetype,
                "filename": media.descriptor.filename,
                "sha256": media.sha256,
            },
        )


class MediaAnalyzerRegistry:
    def __init__(
        self,
        *,
        audio: MediaAnalyzer | None = None,
        image: MediaAnalyzer | None = None,
        document: MediaAnalyzer | None = None,
    ) -> None:
        self._items = {
            "voice": audio,
            "audio": audio,
            "image": image,
            "document": document or DocumentAnalyzer(),
        }

    def get(self, kind: str) -> MediaAnalyzer | None:
        return self._items.get(str(kind or "").strip().casefold())
