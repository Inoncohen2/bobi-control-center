"""Local-first AI provider configuration for Bobi Next.

Credentials never live in this database.  Rows contain only a secret reference
that a runtime secret backend resolves.  The same selected provider can later be
used by intent understanding, audio transcription and vision when supported.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class SecretResolver(Protocol):
    def resolve(self, secret_ref: str) -> str: ...


@dataclass(slots=True, frozen=True)
class AIProviderConfig:
    provider_key: str
    provider_type: str
    display_name: str
    endpoint: str
    model: str
    secret_ref: str
    enabled: bool
    capabilities: frozenset[str]
    config: dict[str, Any]


_ALLOWED_CAPABILITIES = frozenset({"intent", "chat", "audio", "vision", "embeddings"})


class AIProviderStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS ai_providers (
                provider_key TEXT PRIMARY KEY,
                provider_type TEXT NOT NULL,
                display_name TEXT NOT NULL,
                endpoint TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                secret_ref TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                capabilities_json TEXT NOT NULL DEFAULT '[]',
                config_json TEXT NOT NULL DEFAULT '{}',
                created_ts INTEGER NOT NULL,
                updated_ts INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ai_provider_selection (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                provider_key TEXT NOT NULL,
                updated_ts INTEGER NOT NULL,
                FOREIGN KEY(provider_key) REFERENCES ai_providers(provider_key)
            );
            """
        )
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    @staticmethod
    def _decode_object(raw: str) -> dict[str, Any]:
        try:
            value = json.loads(raw or "{}")
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _decode_capabilities(raw: str) -> frozenset[str]:
        try:
            value = json.loads(raw or "[]")
        except (TypeError, ValueError):
            return frozenset()
        if not isinstance(value, list):
            return frozenset()
        return frozenset(str(item) for item in value if str(item) in _ALLOWED_CAPABILITIES)

    def get(self, provider_key: str) -> AIProviderConfig | None:
        row = self._db.execute(
            "SELECT * FROM ai_providers WHERE provider_key=?",
            (provider_key,),
        ).fetchone()
        if row is None:
            return None
        return AIProviderConfig(
            provider_key=str(row["provider_key"]),
            provider_type=str(row["provider_type"]),
            display_name=str(row["display_name"]),
            endpoint=str(row["endpoint"]),
            model=str(row["model"]),
            secret_ref=str(row["secret_ref"]),
            enabled=bool(row["enabled"]),
            capabilities=self._decode_capabilities(str(row["capabilities_json"])),
            config=self._decode_object(str(row["config_json"])),
        )

    def upsert(
        self,
        *,
        provider_key: str,
        provider_type: str,
        display_name: str,
        endpoint: str = "",
        model: str = "",
        secret_ref: str = "",
        enabled: bool = True,
        capabilities: frozenset[str] = frozenset({"intent"}),
        config: dict[str, Any] | None = None,
        now_ts: int | None = None,
    ) -> AIProviderConfig:
        key = provider_key.strip()
        kind = provider_type.strip().casefold()
        name = display_name.strip()
        if not key or not kind or not name:
            raise ValueError("ai_provider_identity_required")
        invalid = set(capabilities) - _ALLOWED_CAPABILITIES
        if invalid:
            raise ValueError("unsupported_ai_capability")
        values = config or {}
        if not isinstance(values, dict):
            raise TypeError("ai_provider_config_must_be_object")
        now = int(now_ts or time.time())
        with self._db:
            self._db.execute(
                """
                INSERT INTO ai_providers(
                    provider_key,provider_type,display_name,endpoint,model,
                    secret_ref,enabled,capabilities_json,config_json,created_ts,updated_ts
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(provider_key) DO UPDATE SET
                    provider_type=excluded.provider_type,
                    display_name=excluded.display_name,
                    endpoint=excluded.endpoint,
                    model=excluded.model,
                    secret_ref=excluded.secret_ref,
                    enabled=excluded.enabled,
                    capabilities_json=excluded.capabilities_json,
                    config_json=excluded.config_json,
                    updated_ts=excluded.updated_ts
                """,
                (
                    key,
                    kind,
                    name,
                    endpoint.strip(),
                    model.strip(),
                    secret_ref.strip(),
                    int(bool(enabled)),
                    json.dumps(sorted(capabilities), separators=(",", ":")),
                    json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    now,
                    now,
                ),
            )
        result = self.get(key)
        if result is None:
            raise RuntimeError("ai_provider_not_persisted")
        return result

    def select(self, provider_key: str, *, now_ts: int | None = None) -> AIProviderConfig:
        provider = self.get(provider_key)
        if provider is None:
            raise KeyError("ai_provider_not_found")
        if not provider.enabled:
            raise ValueError("ai_provider_disabled")
        now = int(now_ts or time.time())
        with self._db:
            self._db.execute(
                """
                INSERT INTO ai_provider_selection(singleton,provider_key,updated_ts)
                VALUES(1,?,?)
                ON CONFLICT(singleton) DO UPDATE SET
                    provider_key=excluded.provider_key,
                    updated_ts=excluded.updated_ts
                """,
                (provider.provider_key, now),
            )
        return provider

    def active(self) -> AIProviderConfig | None:
        row = self._db.execute(
            "SELECT provider_key FROM ai_provider_selection WHERE singleton=1"
        ).fetchone()
        if row is None:
            return None
        provider = self.get(str(row["provider_key"]))
        return provider if provider is not None and provider.enabled else None

    def list_enabled(self) -> tuple[AIProviderConfig, ...]:
        rows = self._db.execute(
            "SELECT provider_key FROM ai_providers WHERE enabled=1 ORDER BY provider_key"
        ).fetchall()
        return tuple(
            provider
            for row in rows
            if (provider := self.get(str(row["provider_key"]))) is not None
        )

    def safe_snapshot(self) -> dict[str, Any]:
        active = self.active()
        return {
            "active_provider": active.provider_key if active else "",
            "providers": [
                {
                    "provider_key": provider.provider_key,
                    "provider_type": provider.provider_type,
                    "display_name": provider.display_name,
                    "endpoint": provider.endpoint,
                    "model": provider.model,
                    "enabled": provider.enabled,
                    "capabilities": sorted(provider.capabilities),
                    "has_secret_ref": bool(provider.secret_ref),
                }
                for provider in self.list_enabled()
            ],
        }
