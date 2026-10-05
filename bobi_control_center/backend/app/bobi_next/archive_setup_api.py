"""Opt-in archive setup: encrypted integration, read-only handshake, explicit mode.

Connection checks send only ping. They never upload a document or change a cloud
schema. A short-lived proof binds protocol/installation identity to the exact
local integration credential version before selecting cloud storage.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .archive_configuration import (
    ArchiveConfigurationConflict,
    archive_configuration_guard,
    archive_connection_fingerprint,
)
from .integration_store import ExternalIntegration, IntegrationStore
from .secret_vault import EncryptedSecretVault, SecretVaultError
from .setup_store import SetupStore
from .supabase_storage import BobiStorageClient, BobiStorageError

_PROOF_TTL = 300
_SAFE_ERRORS = frozenset(
    {
        "storage_timeout",
        "storage_transport_error",
        "storage_redirect_rejected",
        "storage_unauthorized",
        "storage_unavailable",
        "storage_invalid_json",
        "storage_invalid_response",
    }
)
_CONFIGURATION_ERRORS = frozenset(
    {
        "archive_provider_ambiguous",
        "archive_provider_not_configured",
        "archive_provider_not_enabled",
        "archive_secret_missing",
        "storage_endpoint_invalid",
        "storage_endpoint_https_required",
        "storage_token_invalid",
    }
)
_PROOF_REASONS = _SAFE_ERRORS | frozenset(
    {
        "archive_connection_ready",
        "archive_generic_protocol_required",
        "archive_installation_mismatch",
        "archive_connection_failed",
    }
)


class ArchiveModeInput(BaseModel):
    mode: Literal["local", "cloud"]


def _configuration(path: Path) -> tuple[str, ExternalIntegration, BobiStorageClient, str]:
    setup = SetupStore(path)
    integrations = IntegrationStore(path)
    try:
        installation_id = setup.installation_id()
        items = integrations.list(integration_type="bobi_archive", enabled_only=True)
        if len(items) != 1:
            raise ValueError(
                "archive_provider_ambiguous" if items else "archive_provider_not_configured"
            )
        item = items[0]
        if item.config.get("archive_enabled") is not True:
            raise ValueError("archive_provider_not_enabled")
        if not item.secret_ref:
            raise ValueError("archive_secret_missing")
        vault = EncryptedSecretVault(
            path.with_name("bobi-next-secrets.db"),
            path.with_name("bobi-next-secrets.key"),
        )
        try:
            token = vault.resolve(item.secret_ref)
        finally:
            vault.close()
        client = BobiStorageClient(item.endpoint, token)
        fingerprint = archive_connection_fingerprint(installation_id, item)
        return installation_id, item, client, fingerprint
    finally:
        setup.close()
        integrations.close()


def archive_setup_status(database_path: str | Path, *, now_ts: int | None = None) -> dict:
    path = Path(database_path)
    setup = SetupStore(path)
    integrations = IntegrationStore(path)
    try:
        settings = setup.settings()
        mode = str(settings.get("archive_storage_mode", "local")).strip().lower() or "local"
        items = integrations.list(integration_type="bobi_archive")
        enabled = tuple(i for i in items if i.enabled)
        item = enabled[0] if len(enabled) == 1 else (items[0] if len(items) == 1 else None)
        cloud = {
            "configured": False,
            "ready": False,
            "integration_key": item.integration_key if item else "",
            "endpoint": item.endpoint if item else "",
            "has_secret": bool(item and item.secret_ref),
            "reason": "archive_provider_not_configured",
            "checked_ts": 0,
            "check_fresh": False,
        }
        try:
            _, _, _, fingerprint = _configuration(path)
            cloud["configured"] = True
            proof = settings.get("archive_connection_proof")
            proof = proof if isinstance(proof, dict) else {}
            now = int(time.time()) if now_ts is None else now_ts
            checked = proof.get("checked_ts", 0)
            checked = checked if type(checked) is int else 0
            valid = proof.get("fingerprint") == fingerprint and 0 < checked <= now
            cloud["ready"] = valid and proof.get("ready") is True
            cloud["check_fresh"] = valid and now - checked <= _PROOF_TTL
            cloud["checked_ts"] = checked if proof.get("fingerprint") == fingerprint else 0
            reason = proof.get("reason")
            safe_reason = (
                reason
                if isinstance(reason, str) and reason in _PROOF_REASONS
                else "archive_connection_failed"
            )
            cloud["reason"] = (
                "archive_connection_ready"
                if cloud["ready"]
                else safe_reason
                if valid
                else "archive_connection_not_checked"
            )
        except SecretVaultError:
            cloud["reason"] = "archive_secret_unavailable"
        except ValueError as exc:
            cloud["reason"] = (
                str(exc) if str(exc) in _CONFIGURATION_ERRORS else "archive_connection_failed"
            )
        return {
            "mode": mode,
            "ready": mode == "local" or (mode == "cloud" and cloud["ready"]),
            "cloud": cloud,
        }
    finally:
        setup.close()
        integrations.close()


def create_archive_setup_router(database_path: str | Path) -> APIRouter:
    path = Path(database_path)
    router = APIRouter(prefix="/api/next/setup/archive", tags=["bobi-next-setup"])

    @router.get("")
    async def status() -> dict:
        return archive_setup_status(path)

    @router.post("/check")
    async def check() -> dict:
        try:
            installation, _, client, fingerprint = _configuration(path)
        except (ValueError, SecretVaultError):
            return archive_setup_status(path)
        reason = "archive_connection_ready"
        try:
            result = await client.ping()
            if (
                result.get("archive_protocol") != "bobi-archive-v1"
                or result.get("archive_enabled") is not True
            ):
                reason = "archive_generic_protocol_required"
            elif result.get("installation_id") != installation:
                reason = "archive_installation_mismatch"
        except BobiStorageError as exc:
            # Provider errors may contain secrets. Return only known local codes.
            reason = str(exc) if str(exc) in _SAFE_ERRORS else "archive_connection_failed"
        try:
            with archive_configuration_guard(path):
                _, _, _, current = _configuration(path)
                if current != fingerprint:
                    raise ArchiveConfigurationConflict("archive_configuration_changed")
                setup = SetupStore(path)
                try:
                    setup.update_settings(
                        {
                            "archive_connection_proof": {
                                "fingerprint": fingerprint,
                                "ready": reason == "archive_connection_ready",
                                "reason": reason,
                                "checked_ts": int(time.time()),
                            }
                        }
                    )
                finally:
                    setup.close()
        except (ValueError, SecretVaultError) as exc:
            raise HTTPException(status_code=409, detail="archive_configuration_changed") from exc
        return archive_setup_status(path)

    @router.put("")
    async def select_mode(body: ArchiveModeInput) -> dict:
        try:
            with archive_configuration_guard(path):
                snapshot = archive_setup_status(path)
                if body.mode == "cloud" and not (
                    snapshot["cloud"]["ready"] and snapshot["cloud"]["check_fresh"]
                ):
                    raise ArchiveConfigurationConflict("archive_connection_check_required")
                setup = SetupStore(path)
                try:
                    values = {"archive_storage_mode": body.mode}
                    if body.mode == "cloud":
                        values["archive_connection_check_required"] = True
                    setup.update_settings(values)
                finally:
                    setup.close()
        except ArchiveConfigurationConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return archive_setup_status(path)

    return router
