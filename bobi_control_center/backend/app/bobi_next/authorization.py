"""Generic authorization and single-use approval contracts for Bobi Next.

The policy layer is intentionally independent from WhatsApp, AI providers and
household-specific entity ids.  AI may propose a plan; this module decides
whether the authenticated user and the source provenance authorize that exact
side effect.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any

from .models import ActionPlan


class RiskLevel(IntEnum):
    LOW = 10
    MEDIUM = 20
    HIGH = 30
    CRITICAL = 40


@dataclass(slots=True, frozen=True)
class UserPolicy:
    user_key: str
    allowed_capabilities: frozenset[str] = field(
        default_factory=lambda: frozenset({"*"})
    )
    denied_capabilities: frozenset[str] = frozenset()
    allowed_domains: frozenset[str] = field(default_factory=lambda: frozenset({"*"}))
    denied_actions: frozenset[str] = frozenset()
    max_without_approval: RiskLevel = RiskLevel.MEDIUM
    can_approve: bool = True


@dataclass(slots=True, frozen=True)
class RequestProvenance:
    """Evidence that connects a planned side effect back to the user's words."""

    source_kind: str = "direct"
    same_text: bool = True
    explicit_target_ids: frozenset[str] = frozenset()
    allowed_target_ids: frozenset[str] = frozenset()
    negated: bool = False
    question: bool = False
    literal_name: bool = False
    reference_only: bool = False


@dataclass(slots=True, frozen=True)
class AuthorizationDecision:
    allowed: bool
    reason: str
    risk: RiskLevel
    requires_approval: bool
    approval_authorized: bool
    plan_fingerprint: str


@dataclass(slots=True, frozen=True)
class ApprovalGrant:
    approval_id: str
    token: str
    user_key: str
    plan_fingerprint: str
    state_fingerprint: str
    expires_at: int


@dataclass(slots=True, frozen=True)
class ApprovalValidation:
    valid: bool
    reason: str
    approval_id: str = ""
    plan_fingerprint: str = ""
    state_fingerprint: str = ""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def plan_fingerprint(plan: ActionPlan) -> str:
    """Bind approval to the exact semantic target and mutation."""

    payload = {
        "request_id": plan.request_id,
        "device_id": plan.device_id,
        "entity_id": plan.entity_id,
        "domain": plan.domain,
        "action": plan.action,
        "capability": plan.capability,
        "data": plan.data,
        "expected": plan.expected,
        "source": plan.source,
    }
    return _sha256_text(_canonical_json(payload))


def state_fingerprint(state_guard: dict[str, Any]) -> str:
    return _sha256_text(_canonical_json(state_guard))


