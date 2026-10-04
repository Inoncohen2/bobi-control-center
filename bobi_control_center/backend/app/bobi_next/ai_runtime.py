"""Runtime clients for configured Bobi Next AI providers.

The provider boundary is deliberately semantic-only. It may interpret text,
transcribe audio or describe an image, but it never receives Home Assistant
entity ids, service schemas, authorization tokens or execution tools.
Credentials are resolved from the local secret vault immediately before a
request and are never persisted by this module.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from .ai_providers import AIProviderConfig, AIProviderStore, SecretResolver
from .intent import SemanticIntent
from .understanding import UnderstandingTemporaryFailure, UnderstandingUnresolved

_INTENT_SYSTEM_PROMPT = """You are the semantic parser for a home assistant called Bobi.
Return exactly one JSON object and no prose. You only interpret the user's words.
Never invent a target, device, room, action, value or schedule that is not supported
by the user's message or supplied conversation context. Never output Home Assistant
entity ids or service calls.

Required fields:
family, domain, operation, target_text, confidence.
Optional fields:
target_scopes, aggregate_scope, value_kind, value, delta, scheduled, conditional,
contextual, reference_only, multi_target, exclusion, negated, schedule_kind,
schedule_payload, condition_payload, metadata.

confidence must be 0..1. Use metadata.question=true for questions. Preserve
negation. If the request cannot be safely interpreted, use family='unresolved',
empty domain/operation/target_text and low confidence.
"""

_VISION_SYSTEM_PROMPT = """Describe the user-provided image for Bobi. Focus on text,
objects and facts useful for answering or understanding the user's request. Do not
infer hidden facts. Return concise plain text only."""


class AIRuntimeError(RuntimeError):
    pass


def _base_url(endpoint: str) -> str:
    raw = str(endpoint or "").strip().rstrip("/")
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AIRuntimeError("ai_endpoint_invalid")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise AIRuntimeError("ai_endpoint_invalid")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _capability(config: AIProviderConfig, capability: str) -> None:
    if not config.enabled:
        raise AIRuntimeError("ai_provider_disabled")
    if capability not in config.capabilities:
        raise AIRuntimeError(f"ai_capability_missing:{capability}")


def _bounded_context(context: Any) -> dict[str, Any]:
    recent = getattr(context, "recent_turns", ()) or ()
    safe_turns: list[dict[str, str]] = []
    for turn in tuple(recent)[-8:]:
        if not isinstance(turn, dict):
            continue
        safe_turns.append(
            {
                "direction": str(turn.get("direction") or "")[:20],
                "text": str(turn.get("text") or "")[:1000],
            }
        )
    active = getattr(context, "active_context", None)
    safe_active: dict[str, Any] = {}
    if isinstance(active, dict):
        # Do not send Bobi/HA identifiers to the language provider. Contextual
        # pronouns can still be identified; deterministic code binds the target.
        for key in ("area_name", "object_type", "display_name"):
            value = active.get(key)
            if value:
                safe_active[key] = str(value)[:256]
    return {"recent_turns": safe_turns, "active_context": safe_active}


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _tuple_strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item)[:256] for item in value[:32] if str(item).strip())


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def semantic_intent_from_json(raw_text: str, payload: Any) -> SemanticIntent:
    if not isinstance(payload, dict):
        raise UnderstandingUnresolved("intent_response_not_object")
    family = str(payload.get("family") or "").strip()[:128]
    domain = str(payload.get("domain") or "").strip()[:128]
    operation = str(payload.get("operation") or "").strip()[:128]
    target_text = str(payload.get("target_text") or "").strip()[:1000]
    try:
        confidence = float(payload.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(confidence, 1.0))
    if not family:
        raise UnderstandingUnresolved("intent_family_missing")
    if family == "unresolved":
        raise UnderstandingUnresolved("provider_unresolved")

    schedule_payload = _dict(payload.get("schedule_payload"))
    condition_payload = _dict(payload.get("condition_payload"))
    metadata = _dict(payload.get("metadata"))
    return SemanticIntent(
        raw_text=raw_text,
        family=family,
        domain=domain,
        operation=operation,
        target_text=target_text,
        target_scopes=_tuple_strings(payload.get("target_scopes")),
        aggregate_scope=str(payload.get("aggregate_scope") or "")[:256],
        value_kind=str(payload.get("value_kind") or "none")[:64],
        value=payload.get("value"),
        delta=_float_or_none(payload.get("delta")),
        scheduled=bool(payload.get("scheduled", False)),
        conditional=bool(payload.get("conditional", False)),
        contextual=bool(payload.get("contextual", False)),
        reference_only=bool(payload.get("reference_only", False)),
        multi_target=bool(payload.get("multi_target", False)),
        exclusion=bool(payload.get("exclusion", False)),
        negated=bool(payload.get("negated", False)),
        confidence=confidence,
        schedule_kind=str(payload.get("schedule_kind") or "")[:64],
        schedule_payload=schedule_payload,
        condition_payload=condition_payload,
        metadata=metadata,
    )


@dataclass(slots=True)
class OpenAICompatibleProvider:
    config: AIProviderConfig
    secrets: SecretResolver
    client: httpx.AsyncClient | None = None
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        self.base_url = _base_url(self.config.endpoint)

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.config.secret_ref:
            secret = self.secrets.resolve(self.config.secret_ref)
            if not secret:
                raise AIRuntimeError("ai_secret_empty")
            headers["Authorization"] = f"Bearer {secret}"
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
    ) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        kwargs: dict[str, Any] = {
            "headers": self._headers(),
            "timeout": self.timeout_seconds,
        }
        if json_body is not None:
            kwargs["json"] = json_body
        if files is not None:
            kwargs["files"] = files
        if data is not None:
            kwargs["data"] = data
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient(follow_redirects=False)
        try:
            response = await client.request(method, url, **kwargs)
            if response.status_code == 429 or response.status_code >= 500:
                raise UnderstandingTemporaryFailure(f"ai_http_{response.status_code}")
            if response.status_code >= 400:
                raise AIRuntimeError(f"ai_http_{response.status_code}")
            try:
                return response.json()
            except ValueError as exc:
                raise AIRuntimeError("ai_response_not_json") from exc
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise UnderstandingTemporaryFailure("ai_transport_failure") from exc
        finally:
            if owns_client:
                await client.aclose()

    async def understand(self, text: str, *, context: Any) -> SemanticIntent:
        _capability(self.config, "intent")
        if not self.config.model.strip():
            raise AIRuntimeError("ai_model_missing")
        body = {
            "model": self.config.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _INTENT_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"text": text, "context": _bounded_context(context)},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            ],
        }
        payload = await self._request("POST", "chat/completions", json_body=body)
        try:
            content = payload["choices"][0]["message"]["content"]
            decoded = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise UnderstandingUnresolved("intent_response_invalid") from exc
        return semantic_intent_from_json(text, decoded)

    async def transcribe(
        self,
        content: bytes,
        *,
        mimetype: str,
        filename: str,
    ) -> str:
        _capability(self.config, "audio")
        model = str(self.config.config.get("audio_model") or "").strip()
        if not model:
            raise AIRuntimeError("audio_model_missing")
        safe_name = filename.strip() or "audio.bin"
        payload = await self._request(
            "POST",
            "audio/transcriptions",
            files={"file": (safe_name, content, mimetype)},
            data={"model": model, "response_format": "json"},
        )
        text = str(_dict(payload).get("text") or "").strip()
        if not text:
            raise AIRuntimeError("audio_transcription_empty")
        return text

    async def describe(
        self,
        content: bytes,
        *,
        mimetype: str,
        filename: str,
    ) -> str:
        del filename
        _capability(self.config, "vision")
        model = str(self.config.config.get("vision_model") or self.config.model).strip()
        if not model:
            raise AIRuntimeError("vision_model_missing")
        encoded = base64.b64encode(content).decode("ascii")
        body = {
            "model": model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": _VISION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this image for Bobi."},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mimetype};base64,{encoded}"},
                        },
                    ],
                },
            ],
        }
        payload = await self._request("POST", "chat/completions", json_body=body)
        try:
            text = str(payload["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise AIRuntimeError("vision_response_invalid") from exc
        if not text:
            raise AIRuntimeError("vision_response_empty")
        return text


class AIProviderRuntimeRegistry:
    """Resolve configured providers by capability without exposing credentials."""

    def __init__(
        self,
        store: AIProviderStore,
        secrets: SecretResolver,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.store = store
        self.secrets = secrets
        self.client = client

    def for_capability(self, capability: str) -> OpenAICompatibleProvider:
        active = self.store.active()
        candidates = ((active,) if active is not None else ()) + self.store.list_enabled()
        seen: set[str] = set()
        for config in candidates:
            if config.provider_key in seen:
                continue
            seen.add(config.provider_key)
            if capability not in config.capabilities:
                continue
            if config.provider_type not in {"openai-compatible", "openai_compatible"}:
                continue
            return OpenAICompatibleProvider(config, self.secrets, client=self.client)
        raise AIRuntimeError(f"ai_provider_unavailable:{capability}")

    def intent_provider(self) -> OpenAICompatibleProvider:
        return self.for_capability("intent")

    def audio_provider(self) -> OpenAICompatibleProvider:
        return self.for_capability("audio")

    def vision_provider(self) -> OpenAICompatibleProvider:
        return self.for_capability("vision")
