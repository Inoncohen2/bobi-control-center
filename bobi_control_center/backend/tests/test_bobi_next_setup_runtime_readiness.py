from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.bobi_next.ai_providers import AIProviderStore
from app.bobi_next.setup_api import create_setup_router
from app.bobi_next.setup_store import SetupStore


def _client(tmp_path):
    database_path = tmp_path / "setup.db"
    app = FastAPI()
    app.include_router(create_setup_router(database_path))
    return database_path, TestClient(app)


def test_provider_update_with_blank_endpoint_and_secret_preserves_existing_values(tmp_path):
    database_path, client = _client(tmp_path)
    first = client.post(
        "/api/next/setup/providers",
        json={
            "provider_key": "whatsapp",
            "provider_type": "waha",
            "display_name": "WhatsApp",
            "endpoint": "http://waha.internal:3000",
            "session": "default",
            "engine": "GOWS",
            "secret_value": "private-provider-key",
        },
    )
    assert first.status_code == 200
    assert first.json()["has_secret_ref"] is True

    updated = client.post(
        "/api/next/setup/providers",
        json={
            "provider_key": "whatsapp",
            "provider_type": "waha",
            "display_name": "WhatsApp",
            "endpoint": "",
            "session": "default",
            "engine": "GOWS",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["has_secret_ref"] is True

    store = SetupStore(database_path)
    try:
        provider = store.get_provider("whatsapp")
        assert provider is not None
        assert provider.endpoint == "http://waha.internal:3000"
        assert provider.secret_ref
        assert "private-provider-key" not in provider.secret_ref
    finally:
        store.close()


def test_ai_update_with_blank_endpoint_and_secret_preserves_existing_values(tmp_path):
    database_path, client = _client(tmp_path)
    first = client.post(
        "/api/next/setup/ai/providers",
        json={
            "provider_key": "ai:primary",
            "provider_type": "openai-compatible",
            "display_name": "Primary AI",
            "endpoint": "https://ai.internal/v1",
            "model": "model-a",
            "secret_value": "private-ai-key",
            "capabilities": ["intent"],
        },
    )
    assert first.status_code == 200
    assert first.json()["has_secret_ref"] is True

    updated = client.post(
        "/api/next/setup/ai/providers",
        json={
            "provider_key": "ai:primary",
            "provider_type": "openai-compatible",
            "display_name": "Primary AI",
            "endpoint": "",
            "model": "model-b",
            "capabilities": ["intent"],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["has_secret_ref"] is True

    ai = AIProviderStore(database_path.with_name("bobi-next-ai.db"))
    try:
        provider = ai.get("ai:primary")
        assert provider is not None
        assert provider.endpoint == "https://ai.internal/v1"
        assert provider.model == "model-b"
        assert provider.secret_ref
        assert "private-ai-key" not in provider.secret_ref
    finally:
        ai.close()


def test_complete_rejects_enabled_but_unrunnable_waha_after_ai_is_ready(tmp_path):
    _, client = _client(tmp_path)
    client.post(
        "/api/next/setup/providers",
        json={
            "provider_key": "whatsapp",
            "provider_type": "waha",
            "display_name": "WhatsApp",
        },
    )
    ai = client.post(
        "/api/next/setup/ai/providers",
        json={
            "provider_key": "ai:primary",
            "provider_type": "openai-compatible",
            "display_name": "Primary AI",
            "endpoint": "https://ai.internal/v1",
            "model": "model-a",
            "capabilities": ["intent"],
        },
    )
    assert ai.status_code == 200
    assert client.post("/api/next/setup/ai/providers/ai:primary/select").status_code == 200

    user = client.post(
        "/api/next/setup/users",
        json={"display_name": "Owner", "role": "owner", "user_key": "owner"},
    )
    assert user.status_code == 200
    identity = client.post(
        "/api/next/setup/identities",
        json={
            "provider_key": "whatsapp",
            "external_id": "private-sender",
            "user_key": "owner",
        },
    )
    assert identity.status_code == 200

    status = client.get("/api/next/setup/status").json()
    assert status["messaging_configured"] is False
    assert status["ai"]["configured"] is True
    assert "messaging_provider_config" in status["setup"]["missing_steps"]

    complete = client.post("/api/next/setup/complete")
    assert complete.status_code == 409
    assert "messaging_provider_config" in complete.json()["detail"]
