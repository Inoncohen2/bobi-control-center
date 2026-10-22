from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.services.vault import EncryptedVault, VaultCorrupt, VaultNotConfigured


def test_missing_or_invalid_key_fails_closed(tmp_path, monkeypatch):
    monkeypatch.delenv("BOBI_VAULT_KEY", raising=False)
    with pytest.raises(VaultNotConfigured):
        EncryptedVault(tmp_path / "vault.enc")
    with pytest.raises(VaultNotConfigured):
        EncryptedVault(tmp_path / "vault.enc", key="not-a-fernet-key")


def test_encryption_at_rest_metadata_and_round_trip(tmp_path):
    key = Fernet.generate_key()
    path = tmp_path / "vault.enc"
    vault = EncryptedVault(path, key=key)
    vault.put("caldav.main", "secret-password", service="CalDAV", note="primary")
    assert vault.get("caldav.main") == "secret-password"
    assert vault.list_metadata() == [
        {"name": "caldav.main", "service": "CalDAV", "note": "primary"}
    ]
    assert b"secret-password" not in path.read_bytes()
    assert path.stat().st_mode & 0o777 == 0o600


def test_no_overwrite_by_default(tmp_path):
    vault = EncryptedVault(tmp_path / "vault.enc", key=Fernet.generate_key())
    vault.put("service.token", "one", service="Example")
    with pytest.raises(FileExistsError):
        vault.put("service.token", "two", service="Example")
    assert vault.get("service.token") == "one"


def test_tampering_fails_closed_and_does_not_overwrite(tmp_path):
    path = tmp_path / "vault.enc"
    vault = EncryptedVault(path, key=Fernet.generate_key())
    vault.put("service.token", "secret", service="Example")
    path.write_bytes(path.read_bytes()[:-3] + b"xyz")
    tampered = path.read_bytes()
    with pytest.raises(VaultCorrupt):
        vault.put("other", "value", service="Example")
    assert path.read_bytes() == tampered


@pytest.mark.parametrize("name", ["../outside", "/root", "x\\\\y", "", " space"])
def test_invalid_names_rejected(tmp_path, name):
    vault = EncryptedVault(tmp_path / "vault.enc", key=Fernet.generate_key())
    with pytest.raises(ValueError):
        vault.put(name, "secret", service="Example")


def test_vault_api_never_returns_secret(client, monkeypatch, mock_settings):
    monkeypatch.setenv("BOBI_VAULT_KEY", Fernet.generate_key().decode("ascii"))
    response = client.post(
        "/api/bobi/vault/entries",
        json={"name": "test.token", "service": "Test", "value": "DO_NOT_LEAK_123"},
    )
    assert response.status_code == 201
    assert "DO_NOT_LEAK_123" not in response.text
    listed = client.get("/api/bobi/vault/entries")
    assert listed.status_code == 200
    assert "DO_NOT_LEAK_123" not in listed.text
    assert listed.json()["entries"][0]["name"] == "test.token"
