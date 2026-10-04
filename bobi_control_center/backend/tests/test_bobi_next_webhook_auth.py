from __future__ import annotations

import hashlib
import hmac

import pytest

from app.bobi_next.secret_vault import EncryptedSecretVault, SecretVaultError
from app.bobi_next.setup_store import MessagingProvider
from app.bobi_next.webhook_auth import (
    WEBHOOK_HMAC_REF_KEY,
    provider_webhook_secret,
    verify_waha_webhook_hmac,
)


def _provider(secret_ref: str) -> MessagingProvider:
    return MessagingProvider(
        provider_key="waha:primary",
        provider_type="waha",
        display_name="WhatsApp",
        enabled=True,
        endpoint="http://waha:3000",
        session="default",
        engine="GOWS",
        secret_ref="",
        config={WEBHOOK_HMAC_REF_KEY: secret_ref},
        created_ts=1,
        updated_ts=1,
    )


def _signature(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()


def test_valid_waha_hmac_authenticates_exact_raw_body():
    body = b'{"event":"message","session":"default"}'
    secret = "webhook-key"
    result = verify_waha_webhook_hmac(
        body,
        signature=_signature(body, secret),
        algorithm="sha512",
        secret=secret,
    )
    assert result.authenticated is True
    assert result.reason == "authenticated"


def test_body_change_or_wrong_secret_fails_closed():
    body = b'{"event":"message"}'
    signature = _signature(body, "right-key")
    changed = verify_waha_webhook_hmac(
        body + b" ",
        signature=signature,
        algorithm="sha512",
        secret="right-key",
    )
    wrong_secret = verify_waha_webhook_hmac(
        body,
        signature=signature,
        algorithm="sha512",
        secret="wrong-key",
    )
    assert changed.authenticated is False
    assert changed.reason == "hmac_mismatch"
    assert wrong_secret.authenticated is False
    assert wrong_secret.reason == "hmac_mismatch"


@pytest.mark.parametrize(
    ("signature", "algorithm", "reason"),
    [
        ("00" * 64, "sha256", "unsupported_hmac_algorithm"),
        ("abc", "sha512", "invalid_hmac_signature"),
        ("zz" * 64, "sha512", "invalid_hmac_signature"),
    ],
)
def test_algorithm_and_signature_format_are_strict(signature, algorithm, reason):
    result = verify_waha_webhook_hmac(
        b"{}",
        signature=signature,
        algorithm=algorithm,
        secret="key",
    )
    assert result.authenticated is False
    assert result.reason == reason


def test_provider_webhook_secret_resolves_only_from_vault(tmp_path):
    vault = EncryptedSecretVault(tmp_path / "secrets.db", tmp_path / "secrets.key")
    try:
        ref = vault.put("webhook-hmac:waha:primary", "real-webhook-key")
        assert provider_webhook_secret(_provider(ref), vault) == "real-webhook-key"
    finally:
        vault.close()


def test_provider_without_hmac_ref_fails_closed(tmp_path):
    vault = EncryptedSecretVault(tmp_path / "secrets.db", tmp_path / "secrets.key")
    try:
        with pytest.raises(SecretVaultError, match="webhook_hmac_not_configured"):
            provider_webhook_secret(_provider(""), vault)
    finally:
        vault.close()