def approval_state_guard(
    plan: ActionPlan,
    snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    """Create a stable, relevant precondition for an approval.

    We bind to the entity state plus attributes that matter to this plan.  This
    avoids invalidating an approval because an unrelated volatile attribute
    changed while still detecting material target-state changes.
    """

    if snapshot is None:
        return {"entity_id": plan.entity_id, "state": "missing"}
    attrs_raw = snapshot.get("attributes")
    attrs = attrs_raw if isinstance(attrs_raw, dict) else {}
    guard: dict[str, Any] = {
        "entity_id": plan.entity_id,
        "state": str(snapshot.get("state", "")),
    }

    expected_attribute = plan.expected.get("attribute")
    if expected_attribute == "brightness_pct":
        guard["brightness"] = attrs.get("brightness")
    elif isinstance(expected_attribute, str) and expected_attribute:
        guard[expected_attribute] = attrs.get(expected_attribute)

    for key in ("temperature", "hvac_mode", "fan_mode", "swing_mode", "preset_mode"):
        if key in plan.data and key in attrs:
            guard[key] = attrs.get(key)
    if plan.domain == "cover" and "current_position" in attrs:
        guard["current_position"] = attrs.get("current_position")
    return guard


def classify_risk(plan: ActionPlan) -> RiskLevel:
    """Conservative generic defaults; per-user policy can require more approval."""

    exact = (plan.domain, plan.action)
    if plan.domain == "archive" and plan.action in {"move", "delete", "restore"}:
        return RiskLevel.MEDIUM
    if exact in {
        ("lock", "unlock"),
        ("alarm_control_panel", "alarm_disarm"),
        ("homeassistant", "restart"),
        ("homeassistant", "stop"),
    }:
        return RiskLevel.CRITICAL
    if plan.domain in {"script", "automation", "button", "update"}:
        return RiskLevel.HIGH
    if exact in {
        ("cover", "open_cover"),
        ("cover", "set_cover_position"),
        ("vacuum", "send_command"),
    }:
        return RiskLevel.MEDIUM
    if plan.domain in {
        "light",
        "switch",
        "climate",
        "fan",
        "media_player",
        "vacuum",
        "cover",
        "number",
        "select",
        "input_boolean",
    }:
        return RiskLevel.LOW
    return RiskLevel.HIGH


def _target_matches(plan: ActionPlan, candidates: frozenset[str]) -> bool:
    return bool(candidates.intersection({plan.device_id, plan.entity_id}))


def authorize_plan(
    plan: ActionPlan,
    *,
    policy: UserPolicy,
    provenance: RequestProvenance,
    approval_authorized: bool = False,
) -> AuthorizationDecision:
    """Fail closed before any Home Assistant side effect is attempted."""

    fingerprint = plan_fingerprint(plan)
    risk = classify_risk(plan)

    if not policy.user_key.strip():
        return AuthorizationDecision(False, "missing_user", risk, False, False, fingerprint)
    if (
        "*" not in policy.allowed_capabilities
        and plan.capability not in policy.allowed_capabilities
    ):
        return AuthorizationDecision(
            False,
            "capability_not_allowed",
            risk,
            False,
            False,
            fingerprint,
        )
    if plan.capability in policy.denied_capabilities:
        return AuthorizationDecision(False, "capability_denied", risk, False, False, fingerprint)
    if "*" not in policy.allowed_domains and plan.domain not in policy.allowed_domains:
        return AuthorizationDecision(False, "domain_not_allowed", risk, False, False, fingerprint)
    action_key = f"{plan.domain}.{plan.action}"
    if action_key in policy.denied_actions or plan.action in policy.denied_actions:
        return AuthorizationDecision(False, "action_denied", risk, False, False, fingerprint)

    # These are source-authority vetoes.  A later "yes" must create a new,
    # explicit request rather than turning a negated/literal mention into an action.
    if provenance.negated:
        return AuthorizationDecision(False, "source_negated", risk, False, False, fingerprint)
    if provenance.literal_name:
        return AuthorizationDecision(
            False,
            "literal_name_protected",
            risk,
            False,
            False,
            fingerprint,
        )

    approval_reasons: list[str] = []
    if provenance.question:
        approval_reasons.append("question_without_execution_authority")
    if provenance.explicit_target_ids and not _target_matches(plan, provenance.explicit_target_ids):
        approval_reasons.append("explicit_target_mismatch")
    target_allowed = _target_matches(plan, provenance.allowed_target_ids)
    if provenance.source_kind == "context" and not target_allowed:
        approval_reasons.append("context_target_not_authorized")
    if provenance.reference_only and provenance.source_kind != "context" and not target_allowed:
        approval_reasons.append("reference_without_context_provenance")
    if (
        not provenance.same_text
        and not provenance.explicit_target_ids
        and provenance.source_kind != "context"
        and not target_allowed
    ):
        approval_reasons.append("novel_mutating_target")
    if plan.requires_confirmation:
        approval_reasons.append("plan_requires_approval")
    if risk > policy.max_without_approval:
        approval_reasons.append("risk_requires_approval")

    if approval_reasons and not approval_authorized:
        return AuthorizationDecision(
            False,
            approval_reasons[0],
            risk,
            True,
            False,
            fingerprint,
        )
    if approval_reasons and not policy.can_approve:
        return AuthorizationDecision(
            False,
            "user_cannot_approve",
            risk,
            True,
            False,
            fingerprint,
        )
    return AuthorizationDecision(
        True,
        "authorized",
        risk,
        bool(approval_reasons),
        bool(approval_authorized),
        fingerprint,
    )


class ApprovalStore:
    """SQLite approval ledger storing only token hashes, never raw tokens."""

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
            CREATE TABLE IF NOT EXISTS approval_grants (
                approval_id TEXT PRIMARY KEY,
                token_hash TEXT NOT NULL UNIQUE,
                user_key TEXT NOT NULL,
                plan_fingerprint TEXT NOT NULL,
                state_fingerprint TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                created_ts INTEGER NOT NULL,
                expires_ts INTEGER NOT NULL,
                consumed_ts INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS ix_approval_grants_user
                ON approval_grants(user_key, created_ts DESC);
            CREATE INDEX IF NOT EXISTS ix_approval_grants_expiry
                ON approval_grants(expires_ts, consumed_ts);
            """
        )
        self._db.commit()

    def issue(
        self,
        *,
        user_key: str,
        plan: ActionPlan,
        state_guard: dict[str, Any],
        summary: str = "",
        ttl_seconds: int = 300,
        now_ts: int | None = None,
    ) -> ApprovalGrant:
        if not user_key.strip():
            raise ValueError("user_key_required")
        now = int(now_ts or time.time())
        ttl = max(15, min(int(ttl_seconds), 86400))
        token = secrets.token_urlsafe(32)
        token_hash = _sha256_text(token)
        approval_id = f"ap_{secrets.token_hex(12)}"
        plan_hash = plan_fingerprint(plan)
        state_hash = state_fingerprint(state_guard)
        expires = now + ttl
        with self._db:
            self._db.execute(
                """
                INSERT INTO approval_grants(
                    approval_id,token_hash,user_key,plan_fingerprint,state_fingerprint,
                    summary,created_ts,expires_ts,consumed_ts
                ) VALUES(?,?,?,?,?,?,?,?,0)
                """,
                (
                    approval_id,
                    token_hash,
                    user_key,
                    plan_hash,
                    state_hash,
                    str(summary)[:1000],
                    now,
                    expires,
                ),
            )
        return ApprovalGrant(
            approval_id=approval_id,
            token=token,
            user_key=user_key,
            plan_fingerprint=plan_hash,
            state_fingerprint=state_hash,
            expires_at=expires,
        )

    def consume(
        self,
        *,
        token: str,
        user_key: str,
        plan: ActionPlan,
        state_guard: dict[str, Any],
        now_ts: int | None = None,
    ) -> ApprovalValidation:
        if not token or not user_key.strip():
            return ApprovalValidation(False, "missing_approval")
        now = int(now_ts or time.time())
        token_hash = _sha256_text(token)
        wanted_plan = plan_fingerprint(plan)
        wanted_state = state_fingerprint(state_guard)

        self._db.execute("BEGIN IMMEDIATE")
        try:
            row = self._db.execute(
                "SELECT * FROM approval_grants WHERE token_hash=?",
                (token_hash,),
            ).fetchone()
            if row is None:
                self._db.rollback()
                return ApprovalValidation(False, "approval_not_found")
            if int(row["consumed_ts"]) > 0:
                self._db.rollback()
                return ApprovalValidation(False, "approval_already_used", row["approval_id"])
            if int(row["expires_ts"]) < now:
                self._db.rollback()
                return ApprovalValidation(False, "approval_expired", row["approval_id"])
            if not hmac.compare_digest(str(row["user_key"]), user_key):
                self._db.rollback()
                return ApprovalValidation(False, "approval_wrong_user", row["approval_id"])
            if not hmac.compare_digest(str(row["plan_fingerprint"]), wanted_plan):
                self._db.rollback()
                return ApprovalValidation(False, "approval_plan_changed", row["approval_id"])
            if not hmac.compare_digest(str(row["state_fingerprint"]), wanted_state):
                self._db.rollback()
                return ApprovalValidation(False, "approval_state_changed", row["approval_id"])

            updated = self._db.execute(
                """
                UPDATE approval_grants
                SET consumed_ts=?
                WHERE approval_id=? AND consumed_ts=0
                """,
                (now, row["approval_id"]),
            )
            if updated.rowcount != 1:
                self._db.rollback()
                return ApprovalValidation(False, "approval_race_lost", row["approval_id"])
            self._db.commit()
            return ApprovalValidation(
                True,
                "approved",
                row["approval_id"],
                wanted_plan,
                wanted_state,
            )
        except Exception:
            self._db.rollback()
            raise

    def purge_expired(self, *, now_ts: int | None = None) -> int:
        now = int(now_ts or time.time())
        with self._db:
            result = self._db.execute(
                "DELETE FROM approval_grants WHERE expires_ts < ? AND consumed_ts > 0",
                (now,),
            )
        return int(result.rowcount)
