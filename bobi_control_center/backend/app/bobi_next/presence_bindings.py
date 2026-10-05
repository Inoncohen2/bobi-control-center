"""Durable Bobi-user to Home Assistant presence identity bindings.

Location-sensitive features must never guess which ``person`` or
``device_tracker`` belongs to a messaging user. Setup explicitly binds a Bobi
user to one discovered presence entity and stores the entity's stable identity,
so entity-id renames do not break the association.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .conditional import TriggerEntityRef, find_trigger_entity, trigger_ref
from .event_reminders import EventReminderStore
from .models import DeviceRecord, EntityRecord

_ALLOWED_DOMAINS = frozenset({"person", "device_tracker"})


@dataclass(slots=True, frozen=True)
class UserPresenceBinding:
    user_key: str
    entity: TriggerEntityRef
    created_ts: int
    updated_ts: int


class PresenceBindingStore:
    """SQLite-backed explicit presence mapping owned by Bobi, not HA helpers."""

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
            CREATE TABLE IF NOT EXISTS user_presence_bindings (
                user_key TEXT PRIMARY KEY,
                entity_json TEXT NOT NULL,
                created_ts INTEGER NOT NULL,
                updated_ts INTEGER NOT NULL
            );
            """
        )
        self._db.commit()

    @staticmethod
    def _validate_entity(entity: EntityRecord) -> None:
        if entity.domain not in _ALLOWED_DOMAINS:
            raise ValueError("presence_entity_domain_invalid")
        ref = trigger_ref(entity)
        if not ref.stable_key or ref.stable_key.startswith("entity_id:"):
            raise ValueError("presence_entity_stable_identity_required")

    def bind(
        self,
        *,
        user_key: str,
        entity: EntityRecord,
        now_ts: int | None = None,
    ) -> UserPresenceBinding:
        user = str(user_key or "").strip()
        if not user:
            raise ValueError("presence_user_required")
        self._validate_entity(entity)
        ref = trigger_ref(entity)
        now = int(now_ts or time.time())
        encoded = json.dumps(
            asdict(ref),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._db:
            self._db.execute(
                """
                INSERT INTO user_presence_bindings(user_key,entity_json,created_ts,updated_ts)
                VALUES(?,?,?,?)
                ON CONFLICT(user_key) DO UPDATE SET
                    entity_json=excluded.entity_json,
                    updated_ts=excluded.updated_ts
                """,
                (user, encoded, now, now),
            )
        binding = self.get(user)
        if binding is None:
            raise RuntimeError("presence_binding_not_persisted")
        return binding

    def get(self, user_key: str) -> UserPresenceBinding | None:
        row = self._db.execute(
            "SELECT * FROM user_presence_bindings WHERE user_key=?",
            (str(user_key or "").strip(),),
        ).fetchone()
        if row is None:
            return None
        raw = json.loads(str(row["entity_json"]))
        if not isinstance(raw, dict):
            raise ValueError("presence_binding_corrupt")
        ref = TriggerEntityRef(
            stable_key=str(raw.get("stable_key") or ""),
            entity_id=str(raw.get("entity_id") or ""),
            domain=str(raw.get("domain") or ""),
            device_id=str(raw.get("device_id") or ""),
            platform=str(raw.get("platform") or ""),
            unique_id=str(raw.get("unique_id") or ""),
        )
        return UserPresenceBinding(
            user_key=str(row["user_key"]),
            entity=ref,
            created_ts=int(row["created_ts"]),
            updated_ts=int(row["updated_ts"]),
        )

    def unbind(self, user_key: str) -> bool:
        with self._db:
            result = self._db.execute(
                "DELETE FROM user_presence_bindings WHERE user_key=?",
                (str(user_key or "").strip(),),
            )
        return result.rowcount == 1

    def resolve_live(
        self,
        user_key: str,
        devices: tuple[DeviceRecord, ...],
    ) -> EntityRecord | None:
        binding = self.get(user_key)
        if binding is None:
            return None
        entity = find_trigger_entity(devices, stable_key=binding.entity.stable_key)
        if entity is None or entity.domain not in _ALLOWED_DOMAINS:
            return None
        return entity


class PresenceAwareEventReminderStore(EventReminderStore):
    """Event reminder definitions plus the explicit user-presence binding."""

    def __init__(
        self,
        path: str | Path,
        *,
        presence_path: str | Path,
    ) -> None:
        super().__init__(path)
        self.presence_bindings = PresenceBindingStore(presence_path)
        self._presence_closed = False

    def resolve_presence(
        self,
        user_key: str,
        devices: tuple[DeviceRecord, ...],
    ) -> EntityRecord | None:
        return self.presence_bindings.resolve_live(user_key, devices)

    def close(self) -> None:
        if not self._presence_closed:
            self.presence_bindings.close()
            self._presence_closed = True
        super().close()
