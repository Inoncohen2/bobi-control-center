from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.bobi_next.ai_providers import AIProviderStore


def test_ai_provider_round_trip_and_selection_survive_restart(tmp_path: Path) -> None:
    path = tmp_path / "ai.db"
    store = AIProviderStore(path)
    try:
        provider = store.upsert(
            provider_key="primary",
            provider_type="openai-compatible",
            display_name="Primary AI",
            endpoint="https://ai.example/v1",
            model="model-a",
            secret_ref="secret://primary-ai",
            capabilities=frozenset({"intent", "audio", "vision"}),
            config={"temperature": 0.1},
            now_ts=100,
        )
        assert provider.secret_ref == "secret://primary-ai"
        assert provider.capabilities == frozenset({"intent", "audio", "vision"})
        store.select("primary", now_ts=101)
        assert store.active() is not None
        assert store.active().provider_key == "primary"
    finally:
        store.close()

    reopened = AIProviderStore(path)
    try:
        active = reopened.active()
        assert active is not None
        assert active.provider_key == "primary"
        assert active.model == "model-a"
    finally:
        reopened.close()


def test_safe_snapshot_never_exposes_secret_reference_or_private_endpoint(tmp_path: Path) -> None:
    store = AIProviderStore(tmp_path / "ai.db")
    try:
        store.upsert(
            provider_key="p1",
            provider_type="provider",
            display_name="Provider",
            endpoint="http://private-ai.internal/v1",
            secret_ref="secret://do-not-expose",
            capabilities=frozenset({"intent"}),
        )
        store.select("p1")
        snapshot = store.safe_snapshot()
        serialized = repr(snapshot)
        assert "secret://do-not-expose" not in serialized
        assert "private-ai.internal" not in serialized
        assert snapshot["providers"][0]["has_secret_ref"] is True
    finally:
        store.close()


def test_store_persists_secret_reference_not_secret_value(tmp_path: Path) -> None:
    path = tmp_path / "ai.db"
    store = AIProviderStore(path)
    try:
        store.upsert(
            provider_key="p1",
            provider_type="provider",
            display_name="Provider",
            secret_ref="secret://ai-key",
        )
    finally:
        store.close()

    db = sqlite3.connect(path)
    try:
        row = db.execute(
            "SELECT secret_ref, config_json FROM ai_providers WHERE provider_key='p1'"
        ).fetchone()
        assert row is not None
        assert row[0] == "secret://ai-key"
        assert "api_key" not in row[1]
    finally:
        db.close()


def test_plaintext_secrets_are_rejected_even_when_nested(tmp_path: Path) -> None:
    store = AIProviderStore(tmp_path / "ai.db")
    try:
        with pytest.raises(ValueError, match="plaintext_secret_not_allowed"):
            store.upsert(
                provider_key="p1",
                provider_type="provider",
                display_name="Provider",
                config={"transport": {"api_key": "plain-secret"}},
            )
        with pytest.raises(ValueError, match="plaintext_secret_not_allowed"):
            store.upsert(
                provider_key="p2",
                provider_type="provider",
                display_name="Provider 2",
                config={"headers": [{"authorization": "Bearer plain-secret"}]},
            )
    finally:
        store.close()


def test_invalid_capability_is_rejected(tmp_path: Path) -> None:
    store = AIProviderStore(tmp_path / "ai.db")
    try:
        with pytest.raises(ValueError, match="unsupported_ai_capability"):
            store.upsert(
                provider_key="p1",
                provider_type="provider",
                display_name="Provider",
                capabilities=frozenset({"intent", "execute_home_assistant"}),
            )
    finally:
        store.close()


def test_disabled_provider_cannot_be_selected_and_active_disappears_when_disabled(
    tmp_path: Path,
) -> None:
    store = AIProviderStore(tmp_path / "ai.db")
    try:
        store.upsert(
            provider_key="p1",
            provider_type="provider",
            display_name="Provider",
        )
        store.select("p1")
        assert store.active() is not None

        store.upsert(
            provider_key="p1",
            provider_type="provider",
            display_name="Provider",
            enabled=False,
        )
        assert store.active() is None
        with pytest.raises(ValueError, match="ai_provider_disabled"):
            store.select("p1")
    finally:
        store.close()


def test_selection_can_switch_between_enabled_providers(tmp_path: Path) -> None:
    store = AIProviderStore(tmp_path / "ai.db")
    try:
        for key in ("one", "two"):
            store.upsert(
                provider_key=key,
                provider_type="provider",
                display_name=key.title(),
            )
        store.select("one")
        assert store.active().provider_key == "one"
        store.select("two")
        assert store.active().provider_key == "two"
    finally:
        store.close()
