from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.bobi_next.integration_api import create_integration_setup_router
from app.bobi_next.integration_store import IntegrationStore
from app.bobi_next.secret_vault import EncryptedSecretVault


def _app(path) -> FastAPI:
    app = FastAPI()
    app.include_router(create_integration_setup_router(path))
    return app


def test_integration_store_snapshot_never_exposes_secret_ref(tmp_path) -> None:
    path = tmp_path / "setup.db"
    store = IntegrationStore(path)
    store.upsert(
        integration_key="cloud",
        integration_type="bobi_storage",
        display_name="Cloud storage",
        endpoint="https://example.supabase.co/functions/v1/bobi-storage",
        secret_ref="vault:///deadbeef",
        config={"private": "metadata"},
    )

    snapshot = store.safe_snapshot()

    assert snapshot == [
        {
            "integration_key": "cloud",
            "integration_type": "bobi_storage",
            "display_name": "Cloud storage",
            "enabled": True,
            "endpoint": "https://example.supabase.co/functions/v1/bobi-storage",
            "has_secret_ref": True,
        }
    ]
    assert "secret_ref" not in snapshot[0]
    assert "config" not in snapshot[0]
    store.close()


def test_setup_integration_encrypts_secret_and_does_not_echo_it(tmp_path) -> None:
    path = tmp_path / "setup.db"
    client = TestClient(_app(path))
    token = "s" * 40

    response = client.post(
        "/api/next/setup/integrations",
        json={
            "integration_key": "supabase",
            "integration_type": "bobi_storage",
            "display_name": "Bobi cloud",
            "endpoint": "https://example.supabase.co/functions/v1/bobi-storage",
            "secret_value": token,
            "config": {"profile_mode": "legacy_external_id"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["has_secret_ref"] is True
    assert token not in response.text
    assert "secret_ref" not in payload

    store = IntegrationStore(path)
    item = store.get("supabase")
    assert item is not None
    assert item.secret_ref.startswith("vault:///")
    assert token not in path.read_bytes().decode("utf-8", errors="ignore")

    vault = EncryptedSecretVault(
        tmp_path / "bobi-next-secrets.db",
        tmp_path / "bobi-next-secrets.key",
    )
    assert vault.resolve(item.secret_ref) == token
    vault.close()
    store.close()


def test_integration_update_without_new_secret_preserves_existing_ref(tmp_path) -> None:
    path = tmp_path / "setup.db"
    client = TestClient(_app(path))
    initial = {
        "integration_key": "supabase",
        "integration_type": "bobi_storage",
        "display_name": "Bobi cloud",
        "endpoint": "https://example.supabase.co/functions/v1/bobi-storage",
        "secret_value": "a" * 40,
    }
    assert client.post("/api/next/setup/integrations", json=initial).status_code == 200

    store = IntegrationStore(path)
    before = store.get("supabase")
    assert before is not None
    original_ref = before.secret_ref
    store.close()

    response = client.post(
        "/api/next/setup/integrations",
        json={
            "integration_key": "supabase",
            "integration_type": "bobi_storage",
            "display_name": "Updated cloud",
            "endpoint": "https://example.supabase.co/functions/v1/bobi-storage",
            "enabled": False,
        },
    )
    assert response.status_code == 200

    store = IntegrationStore(path)
    after = store.get("supabase")
    assert after is not None
    assert after.secret_ref == original_ref
    assert after.display_name == "Updated cloud"
    assert after.enabled is False
    store.close()


def test_setup_rejects_insecure_remote_storage_endpoint(tmp_path) -> None:
    client = TestClient(_app(tmp_path / "setup.db"))
    response = client.post(
        "/api/next/setup/integrations",
        json={
            "integration_key": "bad",
            "integration_type": "bobi_storage",
            "display_name": "Bad",
            "endpoint": "http://example.com/functions/v1/bobi-storage",
            "secret_value": "x" * 40,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "storage_endpoint_https_required"


def test_setup_requires_secret_on_first_configuration(tmp_path) -> None:
    client = TestClient(_app(tmp_path / "setup.db"))
    response = client.post(
        "/api/next/setup/integrations",
        json={
            "integration_key": "supabase",
            "integration_type": "bobi_storage",
            "display_name": "Bobi cloud",
            "endpoint": "https://example.supabase.co/functions/v1/bobi-storage",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "integration_secret_required"


def test_setup_accepts_separate_archive_integration_and_encrypts_token(tmp_path) -> None:
    path = tmp_path / "setup.db"
    client = TestClient(_app(path))
    response = client.post(
        "/api/next/setup/integrations",
        json={
            "integration_key": "archive",
            "integration_type": "bobi_archive",
            "display_name": "Private archive",
            "endpoint": "https://example.supabase.co/functions/v1/bobi-archive-next",
            "secret_value": "a" * 40,
            "config": {"archive_enabled": True},
        },
    )
    assert response.status_code == 200
    assert response.json()["integration_type"] == "bobi_archive"
    assert "a" * 40 not in response.text
    assert "a" * 40 not in path.read_bytes().decode("utf-8", errors="ignore")


@pytest.mark.parametrize("integration_type", ["bobi_storage", "bobi_archive"])
def test_endpoint_change_requires_explicit_secret_and_keeps_existing_config(
    tmp_path, integration_type,
) -> None:
    path = tmp_path / "setup.db"
    client = TestClient(_app(path))
    initial = {
        "integration_key": "cloud", "integration_type": integration_type,
        "display_name": "Cloud", "endpoint": "https://first.example/functions/v1/storage",
        "secret_value": "s" * 40,
    }
    assert client.post("/api/next/setup/integrations", json=initial).status_code == 200
    changed = {**initial, "endpoint": "https://second.example/functions/v1/storage"}
    changed.pop("secret_value")
    response = client.post("/api/next/setup/integrations", json=changed)
    assert response.status_code == 400
    assert response.json()["detail"] == "integration_endpoint_change_requires_secret"
    snapshot = client.get("/api/next/setup/integrations").json()
    assert snapshot[0]["endpoint"] == initial["endpoint"]
    changed["secret_value"] = "n" * 40
    assert client.post("/api/next/setup/integrations", json=changed).status_code == 200


def test_archive_cannot_retype_existing_voucher_integration_even_with_new_secret(tmp_path) -> None:
    client = TestClient(_app(tmp_path / "setup.db"))
    body = {
        "integration_key": "vouchers", "integration_type": "bobi_storage",
        "display_name": "Vouchers", "endpoint": "https://example.supabase.co/functions/v1/bobi-storage",
        "secret_value": "s" * 40,
    }
    assert client.post("/api/next/setup/integrations", json=body).status_code == 200
    response = client.post("/api/next/setup/integrations", json={
        **body, "integration_type": "bobi_archive", "secret_value": "a" * 40,
    })
    assert response.status_code == 400
    assert response.json()["detail"] == "integration_type_change_requires_new_key"
    assert client.get("/api/next/setup/integrations").json()[0]["integration_type"] == "bobi_storage"


@pytest.mark.parametrize("token", ["a" * 513, "a" * 39 + " ", "א" * 40])
def test_archive_token_must_match_edge_header_contract(tmp_path, token) -> None:
    client = TestClient(_app(tmp_path / "setup.db"))
    response = client.post("/api/next/setup/integrations", json={
        "integration_key": "archive", "integration_type": "bobi_archive", "display_name": "Archive",
        "endpoint": "https://example.supabase.co/functions/v1/bobi-archive-next", "secret_value": token,
    })
    assert response.status_code == 400
    assert response.json()["detail"] == "storage_token_invalid"


@pytest.mark.parametrize("stale_read", [False, True])
def test_rejected_config_cannot_replace_existing_encrypted_token(
    tmp_path, monkeypatch, stale_read,
) -> None:
    path = tmp_path / "setup.db"
    client = TestClient(_app(path))
    body = {
        "integration_key": "vouchers", "integration_type": "bobi_storage",
        "display_name": "Vouchers", "endpoint": "https://example.supabase.co/functions/v1/bobi-storage",
        "secret_value": "s" * 40,
    }
    assert client.post("/api/next/setup/integrations", json=body).status_code == 200
    store = IntegrationStore(path)
    before = store.get("vouchers")
    assert before is not None
    store.close()
    if stale_read:
        original_get = IntegrationStore.get
        seen = False

        def stale_get(self, key):
            nonlocal seen
            if not seen:
                seen = True
                return None  # Another writer populated this key after a read.
            return original_get(self, key)

        monkeypatch.setattr(IntegrationStore, "get", stale_get)
        changed = {**body, "integration_type": "bobi_archive", "secret_value": "a" * 40}
    else:
        changed = {**body, "display_name": " ", "secret_value": "a" * 40}
    response = client.post("/api/next/setup/integrations", json=changed)
    assert response.status_code == 400
    store = IntegrationStore(path)
    after = store.get("vouchers")
    assert after is not None
    assert after.integration_type == before.integration_type
    assert after.secret_ref == before.secret_ref
    vault = EncryptedSecretVault(
        tmp_path / "bobi-next-secrets.db", tmp_path / "bobi-next-secrets.key",
    )
    assert vault.resolve(after.secret_ref) == "s" * 40
    vault.close()
    store.close()
