from __future__ import annotations

import hashlib
import hmac

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.bobi_next.secret_vault import EncryptedSecretVault
from app.bobi_next.setup_store import SetupStore
from app.bobi_next.waha_ingest import IngestResult
from app.bobi_next.webhook_api import create_messaging_webhook_router


def _signature(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()


def _configured_app(tmp_path, *, with_runtime=True):
    setup_path = tmp_path / "bobi-next-setup.db"
    secret = "webhook-test-key"
    vault = EncryptedSecretVault(
        tmp_path / "bobi-next-secrets.db",
        tmp_path / "bobi-next-secrets.key",
    )
    setup = SetupStore(setup_path)
    try:
        ref = vault.put("webhook-hmac:waha:primary", secret, now_ts=1)
        setup.upsert_provider(
            provider_key="waha:primary",
            provider_type="waha",
            display_name="WhatsApp",
            endpoint="http://waha:3000",
            session="default",
            engine="GOWS",
            config={"webhook_hmac_ref": ref},
            now_ts=1,
        )
    finally:
        setup.close()
        vault.close()

    class Runtime:
        def __init__(self):
            self.events = []
            self.result = IngestResult(True, "accepted", "m1", "u1")

        def ingest(self, provider_key, event):
            self.events.append((provider_key, event))
            return self.result

    app = FastAPI()
    app.include_router(create_messaging_webhook_router(setup_path, max_body_bytes=4096))
    runtime = Runtime()
    if with_runtime:
        app.state.bobi_next_messaging_runtime = runtime
    return TestClient(app), runtime, secret


def _headers(body: bytes, secret: str):
    return {
        "Content-Type": "application/json",
        "X-Webhook-Hmac": _signature(body, secret),
        "X-Webhook-Hmac-Algorithm": "sha512",
    }


def test_valid_signed_webhook_reaches_runtime_only_after_auth(tmp_path):
    client, runtime, secret = _configured_app(tmp_path)
    body = b'{"event":"message","session":"default","payload":{"id":"m1"}}'
    response = client.post(
        "/api/next/webhooks/waha:primary",
        content=body,
        headers=_headers(body, secret),
    )
    assert response.status_code == 202
    assert response.json()["accepted"] is True
    assert runtime.events == [
        (
            "waha:primary",
            {"event": "message", "session": "default", "payload": {"id": "m1"}},
        )
    ]


def test_bad_signature_is_rejected_before_json_parse_or_runtime(tmp_path):
    client, runtime, secret = _configured_app(tmp_path)
    body = b"not-json"
    headers = _headers(body, secret)
    headers["X-Webhook-Hmac"] = "00" * 64
    response = client.post(
        "/api/next/webhooks/waha:primary",
        content=body,
        headers=headers,
    )
    assert response.status_code == 401
    assert response.json()["reason"] == "webhook_auth_failed"
    assert runtime.events == []


def test_signed_invalid_json_is_rejected_after_auth(tmp_path):
    client, runtime, secret = _configured_app(tmp_path)
    body = b"not-json"
    response = client.post(
        "/api/next/webhooks/waha:primary",
        content=body,
        headers=_headers(body, secret),
    )
    assert response.status_code == 400
    assert response.json()["reason"] == "invalid_webhook_json"
    assert runtime.events == []


def test_duplicate_is_acknowledged_without_retry_status(tmp_path):
    client, runtime, secret = _configured_app(tmp_path)
    runtime.result = IngestResult(False, "duplicate_message", "m1", "u1", duplicate=True)
    body = b'{"event":"message","session":"default","payload":{"id":"m1"}}'
    response = client.post(
        "/api/next/webhooks/waha:primary",
        content=body,
        headers=_headers(body, secret),
    )
    assert response.status_code == 202
    assert response.json() == {
        "accepted": False,
        "reason": "duplicate_message",
        "duplicate": True,
    }


def test_runtime_unavailable_returns_retryable_503(tmp_path):
    client, runtime, secret = _configured_app(tmp_path, with_runtime=False)
    del runtime
    body = b'{"event":"message","session":"default","payload":{"id":"m1"}}'
    response = client.post(
        "/api/next/webhooks/waha:primary",
        content=body,
        headers=_headers(body, secret),
    )
    assert response.status_code == 503
    assert response.json()["reason"] == "messaging_runtime_unavailable"


def test_unknown_provider_does_not_reveal_configuration(tmp_path):
    client, runtime, secret = _configured_app(tmp_path)
    del runtime
    body = b"{}"
    response = client.post(
        "/api/next/webhooks/waha:unknown",
        content=body,
        headers=_headers(body, secret),
    )
    assert response.status_code == 404
    assert response.json()["reason"] == "webhook_provider_not_found"


def test_body_limit_is_enforced_before_authentication(tmp_path):
    client, runtime, secret = _configured_app(tmp_path)
    del runtime, secret
    body = b"x" * 5000
    response = client.post(
        "/api/next/webhooks/waha:primary",
        content=body,
        headers={
            "X-Webhook-Hmac": "00" * 64,
            "X-Webhook-Hmac-Algorithm": "sha512",
        },
    )
    assert response.status_code == 413
    assert response.json()["reason"] == "webhook_body_too_large"
