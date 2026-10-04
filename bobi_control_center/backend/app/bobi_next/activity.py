"""Verified activity ledger and conservative undo for Bobi Next.

Only mutations whose previous Home Assistant state can be reconstructed safely
are marked undoable. Undo never blindly replays stale state: the entity must
still match the relevant post-action snapshot, authorization is evaluated again,
and the inverse mutation is verified through the normal secure executor.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .authorization import (
    RequestProvenance,
    UserPolicy,
    approval_state_guard,
    authorize_plan,
    state_fingerprint,
)
from .executor import ExecutionResult, HAControlClient
from .models import ActionPlan
from .pending_approval import PendingApprovalStore
from .secure_execution import execute_authorized_plan


@dataclass(slots=True, frozen=True)
class ActivityRecord:
    activity_id: int
    request_id: str
    user_key: str
    original_plan: ActionPlan
    inverse_plan: ActionPlan | None
    before: dict[str, Any]
    after: dict[str, Any]
    created_ts: int
    undone_ts: int = 0
    undo_request_id: str = ""
    undo_approval_request_id: str = ""


@dataclass(slots=True, frozen=True)
class UndoResult:
    outcome: str
    reason: str
    activity_id: int = 0
    approval_request_id: str = ""


def _plan_from_json(raw: str) -> ActionPlan:
    payload = json.loads(raw)
    return ActionPlan(
        request_id=str(payload["request_id"]),
        device_id=str(payload["device_id"]),
        entity_id=str(payload["entity_id"]),
        domain=str(payload["domain"]),
        action=str(payload["action"]),
        capability=str(payload["capability"]),
        data=dict(payload.get("data") or {}),
        expected=dict(payload.get("expected") or {}),
        source=str(payload.get("source") or "direct"),  # type: ignore[arg-type]
        confidence=float(payload.get("confidence", 1.0)),
        requires_confirmation=bool(payload.get("requires_confirmation", False)),
    )


def _plan_json(plan: ActionPlan | None) -> str:
    if plan is None:
        return ""
    return json.dumps(asdict(plan), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _snapshot_json(snapshot: dict[str, Any] | None) -> str:
    return json.dumps(snapshot or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _attrs(snapshot: dict[str, Any]) -> dict[str, Any]:
    raw = snapshot.get("attributes")
    return raw if isinstance(raw, dict) else {}


def _inverse(
    execution: ExecutionResult,
    *,
    undo_request_id: str,
) -> ActionPlan | None:
    before = execution.before or {}
    state = str(before.get("state", ""))
    attrs = _attrs(before)
    plan = execution.plan
    base = {
        "request_id": undo_request_id,
        "device_id": plan.device_id,
        "entity_id": plan.entity_id,
        "domain": plan.domain,
        "source": "direct",
        "confidence": 1.0,
    }

    if plan.capability == "power":
        if plan.domain == "climate":
            if state == "off":
                return ActionPlan(
                    **base,
                    action="turn_off",
                    capability="power",
                    data={"entity_id": plan.entity_id},
                    expected={"state": "off"},
                )
            if state and state not in {"unknown", "unavailable"}:
                return ActionPlan(
                    **base,
                    action="set_hvac_mode",
                    capability="hvac_mode",
                    data={"entity_id": plan.entity_id, "hvac_mode": state},
                    expected={"state": state},
                )
            return None
        if state == "off":
            return ActionPlan(
                **base,
                action="turn_off",
                capability="power",
                data={"entity_id": plan.entity_id},
                expected={"state": "off"},
            )
        if state and state not in {"unknown", "unavailable"}:
            expected = (
                {"state_not": ["off", "unknown", "unavailable"]}
                if plan.domain == "media_player"
                else {"state": "on"}
            )
            return ActionPlan(
                **base,
                action="turn_on",
                capability="power",
                data={"entity_id": plan.entity_id},
                expected=expected,
            )
        return None

    if plan.domain == "climate" and plan.capability == "temperature":
        value = attrs.get("temperature")
        if value is None:
            return None
        return ActionPlan(
            **base,
            action="set_temperature",
            capability="temperature",
            data={"entity_id": plan.entity_id, "temperature": value},
            expected={"attribute": "temperature", "value": value, "tolerance": 0.05},
        )

    if plan.domain == "climate" and plan.capability in {
        "hvac_mode",
        "fan_mode",
        "swing_mode",
        "preset_mode",
    }:
        mapping = {
            "hvac_mode": ("set_hvac_mode", "hvac_mode"),
            "fan_mode": ("set_fan_mode", "fan_mode"),
            "swing_mode": ("set_swing_mode", "swing_mode"),
            "preset_mode": ("set_preset_mode", "preset_mode"),
        }
        action, key = mapping[plan.capability]
        value = state if plan.capability == "hvac_mode" else attrs.get(key)
        if value in {None, "", "unknown", "unavailable"}:
            return None
        expected = {"state": value} if plan.capability == "hvac_mode" else {
            "attribute": key,
            "value": value,
        }
        return ActionPlan(
            **base,
            action=action,
            capability=plan.capability,
            data={"entity_id": plan.entity_id, key: value},
            expected=expected,
        )

    if plan.domain == "light" and plan.capability == "brightness":
        if state == "off":
            return ActionPlan(
                **base,
                action="turn_off",
                capability="power",
                data={"entity_id": plan.entity_id},
                expected={"state": "off"},
            )
        raw = attrs.get("brightness")
        if raw is None:
            return ActionPlan(
                **base,
                action="turn_on",
                capability="power",
                data={"entity_id": plan.entity_id},
                expected={"state": "on"},
            )
        pct = round(float(raw) / 255.0 * 100.0)
        return ActionPlan(
            **base,
            action="turn_on",
            capability="brightness",
            data={"entity_id": plan.entity_id, "brightness_pct": pct},
            expected={"attribute": "brightness_pct", "value": pct, "tolerance": 2},
        )

    if plan.domain == "cover" and plan.capability in {"position", "open", "close"}:
        value = attrs.get("current_position")
        if value is not None:
            return ActionPlan(
                **base,
                action="set_cover_position",
                capability="position",
                data={"entity_id": plan.entity_id, "position": round(float(value))},
                expected={
                    "attribute": "current_position",
                    "value": round(float(value)),
                    "tolerance": 2,
                },
            )
        if state in {"open", "closed"}:
            action = "open_cover" if state == "open" else "close_cover"
            return ActionPlan(
                **base,
                action=action,
                capability="open" if state == "open" else "close",
                data={"entity_id": plan.entity_id},
                expected={"state": state},
            )
        return None

    if plan.domain == "cover" and plan.capability == "tilt_position":
        value = attrs.get("current_tilt_position")
        if value is None:
            return None
        return ActionPlan(
            **base,
            action="set_cover_tilt_position",
            capability="tilt_position",
            data={"entity_id": plan.entity_id, "tilt_position": round(float(value))},
            expected={
                "attribute": "current_tilt_position",
                "value": round(float(value)),
                "tolerance": 2,
            },
        )

    if plan.domain == "fan" and plan.capability == "percentage":
        value = attrs.get("percentage")
        if value is None:
            return None
        return ActionPlan(
            **base,
            action="set_percentage",
            capability="percentage",
            data={"entity_id": plan.entity_id, "percentage": round(float(value))},
            expected={"attribute": "percentage", "value": round(float(value)), "tolerance": 1},
        )

    if plan.capability == "preset_mode" and plan.domain == "fan":
        value = attrs.get("preset_mode")
        if not value:
            return None
        return ActionPlan(
            **base,
            action="set_preset_mode",
            capability="preset_mode",
            data={"entity_id": plan.entity_id, "preset_mode": value},
            expected={"attribute": "preset_mode", "value": value},
        )

    if plan.domain == "vacuum" and plan.capability == "fan_speed":
        value = attrs.get("fan_speed")
        if not value:
            return None
        return ActionPlan(
            **base,
            action="set_fan_speed",
            capability="fan_speed",
            data={"entity_id": plan.entity_id, "fan_speed": value},
            expected={"attribute": "fan_speed", "value": value},
        )

    if plan.domain == "lock" and plan.capability in {"lock", "unlock"}:
        if state not in {"locked", "unlocked"}:
            return None
        return ActionPlan(
            **base,
            action="lock" if state == "locked" else "unlock",
            capability="lock" if state == "locked" else "unlock",
            data={"entity_id": plan.entity_id},
            expected={"state": state},
        )

    if plan.domain == "number" and plan.capability == "set_value":
        try:
            value = float(state)
        except ValueError:
            return None
        return ActionPlan(
            **base,
            action="set_value",
            capability="set_value",
            data={"entity_id": plan.entity_id, "value": value},
            expected={"state": str(value)},
        )

    if plan.domain == "select" and plan.capability == "select_option":
        if not state or state in {"unknown", "unavailable"}:
            return None
        return ActionPlan(
            **base,
            action="select_option",
            capability="select_option",
            data={"entity_id": plan.entity_id, "option": state},
            expected={"state": state},
        )

    if plan.domain == "media_player" and plan.capability == "volume":
        value = attrs.get("volume_level")
        if value is None:
            return None
        return ActionPlan(
            **base,
            action="volume_set",
            capability="volume",
            data={"entity_id": plan.entity_id, "volume_level": float(value)},
            expected={"attribute": "volume_level", "value": float(value), "tolerance": 0.02},
        )

    if plan.domain == "media_player" and plan.capability in {"play", "pause", "stop"}:
        mapping = {
            "playing": ("media_play", "play", ["playing"]),
            "paused": ("media_pause", "pause", ["paused"]),
            "idle": ("media_stop", "stop", ["idle", "off", "paused"]),
            "off": ("turn_off", "power", ["off"]),
        }
        restored = mapping.get(state)
        if restored is None:
            return None
        action, capability, states = restored
        return ActionPlan(
            **base,
            action=action,
            capability=capability,
            data={"entity_id": plan.entity_id},
            expected={"state_any": states},
        )

    return None


class ActivityLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS activities (
                activity_id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL,
                user_key TEXT NOT NULL,
                original_plan_json TEXT NOT NULL,
                inverse_plan_json TEXT NOT NULL DEFAULT '',
                before_json TEXT NOT NULL,
                after_json TEXT NOT NULL,
                created_ts INTEGER NOT NULL,
                undone_ts INTEGER NOT NULL DEFAULT 0,
                undo_request_id TEXT NOT NULL DEFAULT '',
                undo_approval_request_id TEXT NOT NULL DEFAULT '',
                UNIQUE(request_id, original_plan_json)
            );
            CREATE INDEX IF NOT EXISTS ix_activity_user_undo
                ON activities(user_key, undone_ts, activity_id DESC);
            """
        )
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    @staticmethod
    def _row(row: sqlite3.Row | None) -> ActivityRecord | None:
        if row is None:
            return None
        inverse_raw = str(row["inverse_plan_json"] or "")
        return ActivityRecord(
            activity_id=int(row["activity_id"]),
            request_id=str(row["request_id"]),
            user_key=str(row["user_key"]),
            original_plan=_plan_from_json(str(row["original_plan_json"])),
            inverse_plan=_plan_from_json(inverse_raw) if inverse_raw else None,
            before=json.loads(str(row["before_json"])),
            after=json.loads(str(row["after_json"])),
            created_ts=int(row["created_ts"]),
            undone_ts=int(row["undone_ts"]),
            undo_request_id=str(row["undo_request_id"]),
            undo_approval_request_id=str(row["undo_approval_request_id"]),
        )

    def record_verified(
        self,
        *,
        user_key: str,
        execution: ExecutionResult,
        created_ts: int | None = None,
    ) -> ActivityRecord | None:
        if not execution.executed or not execution.verified:
            return None
        now = int(created_ts or time.time())
        undo_request_id = f"undo:{execution.plan.request_id}:{execution.plan.entity_id}"
        inverse = _inverse(execution, undo_request_id=undo_request_id)
        original_json = _plan_json(execution.plan)
        with self._db:
            self._db.execute(
                """
                INSERT INTO activities(
                    request_id,user_key,original_plan_json,inverse_plan_json,
                    before_json,after_json,created_ts
                ) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(request_id, original_plan_json) DO NOTHING
                """,
                (
                    execution.plan.request_id,
                    user_key,
                    original_json,
                    _plan_json(inverse),
                    _snapshot_json(execution.before),
                    _snapshot_json(execution.after),
                    now,
                ),
            )
        row = self._db.execute(
            "SELECT * FROM activities WHERE request_id=? AND original_plan_json=?",
            (execution.plan.request_id, original_json),
        ).fetchone()
        return self._row(row)

    def latest_undoable(self, user_key: str) -> ActivityRecord | None:
        row = self._db.execute(
            """
            SELECT * FROM activities
            WHERE user_key=? AND undone_ts=0 AND inverse_plan_json<>''
            ORDER BY activity_id DESC LIMIT 1
            """,
            (user_key,),
        ).fetchone()
        return self._row(row)

    def mark_pending(self, activity_id: int, approval_request_id: str) -> None:
        with self._db:
            self._db.execute(
                "UPDATE activities SET undo_approval_request_id=? WHERE activity_id=?",
                (approval_request_id, activity_id),
            )

    def mark_undone(
        self,
        activity_id: int,
        *,
        undo_request_id: str,
        now_ts: int | None = None,
    ) -> None:
        now = int(now_ts or time.time())
        with self._db:
            self._db.execute(
                """
                UPDATE activities
                SET undone_ts=?, undo_request_id=?
                WHERE activity_id=? AND undone_ts=0
                """,
                (now, undo_request_id, activity_id),
            )

    def mark_approval_completed(
        self,
        approval_request_id: str,
        *,
        now_ts: int | None = None,
    ) -> bool:
        now = int(now_ts or time.time())
        with self._db:
            result = self._db.execute(
                """
                UPDATE activities
                SET undone_ts=?, undo_request_id=undo_approval_request_id
                WHERE undo_approval_request_id=? AND undone_ts=0
                """,
                (now, approval_request_id),
            )
        return result.rowcount == 1


