from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.bobi_next.ai_providers import AIProviderStore
from app.bobi_next.secret_vault import EncryptedSecretVault
from app.bobi_next.setup_api import create_setup_router
from app.bobi_next.setup_store import SetupStore


def _client(tmp_path):
    database_path = tmp_path / "setup.db"
    app = FastAPI()
    app.include_router(create_setup_router(database_path))
    return database_path, TestClient(app)


def _vault(tmp_path):
    return EncryptedSecretVault(
        tmp_path / "bobi-next-secrets.db",
        tmp_path / "bobi-next-secrets.key",
    )


def test_ai_secret_value_is_encrypted_and_only_reference_is_configured(tmp_path):
    _, client = _client(tmp_path)
    plaintext = "ai-key-must-never-be-returned-or-stored-plain"
    response = client.post(
        "/api/next/setup/ai/providers",
        json={
            "provider_key": "ai:primary",
            "provider_type": "openai-compatible",
            "display_name": "Primary AI",
            "model": "model-a",
            "secret_value": plaintext,
            "capabilities": ["intent", "audio", "vision"],
        },
    )
    assert response.status_code == 200
    assert response.json()["has_secret_ref"] is True
    assert plaintext not in response.text

    store = AIProviderStore(tmp_path / "bobi-next-ai.db")
    try:
        provider = store.get("ai:primary")
        assert provider is not None
        assert provider.secret_ref.startswith("vault:///")
        assert plaintext.encode() not in (tmp_path / "bobi-next-ai.db").read_bytes()
    finally:
        store.close()

    vault = _vault(tmp_path)
    try:
        assert vault.resolve(provider.secret_ref) == plaintext
    finally:
        vault.close()
    assert plaintext.encode() not in (tmp_path / "bobi-next-secrets.db").read_bytes()


def test_ai_secret_rotation_keeps_same_reference(tmp_path):
    _, client = _client(tmp_path)
    base = {
        "provider_key": "ai:primary",
        "provider_type": "openai-compatible",
        "display_name": "Primary AI",
        "capabilities": ["intent"],
    }
    first = client.post(
        "/api/next/setup/ai/providers",
        json={**base, "secret_value": "old-secret"},
    )
    assert first.status_code == 200

    store = AIProviderStore(tmp_path / "bobi-next-ai.db")
    try:
        first_ref = store.get("ai:primary").secret_ref
    finally:
        store.close()

    second = client.post(
        "/api/next/setup/ai/providers",
        json={**base, "secret_value": "new-secret"},
    )
    assert second.status_code == 200

    store = AIProviderStore(tmp_path / "bobi-next-ai.db")
    try:
        second_ref = store.get("ai:primary").secret_ref
    finally:
        store.close()
    assert first_ref == second_ref

    vault = _vault(tmp_path)
    try:
        assert vault.resolve(second_ref) == "new-secret"
    finally:
        vault.close()


def test_messaging_provider_secret_value_is_encrypted(tmp_path):
    setup_path, client = _client(tmp_path)
    plaintext = "waha-api-key"
    response = client.post(
        "/api/next/setup/providers",
        json={
            "provider_key": "waha:primary",
            "provider_type": "waha",
            "display_name": "WhatsApp",
            "session": "default",
            "secret_value": plaintext,
        },
    )
    assert response.status_code == 200
    assert response.json()["has_secret_ref"] is True
    assert plaintext not in response.text

    store = SetupStore(setup_path)
    try:
        provider = store.get_provider("waha:primary")
        assert provider is not None
        secret_ref = provider.secret_ref
        assert secret_ref.startswith("vault:///")
        assert plaintext.encode() not in setup_path.read_bytes()
    finally:
        store.close()

    vault = _vault(tmp_path)
    try:
        assert vault.resolve(secret_ref) == plaintext
    finally:
        vault.close()


def test_secretstr_repr_never_leaks_plaintext_in_validation_error(tmp_path):
    _, client = _client(tmp_path)
    plaintext = "do-not-leak-this-value"
    response = client.post(
        "/api/next/setup/ai/providers",
        json={
            "provider_key": "ai:bad",
            "provider_type": "provider",
            "display_name": "Bad",
            "secret_value": plaintext,
            "capabilities": ["not-a-real-capability"],
        },
    )
    assert response.status_code == 422
    assert plaintext not in response.text
