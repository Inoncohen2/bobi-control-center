"""Optional external-integration configuration for Bobi Next.

This store shares Bobi Next's setup database but keeps external integrations
separate from messaging providers. Credentials are never stored here: only an
opaque ``vault://`` reference from :mod:`secret_vault` is persisted.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True, frozen=True)
class ExternalIntegration:
    integration_key: str
    integration_type: str
    display_name: str
    enabled: bool
    endpoint: str
    secret_ref: str
    config: dict[str, Any]


def _json_object(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


class IntegrationStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    def close(self) -> None:
        self._db.close()

    def _migrate(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS external_integrations (
                integration_key TEXT PRIMARY KEY,
                integration_type TEXT NOT NULL,
                display_name TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                endpoint TEXT NOT NULL DEFAULT '',
                secret_ref TEXT NOT NULL DEFAULT '',
                config_json TEXT NOT NULL DEFAULT '{}',
                created_ts INTEGER NOT NULL,
                updated_ts INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_external_integrations_type
                ON external_integrations(integration_type, enabled, integration_key);
            """
        )
        self._db.commit()

    @staticmethod
    def _from_row(row: sqlite3.Row | None) -> ExternalIntegration | None:
        if row is None:
            return None
        return ExternalIntegration(
            integration_key=str(row["integration_key"]),
            integration_type=str(row["integration_type"]),
            display_name=str(row["display_name"]),
            enabled=bool(row["enabled"]),
            endpoint=str(row["endpoint"]),
            secret_ref=str(row["secret_ref"]),
            config=_json_object(str(row["config_json"])),
        )

    def upsert(
        self,
        *,
        integration_key: str,
        integration_type: str,
        display_name: str,
        enabled: bool = True,
        endpoint: str = "",
        secret_ref: str = "",
        config: dict[str, Any] | None = None,
        now_ts: int | None = None,
    ) -> ExternalIntegration:
        key = str(integration_key or "").strip()
        kind = str(integration_type or "").strip().lower()
        name = str(display_name or "").strip()
        if not key or not kind:
            raise ValueError("integration_identity_required")
        if not name:
            raise ValueError("integration_display_name_required")
        config_value = config or {}
        if not isinstance(config_value, dict):
            raise TypeError("integration_config_must_be_object")
        encoded = json.dumps(
            config_value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        now = int(now_ts or time.time())
        with self._db:
            self._db.execute(
                """
                INSERT INTO external_integrations(
                    integration_key,integration_type,display_name,enabled,endpoint,
                    secret_ref,config_json,created_ts,updated_ts
                ) VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(integration_key) DO UPDATE SET
                    integration_type=excluded.integration_type,
                    display_name=excluded.display_name,
                    enabled=excluded.enabled,
                    endpoint=excluded.endpoint,
                    secret_ref=excluded.secret_ref,
                    config_json=excluded.config_json,
                    updated_ts=excluded.updated_ts
                """,
                (
                    key,
                    kind,
                    name,
                    int(bool(enabled)),
                    str(endpoint or "").strip(),
                    str(secret_ref or "").strip(),
                    encoded,
                    now,
                    now,
                ),
            )
        result = self.get(key)
        if result is None:
            raise RuntimeError("integration_not_persisted")
        return result

    def get(self, integration_key: str) -> ExternalIntegration | None:
        row = self._db.execute(
            "SELECT * FROM external_integrations WHERE integration_key=?",
            (str(integration_key or "").strip(),),
        ).fetchone()
        return self._from_row(row)

    def list(
        self,
        *,
        integration_type: str = "",
        enabled_only: bool = False,
    ) -> tuple[ExternalIntegration, ...]:
        clauses: list[str] = []
        values: list[object] = []
        if integration_type.strip():
            clauses.append("integration_type=?")
            values.append(integration_type.strip().lower())
        if enabled_only:
            clauses.append("enabled=1")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._db.execute(
            f"SELECT * FROM external_integrations {where} ORDER BY integration_key",
            tuple(values),
        ).fetchall()
        return tuple(item for row in rows if (item := self._from_row(row)) is not None)

    def set_enabled(self, integration_key: str, enabled: bool) -> ExternalIntegration:
        key = str(integration_key or "").strip()
        with self._db:
            result = self._db.execute(
                "UPDATE external_integrations SET enabled=?, updated_ts=? WHERE integration_key=?",
                (int(bool(enabled)), int(time.time()), key),
            )
        if result.rowcount != 1:
            raise KeyError("integration_not_found")
        updated = self.get(key)
        if updated is None:
            raise RuntimeError("integration_disappeared")
        return updated

    def safe_snapshot(self) -> list[dict[str, Any]]:
        """Return setup-safe metadata without secret refs or config internals."""

        return [
            {
                "integration_key": item.integration_key,
                "integration_type": item.integration_type,
                "display_name": item.display_name,
                "enabled": item.enabled,
                "endpoint": item.endpoint,
                "has_secret_ref": bool(item.secret_ref),
            }
            for item in self.list()
        ]
