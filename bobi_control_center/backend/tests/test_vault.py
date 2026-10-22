from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.services.vault import EncryptedVault, VaultCorrupt, VaultNotConfigured


def test_key_is_created_once_and_round_trip_metadata(tmp_path, monkeypatch):
    monkeypatch.delenv("BOBI_VAULT_KEY", raising=False)
    path = tmp_path / "vault.enc"
    vault = EncryptedVault(path)
    key_path = tmp_path / ".bobi-vault.key"
    assert key_path.exists()
    assert os.stat(key_path).st_mode & 0o777 == 0o600
    vault.put("caldav.main", "secret-password", service="CalDAV", note="primary")
    assert vault.get("caldav.main") == "secret-password"
    assert vault.list_metadata() == [{"name": "caldav.main", "service": "CalDAV", "note": "primary"}]
    assert b"secret-password" not in path.read_bytes()
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert EncryptedVault(path).get("caldav.main") == "secret-password"


def test_no_overwrite_by_default(tmp_path):
    vault = EncryptedVault(tmp_path / "vault.enc")
    vault.put("service.token", "one", service="Example")
    with pytest.raises(FileExistsError):
        vault.put("service.token", "two", service="Example")
    assert vault.get("service.token") == "one"


def test_missing_key_with_existing_vault_fails_closed(tmp_path):
    path = tmp_path / "vault.enc"
    vault = EncryptedVault(path)
    vault.put("service.token", "secret", service="Example")
    (tmp_path / ".bobi-vault.key").unlink()
    with pytest.raises(VaultNotConfigured):
        EncryptedVault(path)


def test_tampering_fails_closed_and_does_not_overwrite(tmp_path):
    path = tmp_path / "vault.enc"
    vault = EncryptedVault(path)
    vault.put("service.token", "secret", service="Example")
    path.write_bytes(path.read_bytes()[:-3] + b"xyz")
    tampered = path.read_bytes()
    with pytest.raises(VaultCorrupt):
        vault.put("other", "value", service="Example")
    assert path.read_bytes() == tampered


@pytest.mark.parametrize("name", ["../outside", "/root", "x\\\\y", "", " space"])
def test_invalid_names_rejected(tmp_path, name):
    vault = EncryptedVault(tmp_path / "vault.enc")
    with pytest.raises(ValueError):
        vault.put(name, "secret", service="Example")


def test_vault_api_requires_admin_and_never_returns_secret(client, monkeypatch, mock_settings):
    # The default request path is HA Ingress in tests (owner).
    monkeypatch.setattr(mock_settings, "data_dir", mock_settings.data_dir)
    response = client.post("/api/bobi/vault/entries", json={
        "name": "test.token", "service": "Test", "value": "DO_NOT_LEAK_123"
    })
    assert response.status_code == 201
    assert "DO_NOT_LEAK_123" not in response.text
    listed = client.get("/api/bobi/vault/entries")
    assert listed.status_code == 200
    assert "DO_NOT_LEAK_123" not in listed.text
    assert listed.json()["entries"][0]["name"] == "test.token"
