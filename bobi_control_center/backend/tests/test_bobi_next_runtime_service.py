from __future__ import annotations

from pathlib import Path

import pytest

from app.bobi_next.authorization import RiskLevel
from app.bobi_next.runtime_service import BobiNextRuntimeService
from app.config import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(adapter="mock", data_dir=tmp_path)


@pytest.mark.asyncio
async def test_runtime_refuses_to_start_without_supervisor_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    service = BobiNextRuntimeService(_settings(tmp_path))
    try:
        status = await service.start_if_ready()
        assert status.started is False
        assert status.reason == "missing_supervisor_token"
        assert service.task is None
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_runtime_refuses_incomplete_setup_before_network_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "test-supervisor-token")
    service = BobiNextRuntimeService(_settings(tmp_path))
    try:
        status = await service.start_if_ready()
        assert status.started is False
        assert status.reason == "setup_not_completed"
        assert service.discovery is None
        assert service.native is None
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_runtime_policy_provider_denies_unknown_and_disabled_users(
    tmp_path: Path,
) -> None:
    service = BobiNextRuntimeService(_settings(tmp_path))
    try:
        unknown = await service.policy_for("missing-user")
        assert unknown.allowed_capabilities == frozenset()
        assert unknown.allowed_domains == frozenset()
        assert unknown.can_approve is False
        assert unknown.max_without_approval == RiskLevel.LOW

        user = service.setup.create_user(
            display_name="Disabled",
            role="admin",
            enabled=False,
            user_key="disabled-user",
        )
        assert "*" in user.policy.allowed_capabilities
        disabled = await service.policy_for("disabled-user")
        assert disabled.allowed_capabilities == frozenset()
        assert disabled.allowed_domains == frozenset()
        assert disabled.can_approve is False
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_runtime_policy_provider_uses_enabled_setup_policy(tmp_path: Path) -> None:
    service = BobiNextRuntimeService(_settings(tmp_path))
    try:
        user = service.setup.create_user(
            display_name="Owner",
            role="owner",
            user_key="owner-user",
        )
        policy = await service.policy_for("owner-user")
        assert policy == user.policy
        assert policy.can_approve is True
    finally:
        await service.aclose()
