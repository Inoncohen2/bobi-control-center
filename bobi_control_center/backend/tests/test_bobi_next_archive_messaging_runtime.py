from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.bobi_next.archive_messaging_runtime as archive_runtime_module
from app.bobi_next.archive_messaging_runtime import ArchiveMessagingRuntime
from app.bobi_next.authorization import UserPolicy
from app.bobi_next.media_analyzers import MediaAnalyzerRegistry
from app.bobi_next.pending_approval import PendingApprovalStore
from app.bobi_next.setup_store import MessagingProvider, SetupStore


class FakeHA:
    async def get_state(self, entity_id):
        del entity_id
        return None

    async def call_service(self, domain, service, data):
        del domain, service, data


async def _devices():
    return ()


async def _policy(user_key: str) -> UserPolicy:
    return UserPolicy(user_key)


class DummyUnderstanding:
    async def understand(self, text, *, context):
        del text, context
        raise AssertionError("understanding should not run in this composition test")


@pytest.mark.asyncio
async def test_waha_boundary_injects_archive_capture_into_handler(tmp_path, monkeypatch):
    setup = SetupStore(tmp_path / "setup.db")
    pending = PendingApprovalStore(tmp_path / "pending.db")
    runtime = ArchiveMessagingRuntime(
        data_dir=tmp_path,
        setup=setup,
        ha=FakeHA(),
        list_devices=_devices,
        policy_for=_policy,
        pending_approvals=pending,
    )
    captured = {}

    def fake_handler(**kwargs):
        captured.update(kwargs)

        async def handler(message):
            del message
            return SimpleNamespace(text="ok")

        return handler

    monkeypatch.setattr(archive_runtime_module, "build_conversation_handler", fake_handler)
    provider = MessagingProvider(
        provider_key="waha-main",
        provider_type="waha",
        display_name="WAHA",
        enabled=True,
        endpoint="http://waha:3000",
        session="default",
        engine="GOWS",
        secret_ref="",
        config={},
    )

    try:
        boundary = runtime._waha_boundary(
            provider,
            understanding=DummyUnderstanding(),
            analyzers=MediaAnalyzerRegistry(),
        )
        runtime.boundaries[provider.provider_key] = boundary
        assert captured["archive_capture"] is runtime.archive.capture
        assert captured["media_pipeline"] is not None
        assert boundary.provider == provider
    finally:
        await runtime.aclose()
        pending.close()
        setup.close()


@pytest.mark.asyncio
async def test_archive_runtime_close_is_idempotent(tmp_path):
    setup = SetupStore(tmp_path / "setup.db")
    pending = PendingApprovalStore(tmp_path / "pending.db")
    runtime = ArchiveMessagingRuntime(
        data_dir=tmp_path,
        setup=setup,
        ha=FakeHA(),
        list_devices=_devices,
        policy_for=_policy,
        pending_approvals=pending,
    )
    try:
        assert runtime.archive.capture is not None
        await runtime.aclose()
        await runtime.aclose()
    finally:
        pending.close()
        setup.close()
