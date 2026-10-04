"""Durable conditional rules and deterministic HA state-trigger matching.

Rules keep stable semantic trigger identity plus a semantic device action.  They
never persist an arbitrary HA service call.  A matching event only authorizes a
runner to *consider* the action; policy, capability validation and secure
execution are re-evaluated at fire time.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from .models import DeviceRecord, EntityRecord

TriggerKind = Literal["state", "numeric", "availability"]


@dataclass(slots=True, frozen=True)
class TriggerEntityRef:
    stable_key: str
    entity_id: str
    domain: str
    device_id: str = ""
    platform: str = ""
    unique_id: str = ""


@dataclass(slots=True, frozen=True)
class TriggerSpec:
    kind: TriggerKind
    entity: TriggerEntityRef
    attribute: str = ""
    from_state: str | None = None
    to_state: str | None = None
    above: float | None = None
    below: float | None = None
    for_seconds: int = 0


@dataclass(slots=True, frozen=True)
class StateChangeEvent:
    event_id: str
    entity_id: str
    old_state: str | None
    new_state: str | None
    old_attributes: dict[str, Any]
    new_attributes: dict[str, Any]
    occurred_ts: int


@dataclass(slots=True, frozen=True)
class ConditionalRule:
    rule_id: str
    user_key: str
    source_text: str
    trigger: TriggerSpec
    action_payload: dict[str, Any]
    enabled: bool
    cooldown_seconds: int
    once: bool
    created_ts: int
    updated_ts: int
    last_fired_ts: int
    last_error: str


def entity_stable_key(entity: EntityRecord) -> str:
    if entity.device_id and entity.platform and entity.unique_id:
        return f"device:{entity.device_id}:entity:{entity.platform}:{entity.unique_id}"
    if entity.platform and entity.unique_id:
        return f"entity:{entity.platform}:{entity.unique_id}"
    return f"entity_id:{entity.entity_id}"


def trigger_ref(entity: EntityRecord) -> TriggerEntityRef:
    return TriggerEntityRef(
        stable_key=entity_stable_key(entity),
        entity_id=entity.entity_id,
        domain=entity.domain,
        device_id=entity.device_id,
        platform=entity.platform,
        unique_id=entity.unique_id,
    )


def find_trigger_entity(
    devices: tuple[DeviceRecord, ...],
    *,
    stable_key: str,
) -> EntityRecord | None:
    for device in devices:
        for entity in device.entities:
            if entity_stable_key(entity) == stable_key:
                return entity
    return None


def _value(event: StateChangeEvent, attribute: str, *, old: bool) -> Any:
    if attribute:
        attrs = event.old_attributes if old else event.new_attributes
        return attrs.get(attribute)
    return event.old_state if old else event.new_state


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def event_matches(
    trigger: TriggerSpec,
    event: StateChangeEvent,
    devices: tuple[DeviceRecord, ...],
) -> bool:
    """Match only transitions for the currently discovered stable entity."""

    if trigger.for_seconds > 0:
        # Duration triggers are handled by ConditionalDurationRuntime.  Keep the
        # immediate runner fail-closed so the initial transition never fires.
        return False

    live_entity = find_trigger_entity(devices, stable_key=trigger.entity.stable_key)
    if live_entity is None or live_entity.entity_id != event.entity_id:
        return False

    old_value = _value(event, trigger.attribute, old=True)
    new_value = _value(event, trigger.attribute, old=False)

    if trigger.kind == "state":
        if trigger.from_state is not None and str(old_value) != trigger.from_state:
            return False
        if trigger.to_state is not None and str(new_value) != trigger.to_state:
            return False
        if trigger.from_state is None and trigger.to_state is None:
            return old_value != new_value
        return old_value != new_value

    if trigger.kind == "availability":
        old_unavailable = str(event.old_state) in {"unknown", "unavailable", "None"}
        new_unavailable = str(event.new_state) in {"unknown", "unavailable", "None"}
        if trigger.to_state == "available":
            return old_unavailable and not new_unavailable
        if trigger.to_state == "unavailable":
            return not old_unavailable and new_unavailable
        return old_unavailable != new_unavailable

    if trigger.kind == "numeric":
        old_number = _number(old_value)
        new_number = _number(new_value)
        if new_number is None:
            return False
        if trigger.above is not None:
            was_below = old_number is None or old_number <= trigger.above
            if not (was_below and new_number > trigger.above):
                return False
        if trigger.below is not None:
            was_above = old_number is None or old_number >= trigger.below
            if not (was_above and new_number < trigger.below):
                return False
        return trigger.above is not None or trigger.below is not None

    return False


def _trigger_payload(trigger: TriggerSpec) -> dict[str, Any]:
    payload = asdict(trigger)
    payload["entity"] = asdict(trigger.entity)
    return payload


def _trigger_from_payload(payload: dict[str, Any]) -> TriggerSpec:
    entity_raw = dict(payload.get("entity") or {})
    entity = TriggerEntityRef(
        stable_key=str(entity_raw["stable_key"]),
        entity_id=str(entity_raw.get("entity_id") or ""),
        domain=str(entity_raw.get("domain") or ""),
        device_id=str(entity_raw.get("device_id") or ""),
        platform=str(entity_raw.get("platform") or ""),
        unique_id=str(entity_raw.get("unique_id") or ""),
    )
    kind = str(payload.get("kind") or "")
    if kind not in {"state", "numeric", "availability"}:
        raise ValueError("unsupported_trigger_kind")
    return TriggerSpec(
        kind=kind,  # type: ignore[arg-type]
        entity=entity,
        attribute=str(payload.get("attribute") or ""),
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


class ConditionalRuleStore:
    """SQLite rules + per-event fire receipts for restart-safe deduplication."""

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
            CREATE TABLE IF NOT EXISTS conditional_rules (
                rule_id TEXT PRIMARY KEY,
                user_key TEXT NOT NULL,
                source_text TEXT NOT NULL DEFAULT '',
                trigger_json TEXT NOT NULL,
                action_json TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                cooldown_seconds INTEGER NOT NULL DEFAULT 0,
                once_rule INTEGER NOT NULL DEFAULT 0,
                created_ts INTEGER NOT NULL,
                updated_ts INTEGER NOT NULL,
                last_fired_ts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS conditional_fire_receipts (
                rule_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'claimed',
                created_ts INTEGER NOT NULL,
                updated_ts INTEGER NOT NULL,
                error TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(rule_id,event_id)
            );
            CREATE INDEX IF NOT EXISTS ix_conditional_rules_enabled
                ON conditional_rules(enabled, updated_ts DESC);
            """
        )
        self._db.commit()

    @staticmethod
    def _row(row: sqlite3.Row | None) -> ConditionalRule | None:
        if row is None:
            return None
        return ConditionalRule(
            rule_id=str(row["rule_id"]),
            user_key=str(row["user_key"]),
            source_text=str(row["source_text"]),
            trigger=_trigger_from_payload(json.loads(row["trigger_json"])),
            action_payload=dict(json.loads(row["action_json"])),
            enabled=bool(row["enabled"]),
            cooldown_seconds=int(row["cooldown_seconds"]),
            once=bool(row["once_rule"]),
            created_ts=int(row["created_ts"]),
            updated_ts=int(row["updated_ts"]),
            last_fired_ts=int(row["last_fired_ts"]),
            last_error=str(row["last_error"]),
        )

    def create(
        self,
        *,
        rule_id: str,
        user_key: str,
        source_text: str,
        trigger: TriggerSpec,
        action_payload: dict[str, Any],
        cooldown_seconds: int = 0,
        once: bool = False,
        now_ts: int | None = None,
    ) -> ConditionalRule:
        if not rule_id.strip() or not user_key.strip():
            raise ValueError("invalid_conditional_identity")
        now = int(now_ts or time.time())
        with self._db:
            self._db.execute(
                """
                INSERT INTO conditional_rules(
                    rule_id,user_key,source_text,trigger_json,action_json,enabled,
                    cooldown_seconds,once_rule,created_ts,updated_ts
                ) VALUES(?,?,?,?,?,1,?,?,?,?)
                """,
                (
                    rule_id,
                    user_key,
                    source_text[:2000],
                    json.dumps(_trigger_payload(trigger), ensure_ascii=False, sort_keys=True),
                    json.dumps(action_payload, ensure_ascii=False, sort_keys=True),
                    max(0, int(cooldown_seconds)),
                    int(bool(once)),
                    now,
                    now,
                ),
            )
        result = self.get(rule_id)
        if result is None:
            raise RuntimeError("conditional_rule_not_persisted")
        return result

    def get(self, rule_id: str) -> ConditionalRule | None:
        row = self._db.execute(
            "SELECT * FROM conditional_rules WHERE rule_id=?",
            (rule_id,),
        ).fetchone()
        return self._row(row)

    def enabled_rules(self) -> tuple[ConditionalRule, ...]:
        rows = self._db.execute(
            "SELECT * FROM conditional_rules WHERE enabled=1 ORDER BY created_ts, rule_id"
        ).fetchall()
        return tuple(rule for row in rows if (rule := self._row(row)) is not None)

    def set_enabled(self, rule_id: str, enabled: bool, *, now_ts: int | None = None) -> None:
        now = int(now_ts or time.time())
        with self._db:
            updated = self._db.execute(
                "UPDATE conditional_rules SET enabled=?, updated_ts=? WHERE rule_id=?",
                (int(bool(enabled)), now, rule_id),
            )
        if updated.rowcount != 1:
            raise KeyError("conditional_rule_not_found")

    def claim_fire(
        self,
        *,
        rule_id: str,
        event_id: str,
        now_ts: int,
    ) -> bool:
        if not event_id.strip():
            raise ValueError("event_id_required")
        self._db.execute("BEGIN IMMEDIATE")
        try:
            row = self._db.execute(
                "SELECT * FROM conditional_rules WHERE rule_id=?",
                (rule_id,),
            ).fetchone()
            rule = self._row(row)
            if rule is None or not rule.enabled:
                self._db.rollback()
                return False
            if (
                rule.cooldown_seconds > 0
                and rule.last_fired_ts
                and now_ts - rule.last_fired_ts < rule.cooldown_seconds
            ):
                self._db.rollback()
                return False
            try:
                self._db.execute(
                    """
                    INSERT INTO conditional_fire_receipts(
                        rule_id,event_id,state,created_ts,updated_ts
                    ) VALUES(?,?,'claimed',?,?)
                    """,
                    (rule_id, event_id, now_ts, now_ts),
                )
            except sqlite3.IntegrityError:
                self._db.rollback()
                return False
            self._db.commit()
            return True
        except Exception:
            self._db.rollback()
            raise

    def finish_fire(
        self,
        *,
        rule_id: str,
        event_id: str,
        success: bool,
        now_ts: int,
        error: str = "",
    ) -> None:
        self._db.execute("BEGIN IMMEDIATE")
        try:
            receipt = self._db.execute(
                """
                SELECT state FROM conditional_fire_receipts
                WHERE rule_id=? AND event_id=?
                """,
                (rule_id, event_id),
            ).fetchone()
            if receipt is None or str(receipt["state"]) != "claimed":
                self._db.rollback()
                raise PermissionError("conditional_fire_not_claimed")
            self._db.execute(
                """
                UPDATE conditional_fire_receipts
                SET state=?, updated_ts=?, error=?
                WHERE rule_id=? AND event_id=?
                """,
                ("completed" if success else "failed", now_ts, error[:1000], rule_id, event_id),
            )
            if success:
                rule = self.get(rule_id)
                disable = bool(rule and rule.once)
                self._db.execute(
                    """
                    UPDATE conditional_rules
                    SET last_fired_ts=?, last_error='', enabled=?, updated_ts=?
                    WHERE rule_id=?
                    """,
                    (now_ts, 0 if disable else 1, now_ts, rule_id),
                )
            else:
                self._db.execute(
                    """
                    UPDATE conditional_rules SET last_error=?, updated_ts=? WHERE rule_id=?
                    """,
                    (error[:1000], now_ts, rule_id),
                )
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
