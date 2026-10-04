"""Safe provider-neutral media preprocessing for Bobi Next.

Inbound provider metadata is never fetched as an arbitrary URL by the brain.
A trusted provider adapter owns byte retrieval, this boundary enforces size and
MIME limits, and a pluggable analyzer turns supported media into text/context
before the normal deterministic Bobi engine sees the request.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from .messaging import InboundMessage

_MAX_MEDIA_BYTES = 25 * 1024 * 1024
_ALLOWED_PREFIXES = ("audio/", "image/")
_ALLOWED_DOCUMENT_MIMES = frozenset(
    {
        "application/pdf",
        "text/plain",
        "text/csv",
        "application/json",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
)


class MediaPipelineError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class MediaDescriptor:
    provider: str
    message_id: str
    kind: str
    mimetype: str
    filename: str = ""
    provider_ref: str = ""


@dataclass(slots=True, frozen=True)
class LoadedMedia:
    descriptor: MediaDescriptor
    content: bytes
    sha256: str


@dataclass(slots=True, frozen=True)
class MediaAnalysis:
    text: str
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class EnrichedMessage:
    text: str
    media: MediaAnalysis | None = None
    loaded_media: LoadedMedia | None = None


class TrustedMediaLoader(Protocol):
    async def load(self, descriptor: MediaDescriptor, *, max_bytes: int) -> bytes: ...


class MediaAnalyzer(Protocol):
    async def analyze(self, media: LoadedMedia) -> MediaAnalysis: ...


AnalyzerResolver = Callable[[str], MediaAnalyzer | None]


def descriptor_from_message(message: InboundMessage) -> MediaDescriptor | None:
    if message.kind == "text":
        return None
    raw = message.metadata.get("media")
    if not isinstance(raw, dict):
        raise MediaPipelineError("media_metadata_missing")
    mimetype = str(raw.get("mimetype") or "").strip().casefold()
    if not mimetype:
        raise MediaPipelineError("media_mimetype_missing")
    if not (
        mimetype.startswith(_ALLOWED_PREFIXES)
        or mimetype in _ALLOWED_DOCUMENT_MIMES
    ):
        raise MediaPipelineError("media_mimetype_not_allowed")
    return MediaDescriptor(
        provider=message.provider,
        message_id=message.message_id,
        kind=message.kind,
        mimetype=mimetype,
        filename=str(raw.get("filename") or "").strip()[:255],
        provider_ref=str(raw.get("url") or raw.get("provider_ref") or "").strip(),
    )


class MediaPipeline:
    def __init__(
        self,
        *,
        loader: TrustedMediaLoader,
        analyzer_for: AnalyzerResolver,
        max_bytes: int = _MAX_MEDIA_BYTES,
    ) -> None:
        self.loader = loader
        self.analyzer_for = analyzer_for
        self.max_bytes = max(1, min(int(max_bytes), _MAX_MEDIA_BYTES))

    async def enrich(self, message: InboundMessage) -> EnrichedMessage:
        descriptor = descriptor_from_message(message)
        if descriptor is None:
            return EnrichedMessage(message.text)

        analyzer = self.analyzer_for(descriptor.kind)
        if analyzer is None:
            raise MediaPipelineError(f"media_kind_not_supported:{descriptor.kind}")

        content = await self.loader.load(descriptor, max_bytes=self.max_bytes)
        if not isinstance(content, bytes):
            raise MediaPipelineError("media_loader_invalid_type")
        if not content:
            raise MediaPipelineError("media_empty")
        if len(content) > self.max_bytes:
            raise MediaPipelineError("media_too_large")

        loaded = LoadedMedia(
            descriptor=descriptor,
            content=content,
            sha256=hashlib.sha256(content).hexdigest(),
        )
        analysis = await analyzer.analyze(loaded)
        derived = str(analysis.text or analysis.summary or "").strip()
        caption = message.text.strip()
        if not derived and not caption:
            raise MediaPipelineError("media_analysis_empty")

        if caption and derived:
            text = f"{caption}\n\n[Media content]\n{derived}"
        else:
            text = caption or derived
        return EnrichedMessage(text=text, media=analysis, loaded_media=loaded)
