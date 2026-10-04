"""HTTP contract for the Bobi Next setup wizard.

The router is intentionally not registered by the production Control Center
unless Bobi Next setup is explicitly enabled. Each request opens short-lived
SQLite connections, avoiding cross-thread sharing while WAL serializes writers.
Credentials are referenced, never stored in the setup databases themselves.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .ai_providers import AIProviderConfig, AIProviderStore
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


AICapability = Literal["intent", "chat", "audio", "vision", "embeddings"]


class AIProviderInput(BaseModel):
    provider_key: str = Field(min_length=1, max_length=128)
    provider_type: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    endpoint: str = Field(default="", max_length=1000)
    model: str = Field(default="", max_length=256)
    secret_ref: str = Field(default="", max_length=512)
    enabled: bool = True
    capabilities: list[AICapability] = Field(default_factory=lambda: ["intent"])
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


def _ai_provider_view(provider: AIProviderConfig) -> dict[str, Any]:
    return {
        "provider_key": provider.provider_key,
        "provider_type": provider.provider_type,
        "display_name": provider.display_name,
        "model": provider.model,
        "enabled": provider.enabled,
        "capabilities": sorted(provider.capabilities),
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


@contextmanager
def _ai_store(database_path: Path):
    store = AIProviderStore(database_path)
    try:
        yield store
    finally:
        store.close()


def _combined_snapshot(setup: SetupStore, ai: AIProviderStore) -> dict[str, Any]:
    snapshot = setup.safe_snapshot()
    ai_snapshot = ai.safe_snapshot()
    active = ai.active()
    ai_ready = bool(active and "intent" in active.capabilities)
    missing = list(snapshot["setup"]["missing_steps"])
    if not ai_ready:
        missing.append("ai_provider")
    snapshot["setup"]["ready"] = bool(snapshot["setup"]["ready"] and ai_ready)
    snapshot["setup"]["missing_steps"] = missing
    snapshot["ai"] = ai_snapshot
    return snapshot


def create_setup_router(database_path: str | Path) -> APIRouter:
    path = Path(database_path)
    ai_path = path.with_name("bobi-next-ai.db")
    router = APIRouter(prefix="/api/next/setup", tags=["bobi-next-setup"])

    @router.get("/status")
    async def status() -> dict[str, Any]:
        with _request_store(path) as store, _ai_store(ai_path) as ai:
            return _combined_snapshot(store, ai)

    @router.post("/providers")
    async def upsert_provider(body: ProviderInput) -> dict[str, Any]:
        with _request_store(path) as store:
            try:
                provider = store.upsert_provider(**body.model_dump())
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return _provider_view(provider)

    @router.post("/ai/providers")
    async def upsert_ai_provider(body: AIProviderInput) -> dict[str, Any]:
        values = body.model_dump()
        values["capabilities"] = frozenset(values["capabilities"])
        with _ai_store(ai_path) as ai:
            try:
                provider = ai.upsert(**values)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return _ai_provider_view(provider)

    @router.post("/ai/providers/{provider_key}/select")
    async def select_ai_provider(provider_key: str) -> dict[str, Any]:
        with _ai_store(ai_path) as ai:
            try:
                provider = ai.select(provider_key)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="ai_provider_not_found") from exc
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            return _ai_provider_view(provider)

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
        with _request_store(path) as store, _ai_store(ai_path) as ai:
            snapshot = _combined_snapshot(store, ai)
            if not snapshot["setup"]["ready"]:
                missing = ",".join(snapshot["setup"]["missing_steps"])
                raise HTTPException(status_code=409, detail=f"setup_incomplete:{missing}")
            try:
                store.mark_completed()
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            return _combined_snapshot(store, ai)

    return router
