from __future__ import annotations

import sqlite3

import pytest

from app.bobi_next.secret_vault import EncryptedSecretVault, SecretVaultError


def test_vault_encrypts_at_rest_and_survives_restart(tmp_path):
    database = tmp_path / "secrets.db"
    key = tmp_path / "secrets.key"
    plaintext = "provider-api-key-that-must-not-appear-in-sqlite"

    vault = EncryptedSecretVault(database, key)
    try:
        secret_ref = vault.put("ai:primary", plaintext, now_ts=100)
        assert secret_ref.startswith("vault:///")
        assert vault.resolve(secret_ref) == plaintext
    finally:
        vault.close()

    assert plaintext.encode() not in database.read_bytes()
    assert key.exists()
    assert key.stat().st_mode & 0o077 == 0

    reopened = EncryptedSecretVault(database, key)
    try:
        assert reopened.resolve(secret_ref) == plaintext
    finally:
        reopened.close()


def test_rotation_keeps_stable_reference_and_replaces_ciphertext(tmp_path):
    vault = EncryptedSecretVault(tmp_path / "secrets.db", tmp_path / "secrets.key")
    try:
        first = vault.put("ai:primary", "old-value", now_ts=100)
        second = vault.put("ai:primary", "new-value", now_ts=101)
        assert first == second
        assert vault.resolve(second) == "new-value"
        assert b"old-value" not in (tmp_path / "secrets.db").read_bytes()
    finally:
        vault.close()


def test_delete_revokes_reference(tmp_path):
    vault = EncryptedSecretVault(tmp_path / "secrets.db", tmp_path / "secrets.key")
    try:
        secret_ref = vault.put("messaging:waha", "secret")
        assert vault.contains(secret_ref) is True
        assert vault.delete(secret_ref) is True
        assert vault.contains(secret_ref) is False
        with pytest.raises(SecretVaultError, match="secret_not_found"):
            vault.resolve(secret_ref)
    finally:
        vault.close()


def test_tampered_ciphertext_fails_closed(tmp_path):
    database = tmp_path / "secrets.db"
    vault = EncryptedSecretVault(database, tmp_path / "secrets.key")
    try:
        secret_ref = vault.put("ai:primary", "secret")
        secret_id = secret_ref.removeprefix("vault:///")
        with sqlite3.connect(database) as db:
            db.execute(
                "UPDATE secrets SET ciphertext=? WHERE secret_id=?",
                (b"tampered", secret_id),
            )
            db.commit()
        with pytest.raises(SecretVaultError, match="secret_decryption_failed"):
            vault.resolve(secret_ref)
    finally:
        vault.close()


def test_invalid_reference_never_reads_arbitrary_secret(tmp_path):
    vault = EncryptedSecretVault(tmp_path / "secrets.db", tmp_path / "secrets.key")
    try:
        for secret_ref in (
            "env://OPENAI_KEY",
            "vault://host/id",
            "vault:///../id",
            "vault:///not-a-valid-id",
        ):
            with pytest.raises(SecretVaultError, match="secret_ref_invalid"):
                vault.resolve(secret_ref)
    finally:
        vault.close()
