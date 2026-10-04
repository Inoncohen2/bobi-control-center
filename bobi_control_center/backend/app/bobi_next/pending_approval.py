"""Durable pending approvals for immediate Bobi Next requests.

The store persists the exact plans, provenance and state guards that the user was
asked to approve.  It deliberately never persists ApprovalStore bearer tokens.
A confirmation worker claims one pending request atomically, rechecks the live
state, then creates a short-lived single-use token only in process memory.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .authorization import RequestProvenance
from .models import ActionPlan


@dataclass(slots=True, frozen=True)
class PendingApproval:
    approval_request_id: str
    source_request_id: str
    user_key: str
    plans: tuple[ActionPlan, ...]
    provenance: RequestProvenance
    state_guards: tuple[dict[str, Any], ...]
    summary: str
    state: str
    owner_token: str
    lease_until_ts: int
    attempts: int
    created_ts: int
    expires_ts: int
    last_error: str


def _plan_payload(plan: ActionPlan) -> dict[str, Any]:
    return asdict(plan)


def _plan_from_payload(payload: dict[str, Any]) -> ActionPlan:
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


def _provenance_payload(provenance: RequestProvenance) -> dict[str, Any]:
    return {
        "source_kind": provenance.source_kind,
        "same_text": provenance.same_text,
        "explicit_target_ids": sorted(provenance.explicit_target_ids),
        "allowed_target_ids": sorted(provenance.allowed_target_ids),
        "negated": provenance.negated,
        "question": provenance.question,
        "literal_name": provenance.literal_name,
        "reference_only": provenance.reference_only,
    }


def _provenance_from_payload(payload: dict[str, Any]) -> RequestProvenance:
    return RequestProvenance(
        source_kind=str(payload.get("source_kind") or "direct"),
        same_text=bool(payload.get("same_text", True)),
        explicit_target_ids=frozenset(str(v) for v in payload.get("explicit_target_ids", [])),
        allowed_target_ids=frozenset(str(v) for v in payload.get("allowed_target_ids", [])),
        negated=bool(payload.get("negated", False)),
        question=bool(payload.get("question", False)),
        literal_name=bool(payload.get("literal_name", False)),
        reference_only=bool(payload.get("reference_only", False)),
    )


class PendingApprovalStore:
    """SQLite approval queue with atomic per-confirmation ownership."""

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
            CREATE TABLE IF NOT EXISTS pending_approval_requests (
                approval_request_id TEXT PRIMARY KEY,
                source_request_id TEXT NOT NULL UNIQUE,
                user_key TEXT NOT NULL,
                plans_json TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                state_guards_json TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                state TEXT NOT NULL DEFAULT 'pending',
                owner_token TEXT NOT NULL DEFAULT '',
                lease_until_ts INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0,
                created_ts INTEGER NOT NULL,
                expires_ts INTEGER NOT NULL,
                updated_ts INTEGER NOT NULL,
                last_error TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS ix_pending_approval_user
                ON pending_approval_requests(user_key, state, created_ts DESC);
            """
        )
        self._db.commit()

    @staticmethod
    def _row(row: sqlite3.Row | None) -> PendingApproval | None:
        if row is None:
            return None
        plans_raw = json.loads(row["plans_json"] or "[]")
        provenance_raw = json.loads(row["provenance_json"] or "{}")
        guards_raw = json.loads(row["state_guards_json"] or "[]")
        return PendingApproval(
            approval_request_id=str(row["approval_request_id"]),
            source_request_id=str(row["source_request_id"]),
            user_key=str(row["user_key"]),
            plans=tuple(_plan_from_payload(dict(item)) for item in plans_raw),
            provenance=_provenance_from_payload(dict(provenance_raw)),
            state_guards=tuple(dict(item) for item in guards_raw),
            summary=str(row["summary"]),
            state=str(row["state"]),
            owner_token=str(row["owner_token"]),
            lease_until_ts=int(row["lease_until_ts"]),
            attempts=int(row["attempts"]),
            created_ts=int(row["created_ts"]),
            expires_ts=int(row["expires_ts"]),
            last_error=str(row["last_error"]),
        )

    def get(self, approval_request_id: str) -> PendingApproval | None:
        row = self._db.execute(
            "SELECT * FROM pending_approval_requests WHERE approval_request_id=?",
            (approval_request_id,),
        ).fetchone()
        return self._row(row)

    def create(
        self,
        *,
        approval_request_id: str,
        source_request_id: str,
        user_key: str,
        plans: tuple[ActionPlan, ...],
        provenance: RequestProvenance,
        state_guards: tuple[dict[str, Any], ...],
        summary: str = "",
        ttl_seconds: int = 300,
        now_ts: int | None = None,
    ) -> PendingApproval:
        if not approval_request_id.strip() or not source_request_id.strip() or not user_key.strip():
            raise ValueError("invalid_pending_approval_identity")
        if not plans or len(plans) != len(state_guards):
            raise ValueError("invalid_pending_approval_plans")
        now = int(now_ts or time.time())
        expires = now + max(15, min(int(ttl_seconds), 3600))
        plans_json = json.dumps(
            [_plan_payload(plan) for plan in plans],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        provenance_json = json.dumps(
            _provenance_payload(provenance),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        guards_json = json.dumps(
            list(state_guards),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            with self._db:
                self._db.execute(
                    """
                    INSERT INTO pending_approval_requests(
                        approval_request_id,source_request_id,user_key,plans_json,
                        provenance_json,state_guards_json,summary,state,created_ts,
                        expires_ts,updated_ts
                    ) VALUES(?,?,?,?,?,?,?,'pending',?,?,?)
                    """,
                    (
                        approval_request_id,
                        source_request_id,
                        user_key,
                        plans_json,
                        provenance_json,
                        guards_json,
                        summary[:1000],
                        now,
                        expires,
                        now,
                    ),
                )
        except sqlite3.IntegrityError:
            row = self._db.execute(
                "SELECT * FROM pending_approval_requests WHERE source_request_id=?",
                (source_request_id,),
            ).fetchone()
            existing = self._row(row)
            if existing is None or existing.user_key != user_key:
                raise ValueError("pending_approval_conflict") from None
            return existing
        created = self.get(approval_request_id)
        if created is None:
            raise RuntimeError("pending_approval_not_persisted")
        return created

    def claim_latest(
        self,
        *,
        user_key: str,
        owner_token: str,
        now_ts: int | None = None,
        lease_seconds: int = 60,
    ) -> PendingApproval | None:
        if not user_key.strip() or not owner_token.strip():
            raise ValueError("invalid_approval_claim_identity")
        now = int(now_ts or time.time())
        lease_until = now + max(5, int(lease_seconds))
        self._db.execute("BEGIN IMMEDIATE")
        try:
            self._db.execute(
                """
                UPDATE pending_approval_requests
                SET state='expired', owner_token='', lease_until_ts=0, updated_ts=?
                WHERE user_key=? AND state='pending' AND expires_ts < ?
                """,
                (now, user_key, now),
            )
            row = self._db.execute(
                """
                SELECT * FROM pending_approval_requests
                WHERE user_key=?
                  AND expires_ts >= ?
                  AND (
                    state='pending'
                    OR (state='running' AND lease_until_ts < ?)
                  )
                ORDER BY created_ts DESC
                LIMIT 1
                """,
                (user_key, now, now),
            ).fetchone()
            pending = self._row(row)
            if pending is None:
                self._db.commit()
                return None
            updated = self._db.execute(
                """
                UPDATE pending_approval_requests
                SET state='running', owner_token=?, lease_until_ts=?,
                    attempts=attempts+1, updated_ts=?
                WHERE approval_request_id=?
                  AND (state='pending' OR (state='running' AND lease_until_ts < ?))
                """,
                (
                    owner_token,
                    lease_until,
                    now,
                    pending.approval_request_id,
                    now,
                ),
            )
            if updated.rowcount != 1:
                self._db.rollback()
                return None
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
        return self.get(pending.approval_request_id)

    def complete(
        self,
        approval_request_id: str,
        *,
        owner_token: str,
        now_ts: int | None = None,
    ) -> PendingApproval:
        return self._finish(
            approval_request_id,
            owner_token=owner_token,
            state="completed",
            error="",
            now_ts=now_ts,
        )

    def reject(
        self,
        approval_request_id: str,
        *,
        owner_token: str,
        reason: str = "rejected_by_user",
        now_ts: int | None = None,
    ) -> PendingApproval:
        return self._finish(
            approval_request_id,
            owner_token=owner_token,
            state="rejected",
            error=reason,
            now_ts=now_ts,
        )

    def fail(
        self,
        approval_request_id: str,
        *,
        owner_token: str,
        error: str,
        now_ts: int | None = None,
    ) -> PendingApproval:
        return self._finish(
            approval_request_id,
            owner_token=owner_token,
            state="failed",
            error=error,
            now_ts=now_ts,
        )

    def release(
        self,
        approval_request_id: str,
        *,
        owner_token: str,
        error: str,
        now_ts: int | None = None,
    ) -> PendingApproval:
        now = int(now_ts or time.time())
        with self._db:
            updated = self._db.execute(
                """
                UPDATE pending_approval_requests
                SET state='pending', owner_token='', lease_until_ts=0,
                    last_error=?, updated_ts=?
                WHERE approval_request_id=? AND state='running' AND owner_token=?
                """,
                (str(error)[:1000], now, approval_request_id, owner_token),
            )
        if updated.rowcount != 1:
            raise PermissionError("pending_approval_not_owned")
        result = self.get(approval_request_id)
        if result is None:
            raise RuntimeError("pending_approval_disappeared")
        return result

    def _finish(
        self,
        approval_request_id: str,
        *,
        owner_token: str,
        state: str,
        error: str,
        now_ts: int | None,
    ) -> PendingApproval:
        now = int(now_ts or time.time())
        with self._db:
            updated = self._db.execute(
                """
                UPDATE pending_approval_requests
                SET state=?, owner_token='', lease_until_ts=0,
                    last_error=?, updated_ts=?
                WHERE approval_request_id=? AND state='running' AND owner_token=?
                """,
                (state, str(error)[:1000], now, approval_request_id, owner_token),
            )
        if updated.rowcount != 1:
            raise PermissionError("pending_approval_not_owned")
        result = self.get(approval_request_id)
        if result is None:
            raise RuntimeError("pending_approval_disappeared")
        return result
