"""Setup API for optional Bobi Next integrations.

Secrets are accepted only as ``SecretStr`` and encrypted immediately into Bobi's
local secret vault. API responses never contain the secret value or vault ref.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, SecretStr

from .integration_store import ExternalIntegration, IntegrationStore
from .secret_vault import EncryptedSecretVault, SecretVaultError
from .supabase_storage import BobiStorageClient


class IntegrationInput(BaseModel):
    integration_key: str = Field(min_length=1, max_length=128)
    integration_type: Literal["bobi_storage", "bobi_archive"]
    display_name: str = Field(min_length=1, max_length=128)
    enabled: bool = True
    endpoint: str = Field(min_length=1, max_length=1000)
    secret_value: SecretStr | None = None
    config: dict[str, Any] = Field(default_factory=dict)


def _view(item: ExternalIntegration) -> dict[str, Any]:
    return {
        "integration_key": item.integration_key,
        "integration_type": item.integration_type,
        "display_name": item.display_name,
        "enabled": item.enabled,
        "endpoint": item.endpoint,
        "has_secret_ref": bool(item.secret_ref),
    }


@contextmanager
def _store(path: Path):
    store = IntegrationStore(path)
    try:
        yield store
    finally:
        store.close()


@contextmanager
def _vault(database_path: Path, key_path: Path):
    vault = EncryptedSecretVault(database_path, key_path)
    try:
        yield vault
    finally:
        vault.close()


def _validate_bobi_storage_endpoint(endpoint: str) -> str:
    # Reuse the exact transport validator without persisting a fake credential.
    # A fixed placeholder meeting the minimum length never leaves this process.
    client = BobiStorageClient(endpoint, "x" * 32)
    return client.endpoint


def create_integration_setup_router(database_path: str | Path) -> APIRouter:
    path = Path(database_path)
    vault_path = path.with_name("bobi-next-secrets.db")
    vault_key_path = path.with_name("bobi-next-secrets.key")
    router = APIRouter(prefix="/api/next/setup/integrations", tags=["bobi-next-setup"])

    @router.get("")
    async def list_integrations() -> list[dict[str, Any]]:
        with _store(path) as store:
            return store.safe_snapshot()

    @router.post("")
    async def upsert_integration(body: IntegrationInput) -> dict[str, Any]:
        try:
            endpoint = _validate_bobi_storage_endpoint(body.endpoint)
            with _store(path) as store:
                existing = store.get(body.integration_key)
                if existing is not None and existing.integration_type != body.integration_type:
                    raise ValueError("integration_type_change_requires_new_key")
                if (
                    existing is not None
                    and existing.endpoint != endpoint
                    and body.secret_value is None
                ):
                    raise ValueError("integration_endpoint_change_requires_secret")
                secret_ref = existing.secret_ref if existing is not None else ""
            if body.secret_value is not None:
                secret = body.secret_value.get_secret_value()
                if len(secret) < 32:
                    raise ValueError("storage_token_invalid")
                if body.integration_type == "bobi_archive" and (
                    len(secret) > 512 or any(not "!" <= character <= "~" for character in secret)
                ):
                    raise ValueError("storage_token_invalid")
                with _vault(vault_path, vault_key_path) as vault:
                    secret_ref = vault.put(
                        # Each configuration points to an immutable credential
                        # version. A rejected/racing update cannot replace the
                        # token referenced by the previously committed config.
                        f"integration:{body.integration_key}:{uuid4().hex}",
                        secret,
                    )
            if not secret_ref:
                raise ValueError("integration_secret_required")

            with _store(path) as store:
                item = store.upsert(
                    integration_key=body.integration_key,
                    integration_type=body.integration_type,
                    display_name=body.display_name,
                    enabled=body.enabled,
                    endpoint=endpoint,
                    secret_ref=secret_ref,
                    config=body.config,
                )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except SecretVaultError as exc:
            raise HTTPException(status_code=500, detail="secret_vault_unavailable") from exc
        return _view(item)

    @router.post("/{integration_key}/enabled/{enabled}")
    async def set_enabled(integration_key: str, enabled: bool) -> dict[str, Any]:
        with _store(path) as store:
            try:
                item = store.set_enabled(integration_key, enabled)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="integration_not_found") from exc
        return _view(item)

    return router
