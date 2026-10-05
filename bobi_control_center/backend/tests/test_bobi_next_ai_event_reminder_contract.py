from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from app.bobi_next.ai_providers import AIProviderConfig
from app.bobi_next.ai_runtime import OpenAICompatibleProvider


class StaticSecrets:
    def resolve(self, secret_ref: str) -> str:
        del secret_ref
        return "runtime-secret"


def _config() -> AIProviderConfig:
    return AIProviderConfig(
        provider_key="ai:primary",
        provider_type="openai-compatible",
        display_name="Primary AI",
        endpoint="https://ai.example.test/v1",
        model="intent-model",
        secret_ref="vault:///0123456789012345678901234567890123456789",
        enabled=True,
        capabilities=frozenset({"intent"}),
        config={},
    )


@pytest.mark.asyncio
async def test_event_reminder_prompt_is_semantic_only_and_result_preserves_condition() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        system = body["messages"][0]["content"]
        assert "trigger_target_text" in system
        assert "conditional=true" in system
        assert "Never put entity_id, device_id, unique_id" in system
        assert "target_text equal only to what the user wants to be reminded" in system
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "family": "reminder",
                                    "domain": "reminder",
                                    "operation": "create",
                                    "target_text": "check who entered",
                                    "scheduled": False,
                                    "conditional": True,
                                    "condition_payload": {
                                        "kind": "state",
                                        "trigger_target_text": "front door",
                                        "trigger_domain": "binary_sensor",
                                        "to_state": "on",
                                        "once": True,
                                    },
                                    "confidence": 0.98,
                                }
                            )
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(_config(), StaticSecrets(), client=client)
        intent = await provider.understand(
            "remind me to check who entered when the front door opens",
            context=SimpleNamespace(recent_turns=(), active_context=None),
        )

    assert intent.family == "reminder"
    assert intent.canonical_domain == "reminder"
    assert intent.canonical_operation == "create"
    assert intent.target_text == "check who entered"
    assert intent.conditional is True
    assert intent.scheduled is False
    assert intent.condition_payload["trigger_target_text"] == "front door"
    assert "entity_id" not in intent.condition_payload
