from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet

from app.services.vault import EncryptedVault, VaultCorrupt, VaultNotConfigured


@pytest.fixture(autouse=True)
def configured_test_key(monkeypatch):
    monkeypatch.setenv("BOBI_VAULT_KEY", Fernet.generate_key().decode("ascii"))


def test_key_is_required_and_invalid_key_fails_closed(tmp_path, monkeypatch):
    monkeypatch.delenv("BOBI_VAULT_KEY", raising=False)
    with pytest.raises(VaultNotConfigured):
        EncryptedVault(tmp_path / "vault.enc")
    with pytest.raises(VaultNotConfigured):
        EncryptedVault(tmp_path / "vault.enc", key="not-a-fernet-key")


def test_round_trip_metadata_and_encrypted_at_rest(tmp_path):
    key = Fernet.generate_key()
    path = tmp_path / "vault.enc"
    vault = EncryptedVault(path, key=key)
    vault.put("caldav.main", "super-secret-password", service="CalDAV", note="primary")
    assert vault.get("caldav.main") == "super-secret-password"
    assert vault.list_metadata() == [
        {"name": "caldav.main", "service": "CalDAV", "note": "primary"}
    ]
    assert b"super-secret-password" not in path.read_bytes()
    assert os.stat(path).st_mode & 0o777 == 0o600


def test_no_overwrite_by_default(tmp_path):
    vault = EncryptedVault(tmp_path / "vault.enc")
    vault.put("service.token", "one", service="Example")
    with pytest.raises(FileExistsError):
        vault.put("service.token", "two", service="Example")
    assert vault.get("service.token") == "one"


def test_missing_key_with_existing_vault_fails_closed(tmp_path, monkeypatch):
    path = tmp_path / "vault.enc"
    key = Fernet.generate_key()
    vault = EncryptedVault(path, key=key)
    vault.put("service.token", "secret", service="Example")
    monkeypatch.delenv("BOBI_VAULT_KEY", raising=False)
    with pytest.raises(VaultNotConfigured):
        EncryptedVault(path)


def test_tampering_fails_closed_and_does_not_overwrite(tmp_path):
    path = tmp_path / "vault.enc"
    vault = EncryptedVault(path, key=Fernet.generate_key())
    vault.put("service.token", "secret", service="Example")
    path.write_bytes(path.read_bytes()[:-3] + b"xyz")
    tampered = path.read_bytes()
    with pytest.raises(VaultCorrupt):
        vault.put("other", "value", service="Example")
    assert path.read_bytes() == tampered


@pytest.mark.parametrize("name", ["../outside", "/root", "x\\y", "", " space"])
def test_invalid_names_rejected(tmp_path, name):
    vault = EncryptedVault(tmp_path / "vault.enc")
    with pytest.raises(ValueError):
        vault.put(name, "secret", service="Example")


def test_vault_api_requires_admin_and_never_returns_secret(client):
    response = client.post("/api/bobi/vault/entries", json={
        "name": "test.token", "service": "Test", "value": "DO_NOT_LEAK_123"
    })
    assert response.status_code == 201
    assert "DO_NOT_LEAK_123" not in response.text
    listed = client.get("/api/bobi/vault/entries")
    assert listed.status_code == 200
    assert "DO_NOT_LEAK_123" not in listed.text
    assert listed.json()["entries"][0]["name"] == "test.token"
