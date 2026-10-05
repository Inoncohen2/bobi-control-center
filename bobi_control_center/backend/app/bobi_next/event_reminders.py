"""Durable Home Assistant event-linked reminders for Bobi Next.

Event reminders reuse the same stable HA trigger contract as conditional rules,
but their side effect is only to enqueue a Bobi-owned reminder delivery. They do
not call Home Assistant services and never create HA automations/helpers.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .conditional import (
    StateChangeEvent,
    TriggerEntityRef,
    TriggerSpec,
    event_matches,
)
from .models import DeviceRecord
from .reminders import ReminderStore

DeviceProvider = Callable[[], Awaitable[Iterable[DeviceRecord]]]
UserEnabled = Callable[[str], bool]
Clock = Callable[[], int]

_MAX_ID = 256
_MAX_TEXT = 4000
_MAX_PROVIDER = 256
_MAX_CHAT = 512


@dataclass(slots=True, frozen=True)
class EventReminderDefinition:
    trigger_id: str
    user_key: str
    provider_key: str
    chat_id: str
    text: str
    trigger: TriggerSpec
    once: bool
    cooldown_seconds: int
    enabled: bool
    source_message_id: str
    created_ts: int
    updated_ts: int
    last_fired_ts: int


@dataclass(slots=True, frozen=True)
class EventReminderResult:
    trigger_id: str
    event_id: str
    outcome: str
    reminder_id: str = ""
    reason: str = ""


def _trigger_payload(trigger: TriggerSpec) -> dict[str, Any]:
    return {
        "kind": trigger.kind,
        "entity": {
            "stable_key": trigger.entity.stable_key,
            "entity_id": trigger.entity.entity_id,
            "domain": trigger.entity.domain,
            "device_id": trigger.entity.device_id,
            "platform": trigger.entity.platform,
            "unique_id": trigger.entity.unique_id,
        },
        "attribute": trigger.attribute,
        "from_state": trigger.from_state,
        "to_state": trigger.to_state,
        "above": trigger.above,
        "below": trigger.below,
        "for_seconds": trigger.for_seconds,
    }


def _trigger_from_payload(payload: dict[str, Any]) -> TriggerSpec:
    kind = str(payload.get("kind") or "")
    if kind not in {"state", "numeric", "availability"}:
        raise ValueError("event_reminder_trigger_kind_invalid")
    raw_entity = payload.get("entity")
    if not isinstance(raw_entity, dict):
        raise ValueError("event_reminder_entity_required")
    entity = TriggerEntityRef(
        stable_key=str(raw_entity.get("stable_key") or "").strip(),
        entity_id=str(raw_entity.get("entity_id") or "").strip(),
        domain=str(raw_entity.get("domain") or "").strip(),
        device_id=str(raw_entity.get("device_id") or "").strip(),
        platform=str(raw_entity.get("platform") or "").strip(),
        unique_id=str(raw_entity.get("unique_id") or "").strip(),
    )
    if not entity.stable_key:
        raise ValueError("event_reminder_stable_entity_required")
    return TriggerSpec(
        kind=kind,  # type: ignore[arg-type]
        entity=entity,
        attribute=str(payload.get("attribute") or "").strip(),
        from_state=(
            str(payload["from_state"]) if payload.get("from_state") is not None else None
        ),
        to_state=(
            str(payload["to_state"]) if payload.get("to_state") is not None else None
        ),
        above=(float(payload["above"]) if payload.get("above") is not None else None),
        below=(float(payload["below"]) if payload.get("below") is not None else None),
        for_seconds=max(0, int(payload.get("for_seconds", 0) or 0)),
    )


def event_reminder_delivery_id(trigger_id: str, event_id: str) -> str:
    raw = f"{trigger_id}\0{event_id}".encode()
    return f"evt-rem-{hashlib.sha256(raw).hexdigest()[:40]}"


class EventReminderStore:
    """SQLite definitions plus event receipts for replay-safe reminder triggers."""

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
            CREATE TABLE IF NOT EXISTS event_reminder_definitions (
                trigger_id TEXT PRIMARY KEY,
                user_key TEXT NOT NULL,
                provider_key TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                text TEXT NOT NULL,
                trigger_json TEXT NOT NULL,
                once_only INTEGER NOT NULL DEFAULT 1,
                cooldown_seconds INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1,
                source_message_id TEXT NOT NULL DEFAULT '',
                created_ts INTEGER NOT NULL,
                updated_ts INTEGER NOT NULL,
                last_fired_ts INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS ix_event_reminders_enabled
                ON event_reminder_definitions(enabled, updated_ts);
            CREATE INDEX IF NOT EXISTS ix_event_reminders_user
                ON event_reminder_definitions(user_key, enabled, created_ts);

            CREATE TABLE IF NOT EXISTS event_reminder_receipts (
                trigger_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                reminder_id TEXT NOT NULL,
                fired_ts INTEGER NOT NULL,
                PRIMARY KEY(trigger_id, event_id),
                FOREIGN KEY(trigger_id) REFERENCES event_reminder_definitions(trigger_id)
                    ON DELETE CASCADE
            );
            """
        )
        self._db.commit()

    @staticmethod
    def _row(row: sqlite3.Row | None) -> EventReminderDefinition | None:
        if row is None:
            return None
        raw = json.loads(str(row["trigger_json"]))
        if not isinstance(raw, dict):
            raise ValueError("event_reminder_trigger_invalid")
        return EventReminderDefinition(
            trigger_id=str(row["trigger_id"]),
            user_key=str(row["user_key"]),
            provider_key=str(row["provider_key"]),
            chat_id=str(row["chat_id"]),
            text=str(row["text"]),
            trigger=_trigger_from_payload(raw),
            once=bool(row["once_only"]),
            cooldown_seconds=max(0, int(row["cooldown_seconds"])),
            enabled=bool(row["enabled"]),
            source_message_id=str(row["source_message_id"]),
            created_ts=int(row["created_ts"]),
            updated_ts=int(row["updated_ts"]),
            last_fired_ts=int(row["last_fired_ts"]),
        )

    def create(
        self,
        *,
        trigger_id: str,
        user_key: str,
        provider_key: str,
        chat_id: str,
        text: str,
        trigger: TriggerSpec,
        once: bool = True,
        cooldown_seconds: int = 0,
        source_message_id: str = "",
        now_ts: int | None = None,
    ) -> EventReminderDefinition:
        identifier = str(trigger_id or "").strip()[:_MAX_ID]
        user = str(user_key or "").strip()[:_MAX_ID]
        provider = str(provider_key or "").strip()[:_MAX_PROVIDER]
        chat = str(chat_id or "").strip()[:_MAX_CHAT]
        content = " ".join(str(text or "").strip().split())[:_MAX_TEXT]
        if not identifier or not user or not provider or not chat:
            raise ValueError("event_reminder_identity_required")
        if not content:
            raise ValueError("event_reminder_text_required")
        if not trigger.entity.stable_key:
            raise ValueError("event_reminder_stable_entity_required")
        if trigger.for_seconds > 0:
            raise ValueError("event_reminder_duration_not_supported")
        cooldown = max(0, int(cooldown_seconds))
        now = int(now_ts or time.time())
        payload = json.dumps(
            _trigger_payload(trigger),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            with self._db:
                self._db.execute(
                    """
                    INSERT INTO event_reminder_definitions(
                        trigger_id,user_key,provider_key,chat_id,text,trigger_json,
                        once_only,cooldown_seconds,enabled,source_message_id,
                        created_ts,updated_ts,last_fired_ts
                    ) VALUES(?,?,?,?,?,?,?, ?,1,?,?,?,0)
                    """,
                    (
                        identifier,
                        user,
                        provider,
                        chat,
                        content,
                        payload,
                        1 if once else 0,
                        cooldown,
                        str(source_message_id or "")[:_MAX_ID],
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("duplicate_event_reminder_id") from exc
        item = self.get(identifier)
        if item is None:
            raise RuntimeError("event_reminder_not_persisted")
        return item

    def get(self, trigger_id: str) -> EventReminderDefinition | None:
        row = self._db.execute(
            "SELECT * FROM event_reminder_definitions WHERE trigger_id=?",
            (str(trigger_id or "").strip(),),
        ).fetchone()
        return self._row(row)

    def list_enabled(self, *, limit: int = 500) -> tuple[EventReminderDefinition, ...]:
        rows = self._db.execute(
            """
            SELECT * FROM event_reminder_definitions
            WHERE enabled=1 ORDER BY created_ts, trigger_id LIMIT ?
            """,
            (max(1, min(int(limit), 2000)),),
        ).fetchall()
        return tuple(item for row in rows if (item := self._row(row)) is not None)

    def has_receipt(self, trigger_id: str, event_id: str) -> bool:
        row = self._db.execute(
            """
            SELECT 1 FROM event_reminder_receipts
            WHERE trigger_id=? AND event_id=? LIMIT 1
            """,
            (trigger_id, event_id),
        ).fetchone()
        return row is not None

    def record_fired(
        self,
        *,
        trigger_id: str,
        event_id: str,
        reminder_id: str,
        fired_ts: int,
    ) -> bool:
        now = max(1, int(fired_ts))
        self._db.execute("BEGIN IMMEDIATE")
        try:
            result = self._db.execute(
                """
                INSERT OR IGNORE INTO event_reminder_receipts(
                    trigger_id,event_id,reminder_id,fired_ts
                ) VALUES(?,?,?,?)
                """,
                (trigger_id, event_id, reminder_id, now),
            )
            inserted = result.rowcount == 1
            if inserted:
                self._db.execute(
                    """
                    UPDATE event_reminder_definitions
                    SET last_fired_ts=?, updated_ts=?,
                        enabled=CASE WHEN once_only=1 THEN 0 ELSE enabled END
                    WHERE trigger_id=?
                    """,
                    (now, now, trigger_id),
                )
            self._db.commit()
            return inserted
        except Exception:
            self._db.rollback()
            raise

    def cancel(self, trigger_id: str, *, user_key: str, now_ts: int | None = None) -> None:
        now = int(now_ts or time.time())
        with self._db:
            result = self._db.execute(
                """
                UPDATE event_reminder_definitions SET enabled=0, updated_ts=?
                WHERE trigger_id=? AND user_key=? AND enabled=1
                """,
                (now, trigger_id, user_key),
            )
        if result.rowcount != 1:
            raise ValueError("event_reminder_not_cancellable")


class EventReminderRuntime:
    """Convert matching HA state events into normal reminder delivery jobs."""

    def __init__(
        self,
        *,
        definitions: EventReminderStore,
        reminders: ReminderStore,
        list_devices: DeviceProvider,
        user_enabled: UserEnabled | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.definitions = definitions
        self.reminders = reminders
        self.list_devices = list_devices
        self.user_enabled = user_enabled or (lambda user_key: True)
        self.clock = clock or (lambda: int(time.time()))

    async def observe_event(self, event: StateChangeEvent) -> tuple[EventReminderResult, ...]:
        devices = tuple(await self.list_devices())
        fired_ts = int(event.occurred_ts or self.clock())
        event_id = str(event.event_id or "").strip()
        if not event_id:
            return ()

        results: list[EventReminderResult] = []
        for definition in self.definitions.list_enabled():
            if not self.user_enabled(definition.user_key):
                continue
            if self.definitions.has_receipt(definition.trigger_id, event_id):
                continue
            if (
                definition.cooldown_seconds > 0
                and definition.last_fired_ts > 0
                and fired_ts - definition.last_fired_ts < definition.cooldown_seconds
            ):
                continue
            if not event_matches(definition.trigger, event, devices):
                continue

            reminder_id = event_reminder_delivery_id(definition.trigger_id, event_id)
            existing = self.reminders.get(reminder_id)
            if existing is None:
                try:
                    self.reminders.create(
                        reminder_id=reminder_id,
                        user_key=definition.user_key,
                        provider_key=definition.provider_key,
                        chat_id=definition.chat_id,
                        text=definition.text,
                        run_at_ts=max(1, fired_ts),
                        source_message_id=definition.source_message_id,
                        now_ts=max(1, fired_ts),
                    )
                except ValueError as exc:
                    if str(exc) != "duplicate_reminder_id":
                        raise

            inserted = self.definitions.record_fired(
                trigger_id=definition.trigger_id,
                event_id=event_id,
                reminder_id=reminder_id,
                fired_ts=max(1, fired_ts),
            )
            results.append(
                EventReminderResult(
                    trigger_id=definition.trigger_id,
                    event_id=event_id,
                    outcome="queued" if inserted else "duplicate",
                    reminder_id=reminder_id,
                )
            )
        return tuple(results)