async def undo_latest(
    ledger: ActivityLedger,
    client: HAControlClient,
    *,
    user_key: str,
    policy: UserPolicy,
    undo_request_id: str,
    pending_approvals: PendingApprovalStore | None = None,
    now_ts: int | None = None,
    verification_attempts: int = 3,
    verification_delay: float = 0.35,
) -> UndoResult:
    record = ledger.latest_undoable(user_key)
    if record is None or record.inverse_plan is None:
        return UndoResult("nothing_to_undo", "no_undoable_activity")

    current = await client.get_state(record.original_plan.entity_id)
    if current is None or str(current.get("state", "")) in {"unknown", "unavailable"}:
        return UndoResult("blocked", "target_unavailable", record.activity_id)

    expected_after = approval_state_guard(record.original_plan, record.after)
    current_after = approval_state_guard(record.original_plan, current)
    if state_fingerprint(expected_after) != state_fingerprint(current_after):
        return UndoResult("blocked", "state_changed_since_action", record.activity_id)

    inverse = record.inverse_plan
    inverse.request_id = undo_request_id
    provenance = RequestProvenance(
        source_kind="direct",
        same_text=True,
        explicit_target_ids=frozenset({inverse.device_id}),
    )
    decision = authorize_plan(inverse, policy=policy, provenance=provenance)
    if decision.requires_approval:
        if pending_approvals is None:
            return UndoResult("approval_required", "approval_store_missing", record.activity_id)
        approval_request_id = f"undo-approval:{record.activity_id}:{undo_request_id}"
        guard = approval_state_guard(inverse, current)
        pending_approvals.create(
            approval_request_id=approval_request_id,
            source_request_id=undo_request_id,
            user_key=user_key,
            plans=(inverse,),
            provenance=provenance,
            state_guards=(guard,),
            summary="Undo previous Bobi action",
            now_ts=now_ts,
        )
        ledger.mark_pending(record.activity_id, approval_request_id)
        return UndoResult(
            "approval_required",
            "approval_required",
            record.activity_id,
            approval_request_id,
        )
    if not decision.allowed:
        return UndoResult("blocked", decision.reason, record.activity_id)

    result = await execute_authorized_plan(
        inverse,
        client,
        user_key=user_key,
        policy=policy,
        provenance=provenance,
        verification_attempts=verification_attempts,
        verification_delay=verification_delay,
    )
    if not result.executed or not result.verified:
        return UndoResult("failed", result.reason, record.activity_id)

    ledger.mark_undone(record.activity_id, undo_request_id=undo_request_id, now_ts=now_ts)
    return UndoResult("completed", "verified", record.activity_id)
