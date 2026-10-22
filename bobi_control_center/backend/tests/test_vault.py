from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet

from app.services.vault import (
    EncryptedVault,
    VaultCorrupt,
    VaultNotConfigured,
)


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
    vault.put("caldav.main", "super-secret-password", service="CalDAV", note="primary account")

    assert vault.get("caldav.main") == "super-secret-password"
    assert vault.list_metadata() == [
        {"name": "caldav.main", "service": "CalDAV", "note": "primary account"}
    ]
    assert b"super-secret-password" not in path.read_bytes()
    assert os.stat(path).st_mode & 0o777 == 0o600


def test_delete_and_missing_secret(tmp_path):
    vault = EncryptedVault(tmp_path / "vault.enc", key=Fernet.generate_key())
    assert vault.get("missing") is None
    assert vault.delete("missing") is False
    vault.put("service.token", "abc123", service="Example")
    assert vault.delete("service.token") is True
    assert vault.get("service.token") is None


def test_tampering_fails_closed_without_overwrite(tmp_path):
    path = tmp_path / "vault.enc"
    vault = EncryptedVault(path, key=Fernet.generate_key())
    vault.put("service.token", "abc123", service="Example")
    original = path.read_bytes()
    path.write_bytes(original[:-3] + b"xyz")
    tampered = path.read_bytes()
    with pytest.raises(VaultCorrupt):
        vault.put("another", "value", service="Example")
    assert path.read_bytes() == tampered


@pytest.mark.parametrize("name", ["../outside", "/root", "x\\y", "", " space"])
def test_invalid_names_rejected(tmp_path, name):
    vault = EncryptedVault(tmp_path / "vault.enc", key=Fernet.generate_key())
    with pytest.raises(ValueError):
        vault.put(name, "secret", service="Example")
