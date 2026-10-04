from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.bobi_next.secret_vault import EncryptedSecretVault
from app.bobi_next.setup_api import create_setup_router
from app.bobi_next.setup_store import SetupStore
from app.bobi_next.webhook_auth import WEBHOOK_HMAC_REF_KEY


def _client(tmp_path):
    setup_path = tmp_path / "setup.db"
    app = FastAPI()
    app.include_router(create_setup_router(setup_path))
    return setup_path, TestClient(app)


def test_waha_provider_gets_server_generated_webhook_hmac(tmp_path):
    setup_path, client = _client(tmp_path)
    response = client.post(
        "/api/next/setup/providers",
        json={
            "provider_key": "waha:primary",
            "provider_type": "waha",
            "display_name": "WhatsApp",
            "endpoint": "http://waha:3000",
            "session": "default",
        },
    )
    assert response.status_code == 200
    assert response.json()["webhook_hmac_ready"] is True
    assert WEBHOOK_HMAC_REF_KEY not in response.text

    store = SetupStore(setup_path)
    try:
        provider = store.get_provider("waha:primary")
        assert provider is not None
        secret_ref = str(provider.config[WEBHOOK_HMAC_REF_KEY])
        assert secret_ref.startswith("vault:///")
    finally:
        store.close()

    vault = EncryptedSecretVault(
        tmp_path / "bobi-next-secrets.db",
        tmp_path / "bobi-next-secrets.key",
    )
    try:
        secret = vault.resolve(secret_ref)
        assert len(secret) >= 48
        assert secret not in response.text
        assert secret.encode() not in setup_path.read_bytes()
    finally:
        vault.close()


def test_client_cannot_replace_bobi_owned_webhook_reference(tmp_path):
    setup_path, client = _client(tmp_path)
    initial = client.post(
        "/api/next/setup/providers",
        json={
            "provider_key": "waha:primary",
            "provider_type": "waha",
            "display_name": "WhatsApp",
        },
    )
    assert initial.status_code == 200

    store = SetupStore(setup_path)
    try:
        before = store.get_provider("waha:primary")
        assert before is not None
        original_ref = before.config[WEBHOOK_HMAC_REF_KEY]
    finally:
        store.close()

    injected_ref = "vault:///0000000000000000000000000000000000000000"
    updated = client.post(
        "/api/next/setup/providers",
        json={
            "provider_key": "waha:primary",
            "provider_type": "waha",
            "display_name": "WhatsApp Updated",
            "config": {WEBHOOK_HMAC_REF_KEY: injected_ref, "safe_option": True},
        },
    )
    assert updated.status_code == 200

    store = SetupStore(setup_path)
    try:
        after = store.get_provider("waha:primary")
        assert after is not None
        assert after.config[WEBHOOK_HMAC_REF_KEY] == original_ref
        assert after.config[WEBHOOK_HMAC_REF_KEY] != injected_ref
        assert after.config["safe_option"] is True
    finally:
        store.close()


def test_non_waha_provider_does_not_receive_webhook_hmac(tmp_path):
    setup_path, client = _client(tmp_path)
    response = client.post(
        "/api/next/setup/providers",
        json={
            "provider_key": "other:primary",
            "provider_type": "other",
            "display_name": "Other",
        },
    )
    assert response.status_code == 200
    assert response.json()["webhook_hmac_ready"] is False

    store = SetupStore(setup_path)
    try:
        provider = store.get_provider("other:primary")
        assert provider is not None
        assert WEBHOOK_HMAC_REF_KEY not in provider.config
    finally:
        store.close()
