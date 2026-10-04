"""HTTP contract for the Bobi Next setup wizard.

The router is intentionally not registered by the production Control Center
yet. Each request opens its own short-lived SetupStore connection against the
same local SQLite file, avoiding cross-thread connection sharing while SQLite
WAL serializes concurrent writers.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .authorization import RiskLevel, UserPolicy
from .setup_store import BobiUser, MessagingProvider, SetupStore, policy_to_dict


class ProviderInput(BaseModel):
    provider_key: str = Field(min_length=1, max_length=128)
    provider_type: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    enabled: bool = True
    endpoint: str = Field(default="", max_length=1000)
    session: str = Field(default="", max_length=128)
    engine: str = Field(default="", max_length=64)
    secret_ref: str = Field(default="", max_length=512)
    config: dict[str, Any] = Field(default_factory=dict)


class UserInput(BaseModel):
    display_name: str = Field(min_length=1, max_length=128)
    role: Literal["owner", "admin", "member", "guest"] = "member"
    user_key: str = Field(default="", max_length=128)
    enabled: bool = True


class IdentityInput(BaseModel):
    provider_key: str = Field(min_length=1, max_length=128)
    external_id: str = Field(min_length=1, max_length=512)
    user_key: str = Field(min_length=1, max_length=128)
    identity_label: str = Field(default="", max_length=128)


class PolicyInput(BaseModel):
    allowed_capabilities: list[str] = Field(default_factory=lambda: ["*"])
    denied_capabilities: list[str] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=lambda: ["*"])
    denied_actions: list[str] = Field(default_factory=list)
    max_without_approval: Literal[10, 20, 30, 40] = 20
    can_approve: bool = False


def _provider_view(provider: MessagingProvider) -> dict[str, Any]:
    return {
        "provider_key": provider.provider_key,
        "provider_type": provider.provider_type,
        "display_name": provider.display_name,
        "enabled": provider.enabled,
        "session": provider.session,
        "engine": provider.engine,
        "has_secret_ref": bool(provider.secret_ref),
    }


def _user_view(user: BobiUser) -> dict[str, Any]:
    return {
        "user_key": user.user_key,
        "display_name": user.display_name,
        "role": user.role,
        "enabled": user.enabled,
        "policy": policy_to_dict(user.policy),
    }


@contextmanager
def _request_store(database_path: Path):
    store = SetupStore(database_path)
    try:
        yield store
    finally:
        store.close()


def create_setup_router(database_path: str | Path) -> APIRouter:
    path = Path(database_path)
    router = APIRouter(prefix="/api/next/setup", tags=["bobi-next-setup"])

    @router.get("/status")
    async def status() -> dict[str, Any]:
        with _request_store(path) as store:
            return store.safe_snapshot()

    @router.post("/providers")
    async def upsert_provider(body: ProviderInput) -> dict[str, Any]:
        with _request_store(path) as store:
            try:
                provider = store.upsert_provider(**body.model_dump())
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return _provider_view(provider)

    @router.post("/users")
    async def create_user(body: UserInput) -> dict[str, Any]:
        with _request_store(path) as store:
            try:
                user = store.create_user(**body.model_dump())
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            return _user_view(user)

    @router.put("/users/{user_key}/policy")
    async def update_policy(user_key: str, body: PolicyInput) -> dict[str, Any]:
        policy = UserPolicy(
            user_key=user_key,
            allowed_capabilities=frozenset(body.allowed_capabilities),
            denied_capabilities=frozenset(body.denied_capabilities),
            allowed_domains=frozenset(body.allowed_domains),
            denied_actions=frozenset(body.denied_actions),
            max_without_approval=RiskLevel(body.max_without_approval),
            can_approve=body.can_approve,
        )
        with _request_store(path) as store:
            try:
                user = store.update_user_policy(user_key, policy)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="user_not_found") from exc
            return _user_view(user)

    @router.post("/identities")
    async def link_identity(body: IdentityInput) -> dict[str, Any]:
        with _request_store(path) as store:
            try:
                link = store.link_identity(**body.model_dump())
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            return {
                "provider_key": link.provider_key,
                "user_key": link.user_key,
                "identity_label": link.identity_label,
            }

    @router.post("/complete")
    async def complete() -> dict[str, Any]:
        with _request_store(path) as store:
            try:
                store.mark_completed()
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            return store.safe_snapshot()

    return router
