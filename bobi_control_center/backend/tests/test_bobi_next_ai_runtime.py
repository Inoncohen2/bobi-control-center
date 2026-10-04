from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from app.bobi_next.ai_providers import AIProviderConfig, AIProviderStore
from app.bobi_next.ai_runtime import (
    AIRuntimeError,
    AIProviderRuntimeRegistry,
    OpenAICompatibleProvider,
    semantic_intent_from_json,
)
from app.bobi_next.secret_vault import EncryptedSecretVault
from app.bobi_next.understanding import UnderstandingTemporaryFailure, UnderstandingUnresolved


def _config(*, capabilities=frozenset({"intent", "audio", "vision"}), config=None):
    return AIProviderConfig(
        provider_key="ai:primary",
        provider_type="openai-compatible",
        display_name="Primary AI",
        endpoint="https://ai.example.test/v1",
        model="intent-model",
        secret_ref="vault:///0123456789012345678901234567890123456789",
        enabled=True,
        capabilities=capabilities,
        config=config or {"audio_model": "audio-model", "vision_model": "vision-model"},
    )


class StaticSecrets:
    def __init__(self, value="runtime-secret"):
        self.value = value
        self.refs = []

    def resolve(self, secret_ref: str) -> str:
        self.refs.append(secret_ref)
        return self.value


def test_semantic_parser_clamps_confidence_and_preserves_safety_fields():
    intent = semantic_intent_from_json(
        "don't turn it on",
        {
            "family": "device_control",
            "domain": "switch",
            "operation": "on",
            "target_text": "it",
            "confidence": 4.2,
            "contextual": True,
            "reference_only": True,
            "negated": True,
            "metadata": {"question": False},
        },
    )
    assert intent.confidence == 1.0
    assert intent.contextual is True
    assert intent.reference_only is True
    assert intent.negated is True


@pytest.mark.asyncio
async def test_intent_request_uses_secret_only_in_header_and_hides_internal_ids():
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        user_payload = json.loads(body["messages"][1]["content"])
        assert user_payload["text"] == "turn it off"
        assert "bobi_device_id" not in body["messages"][1]["content"]
        assert "entity_id" not in body["messages"][1]["content"]
        assert user_payload["context"]["active_context"] == {"display_name": "room switch"}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "family": "device_control",
                                    "domain": "switch",
                                    "operation": "off",
                                    "target_text": "it",
                                    "contextual": True,
                                    "reference_only": True,
                                    "confidence": 0.96,
                                }
                            )
                        }
                    }
                ]
            },
        )

    secrets = StaticSecrets()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(_config(), secrets, client=client)
        context = SimpleNamespace(
            recent_turns=({"direction": "inbound", "text": "use the room switch"},),
            active_context={
                "bobi_device_id": "dev-private",
                "entity_id": "switch.private",
                "display_name": "room switch",
            },
        )
        intent = await provider.understand("turn it off", context=context)

    assert intent.canonical_domain == "switch"
    assert intent.canonical_operation == "off"
    assert intent.contextual is True
    assert seen[0].url == httpx.URL("https://ai.example.test/v1/chat/completions")
    assert seen[0].headers["authorization"] == "Bearer runtime-secret"
    assert b"runtime-secret" not in seen[0].content
    assert secrets.refs == [_config().secret_ref]


@pytest.mark.asyncio
async def test_invalid_intent_output_fails_as_unresolved():
    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(_config(), StaticSecrets(), client=client)
        with pytest.raises(UnderstandingUnresolved, match="intent_response_invalid"):
            await provider.understand("hello", context=SimpleNamespace())


@pytest.mark.asyncio
async def test_provider_5xx_is_retryable_understanding_failure():
    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(503, json={"error": "busy"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(_config(), StaticSecrets(), client=client)
        with pytest.raises(UnderstandingTemporaryFailure, match="ai_http_503"):
            await provider.understand("hello", context=SimpleNamespace())


@pytest.mark.asyncio
async def test_audio_transcription_is_multipart_and_uses_configured_model():
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.url.path == "/v1/audio/transcriptions"
        assert request.headers["authorization"] == "Bearer runtime-secret"
        assert request.headers["content-type"].startswith("multipart/form-data;")
        assert b'audio-model' in request.content
        assert b'voice.ogg' in request.content
        assert b'voice-bytes' in request.content
        return httpx.Response(200, json={"text": "turn the light off"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(_config(), StaticSecrets(), client=client)
        text = await provider.transcribe(
            b"voice-bytes",
            mimetype="audio/ogg",
            filename="voice.ogg",
        )
    assert text == "turn the light off"
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_vision_uses_inline_data_url_not_external_image_url():
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "vision-model"
        content = body["messages"][1]["content"]
        image_url = content[1]["image_url"]["url"]
        assert image_url.startswith("data:image/jpeg;base64,")
        assert "http" not in image_url
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "A coffee machine display showing 2 cups."}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(_config(), StaticSecrets(), client=client)
        text = await provider.describe(b"image-bytes", mimetype="image/jpeg", filename="photo.jpg")
    assert "coffee machine" in text


def test_capability_is_fail_closed():
    provider = OpenAICompatibleProvider(
        _config(capabilities=frozenset({"intent"})),
        StaticSecrets(),
    )
    with pytest.raises(AIRuntimeError, match="ai_capability_missing:audio"):
        # Capability validation occurs before any HTTP request.
        import asyncio

        asyncio.run(provider.transcribe(b"x", mimetype="audio/ogg", filename="x.ogg"))


def test_runtime_registry_resolves_vault_secret_and_provider_by_capability(tmp_path):
    vault = EncryptedSecretVault(tmp_path / "secrets.db", tmp_path / "secrets.key")
    store = AIProviderStore(tmp_path / "ai.db")
    try:
        secret_ref = vault.put("ai:primary", "real-secret")
        store.upsert(
            provider_key="ai:primary",
            provider_type="openai-compatible",
            display_name="Primary",
            endpoint="https://ai.example.test/v1",
            model="intent-model",
            secret_ref=secret_ref,
            capabilities=frozenset({"intent", "vision"}),
            config={"vision_model": "vision-model"},
            now_ts=100,
        )
        store.select("ai:primary", now_ts=100)
        registry = AIProviderRuntimeRegistry(store, vault)
        intent = registry.intent_provider()
        vision = registry.vision_provider()
        assert intent.config.provider_key == "ai:primary"
        assert vision.config.provider_key == "ai:primary"
        assert intent._headers()["Authorization"] == "Bearer real-secret"
        with pytest.raises(AIRuntimeError, match="ai_provider_unavailable:audio"):
            registry.audio_provider()
    finally:
        store.close()
        vault.close()
