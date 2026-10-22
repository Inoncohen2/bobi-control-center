"""Admin-only API for Bobi Guardian's encrypted credential vault.

Responses deliberately never contain secret values. Secrets are accepted only
by this protected backend route and are never written to logs.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.auth import actor_for
from app.services.roles import Role, rank
from app.services.vault import EncryptedVault, VaultError

router = APIRouter(prefix="/api/bobi/vault", tags=["vault"])


class VaultEntryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    service: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=240)
    value: SecretStr = Field(min_length=1, max_length=8192)


def _vault(request: Request) -> EncryptedVault:
    settings = request.app.state.settings
    return EncryptedVault(settings.data_dir / "bobi-vault.enc")


def _require_admin(request: Request) -> None:
    actor = actor_for(request)
    if rank(actor.role) < rank(Role.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required.",
        )


@router.get("/status")
async def vault_status(request: Request) -> dict[str, object]:
    _require_admin(request)
    try:
        vault = _vault(request)
        entries = vault.list_metadata()
        return {"configured": True, "locked": False, "count": len(entries)}
    except VaultError as exc:
        return {"configured": False, "locked": True, "count": 0, "message": str(exc)}


@router.get("/entries")
async def list_entries(request: Request) -> dict[str, object]:
    _require_admin(request)
    try:
        return {"entries": _vault(request).list_metadata()}
    except VaultError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/entries", status_code=status.HTTP_201_CREATED)
async def create_entry(body: VaultEntryInput, request: Request) -> dict[str, object]:
    _require_admin(request)
    try:
        _vault(request).put(
            body.name, body.value.get_secret_value(), service=body.service, note=body.note
        )
    except FileExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail="Entry already exists; overwrite is disabled.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except VaultError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"created": True, "name": body.name, "service": body.service, "note": body.note}


@router.delete("/entries/{name}")
async def delete_entry(name: str, request: Request) -> dict[str, object]:
    _require_admin(request)
    # Deletion is available only to an owner, not the external admin session.
    if actor_for(request).role != Role.OWNER:
        raise HTTPException(status_code=403, detail="Owner role required for deletion.")
    try:
        deleted = _vault(request).delete(name)
    except (ValueError, VaultError) as exc:
        raise HTTPException(status_code=503, detail="Vault operation failed safely.") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Entry not found.")
    return {"deleted": True, "name": name}
