"""Local-first durable memory for Bobi Next.

The database replaces Bobi-owned input_text/input_boolean/timer/todo storage.
It never becomes the source of truth for a device's live state; live state is
always read back from Home Assistant.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

from .models import DeviceRecord


SCHEMA_VERSION = 1


class BobiMemory:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def close(self) -> None:
        self._db.close()

    def _migrate(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS devices (
                bobi_id TEXT PRIMARY KEY,
                stable_key TEXT NOT NULL UNIQUE,
                ha_device_id TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL DEFAULT '',
                area_id TEXT NOT NULL DEFAULT '',
                area_name TEXT NOT NULL DEFAULT '',
                capabilities_json TEXT NOT NULL DEFAULT '[]',
                last_seen_ts INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS aliases (
                bobi_id TEXT NOT NULL,
                alias TEXT NOT NULL COLLATE NOCASE,
                source TEXT NOT NULL DEFAULT 'discovery',
                weight REAL NOT NULL DEFAULT 1.0,
                created_ts INTEGER NOT NULL,
                PRIMARY KEY (bobi_id, alias),
                FOREIGN KEY (bobi_id) REFERENCES devices(bobi_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS conversation_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_key TEXT NOT NULL,
                message_id TEXT NOT NULL DEFAULT '',
                direction TEXT NOT NULL,
                text TEXT NOT NULL,
                semantic_json TEXT NOT NULL DEFAULT '{}',
                created_ts INTEGER NOT NULL,
                UNIQUE(user_key, message_id) ON CONFLICT IGNORE
            );
            CREATE INDEX IF NOT EXISTS ix_conversation_recent
                ON conversation_turns(user_key, created_ts DESC);
            CREATE TABLE IF NOT EXISTS active_context (
                user_key TEXT PRIMARY KEY,
                bobi_device_id TEXT NOT NULL DEFAULT '',
                area_id TEXT NOT NULL DEFAULT '',
                object_type TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                updated_ts INTEGER NOT NULL,
                expires_ts INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS request_ledger (
                request_id TEXT PRIMARY KEY,
                user_key TEXT NOT NULL,
                state TEXT NOT NULL,
                owner_token TEXT NOT NULL DEFAULT '',
                input_text TEXT NOT NULL DEFAULT '',
                terminal_kind TEXT NOT NULL DEFAULT '',
                outbound_message_id TEXT NOT NULL DEFAULT '',
                created_ts INTEGER NOT NULL,
                updated_ts INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_ts INTEGER NOT NULL
            );
            """
        )
        self._db.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)",
            (str(SCHEMA_VERSION),),
        )
        self._db.commit()

    def sync_devices(self, devices: Iterable[DeviceRecord], now_ts: int | None = None) -> None:
        now = int(now_ts or time.time())
        with self._db:
            for device in devices:
                self._db.execute(
                    """
                    INSERT INTO devices(
                        bobi_id, stable_key, ha_device_id, name, area_id,
                        area_name, capabilities_json, last_seen_ts
                    ) VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(bobi_id) DO UPDATE SET
                        stable_key=excluded.stable_key,
                        ha_device_id=excluded.ha_device_id,
                        name=excluded.name,
                        area_id=excluded.area_id,
                        area_name=excluded.area_name,
                        capabilities_json=excluded.capabilities_json,
                        last_seen_ts=excluded.last_seen_ts
                    """,
                    (
                        device.bobi_id,
                        device.stable_key,
                        device.ha_device_id,
                        device.name,
                        device.area_id,
                        device.area_name,
                        json.dumps(sorted(device.capabilities), ensure_ascii=False),
                        now,
                    ),
                )
                for alias in device.aliases:
                    self._db.execute(
                        """
                        INSERT INTO aliases(bobi_id, alias, source, weight, created_ts)
                        VALUES(?,?,?,?,?)
                        ON CONFLICT(bobi_id, alias) DO NOTHING
                        """,
                        (device.bobi_id, alias, "discovery", 1.0, now),
                    )

    def add_alias(self, bobi_id: str, alias: str, *, source: str = "learned", weight: float = 1.2) -> None:
        alias = alias.strip()
        if not alias:
            return
        with self._db:
            self._db.execute(
                """
                INSERT INTO aliases(bobi_id, alias, source, weight, created_ts)
                VALUES(?,?,?,?,?)
                ON CONFLICT(bobi_id, alias) DO UPDATE SET
                    source=excluded.source, weight=MAX(aliases.weight, excluded.weight)
                """,
                (bobi_id, alias, source, float(weight), int(time.time())),
            )

    def aliases_for(self, bobi_id: str) -> tuple[tuple[str, float], ...]:
        rows = self._db.execute(
            "SELECT alias, weight FROM aliases WHERE bobi_id=? ORDER BY weight DESC, alias",
            (bobi_id,),
        ).fetchall()
        return tuple((row["alias"], float(row["weight"])) for row in rows)

    def store_turn(
        self,
        user_key: str,
        text: str,
        *,
        direction: str,
        message_id: str = "",
        semantic: dict[str, Any] | None = None,
        created_ts: int | None = None,
    ) -> None:
        with self._db:
            self._db.execute(
                """
                INSERT OR IGNORE INTO conversation_turns(
                    user_key,message_id,direction,text,semantic_json,created_ts
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    user_key,
                    message_id,
                    direction,
                    text[:4000],
                    json.dumps(semantic or {}, ensure_ascii=False),
                    int(created_ts or time.time()),
                ),
            )

    def recent_turns(self, user_key: str, limit: int = 12) -> tuple[dict[str, Any], ...]:
        rows = self._db.execute(
            """
            SELECT message_id,direction,text,semantic_json,created_ts
            FROM conversation_turns WHERE user_key=?
            ORDER BY created_ts DESC, id DESC LIMIT ?
            """,
            (user_key, int(limit)),
        ).fetchall()
        return tuple(
            {
                "message_id": row["message_id"],
                "direction": row["direction"],
                "text": row["text"],
                "semantic": json.loads(row["semantic_json"] or "{}"),
                "created_ts": row["created_ts"],
            }
            for row in reversed(rows)
        )

    def set_active_context(
        self,
        user_key: str,
        *,
        bobi_device_id: str = "",
        area_id: str = "",
        object_type: str = "",
        payload: dict[str, Any] | None = None,
        ttl_seconds: int = 300,
        now_ts: int | None = None,
    ) -> None:
        now = int(now_ts or time.time())
        with self._db:
            self._db.execute(
                """
                INSERT INTO active_context(
                    user_key,bobi_device_id,area_id,object_type,payload_json,updated_ts,expires_ts
                ) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(user_key) DO UPDATE SET
                    bobi_device_id=excluded.bobi_device_id,
                    area_id=excluded.area_id,
                    object_type=excluded.object_type,
                    payload_json=excluded.payload_json,
                    updated_ts=excluded.updated_ts,
                    expires_ts=excluded.expires_ts
                """,
                (
                    user_key,
                    bobi_device_id,
                    area_id,
                    object_type,
                    json.dumps(payload or {}, ensure_ascii=False),
                    now,
                    now + max(1, int(ttl_seconds)),
                ),
            )

    def get_active_context(self, user_key: str, now_ts: int | None = None) -> dict[str, Any] | None:
        now = int(now_ts or time.time())
        row = self._db.execute(
            "SELECT * FROM active_context WHERE user_key=?", (user_key,)
        ).fetchone()
        if not row or int(row["expires_ts"]) < now:
            if row:
                with self._db:
                    self._db.execute("DELETE FROM active_context WHERE user_key=?", (user_key,))
            return None
        return {
            "bobi_device_id": row["bobi_device_id"],
            "area_id": row["area_id"],
            "object_type": row["object_type"],
            "payload": json.loads(row["payload_json"] or "{}"),
            "updated_ts": row["updated_ts"],
            "expires_ts": row["expires_ts"],
        }
