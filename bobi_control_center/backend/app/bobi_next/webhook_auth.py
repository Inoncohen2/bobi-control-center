"""Authentication boundary for Bobi Next messaging webhooks.

WAHA supports HMAC-SHA512 signatures over the exact raw POST body. Bobi verifies
that signature before parsing JSON or touching the durable inbox. Webhook HMAC
keys are independent from WAHA API credentials and live only in the encrypted
local secret vault.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from .secret_vault import EncryptedSecretVault, SecretVaultError
from .setup_store import MessagingProvider

WEBHOOK_HMAC_REF_KEY = "webhook_hmac_ref"
WAHA_HMAC_ALGORITHM = "sha512"
_SIGNATURE_HEX_LENGTH = hashlib.sha512().digest_size * 2


@dataclass(slots=True, frozen=True)
class WebhookAuthResult:
    authenticated: bool
    reason: str


def provider_webhook_secret(
    provider: MessagingProvider,
    vault: EncryptedSecretVault,
) -> str:
    if provider.provider_type != "waha":
        raise SecretVaultError("webhook_provider_not_waha")
    secret_ref = str(provider.config.get(WEBHOOK_HMAC_REF_KEY) or "").strip()
    if not secret_ref:
        raise SecretVaultError("webhook_hmac_not_configured")
    secret = vault.resolve(secret_ref)
    if not secret:
        raise SecretVaultError("webhook_hmac_empty")
    return secret


def verify_waha_webhook_hmac(
    raw_body: bytes,
    *,
    signature: str,
    algorithm: str,
    secret: str,
) -> WebhookAuthResult:
    if not isinstance(raw_body, bytes):
        return WebhookAuthResult(False, "invalid_raw_body")
    if str(algorithm or "").strip().casefold() != WAHA_HMAC_ALGORITHM:
        return WebhookAuthResult(False, "unsupported_hmac_algorithm")

    supplied = str(signature or "").strip().casefold()
    if len(supplied) != _SIGNATURE_HEX_LENGTH:
        return WebhookAuthResult(False, "invalid_hmac_signature")
    if any(character not in "0123456789abcdef" for character in supplied):
        return WebhookAuthResult(False, "invalid_hmac_signature")
    if not secret:
        return WebhookAuthResult(False, "missing_hmac_secret")

    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        digestmod=hashlib.sha512,
    ).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        return WebhookAuthResult(False, "hmac_mismatch")
    return WebhookAuthResult(True, "authenticated")
