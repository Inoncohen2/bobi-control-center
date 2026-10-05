"""Authenticated HTTP ingress for Bobi Next messaging providers.

The endpoint verifies WAHA's HMAC over the exact raw request body before JSON
parsing. Authenticated, semantically ignored events are acknowledged so WAHA
does not retry forever; unavailable Bobi Next runtime returns 503 so a retry can
recover without losing the event.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .secret_vault import EncryptedSecretVault, SecretVaultError
from .setup_store import SetupStore
from .webhook_auth import provider_webhook_secret, verify_waha_webhook_hmac

_MAX_WEBHOOK_BYTES = 2 * 1024 * 1024


def _reply(status: int, *, accepted: bool, reason: str, duplicate: bool = False) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "accepted": accepted,
            "reason": reason,
            "duplicate": duplicate,
        },
    )


def _messaging_runtime(app_state: Any):
    """Resolve the live messaging runtime without keeping a stale startup copy."""

    direct = getattr(app_state, "bobi_next_messaging_runtime", None)
    if direct is not None:
        return direct
    service = getattr(app_state, "next_runtime", None)
    return getattr(service, "messaging", None) if service is not None else None


def create_messaging_webhook_router(
    database_path: str | Path,
    *,
    max_body_bytes: int = _MAX_WEBHOOK_BYTES,
) -> APIRouter:
    setup_path = Path(database_path)
    vault_path = setup_path.with_name("bobi-next-secrets.db")
    vault_key_path = setup_path.with_name("bobi-next-secrets.key")
    max_bytes = max(1024, min(int(max_body_bytes), _MAX_WEBHOOK_BYTES))
    router = APIRouter(prefix="/api/next/webhooks", tags=["bobi-next-webhooks"])

    @router.post("/{provider_key}", response_model=None)
    async def webhook(provider_key: str, request: Request) -> JSONResponse:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > max_bytes:
                    return _reply(413, accepted=False, reason="webhook_body_too_large")
            except ValueError:
                return _reply(400, accepted=False, reason="invalid_content_length")

        raw_body = await request.body()
        if len(raw_body) > max_bytes:
            return _reply(413, accepted=False, reason="webhook_body_too_large")

        setup = SetupStore(setup_path)
        vault = EncryptedSecretVault(vault_path, vault_key_path)
        try:
            provider = setup.get_provider(provider_key)
            if provider is None or not provider.enabled or provider.provider_type != "waha":
                # Do not reveal whether a disabled/private provider exists.
                return _reply(404, accepted=False, reason="webhook_provider_not_found")
            try:
                secret = provider_webhook_secret(provider, vault)
            except SecretVaultError:
                return _reply(503, accepted=False, reason="webhook_auth_unavailable")

            auth = verify_waha_webhook_hmac(
                raw_body,
                signature=request.headers.get("x-webhook-hmac", ""),
                algorithm=request.headers.get("x-webhook-hmac-algorithm", ""),
                secret=secret,
            )
            if not auth.authenticated:
                return _reply(401, accepted=False, reason="webhook_auth_failed")
        finally:
            vault.close()
            setup.close()

        try:
            event = json.loads(raw_body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _reply(400, accepted=False, reason="invalid_webhook_json")
        if not isinstance(event, dict):
            return _reply(400, accepted=False, reason="invalid_webhook_payload")

        runtime = _messaging_runtime(request.app.state)
        if runtime is None:
            return _reply(503, accepted=False, reason="messaging_runtime_unavailable")

        result = runtime.ingest(provider_key, event)
        if result.reason == "provider_not_runtime_enabled":
            return _reply(503, accepted=False, reason=result.reason)
        # Once HMAC-authenticated, ignored/unknown/duplicate events are terminal
        # for this delivery. A 2xx prevents WAHA retry storms.
        return _reply(
            202,
            accepted=result.accepted,
            reason=result.reason,
            duplicate=result.duplicate,
        )

    return router
