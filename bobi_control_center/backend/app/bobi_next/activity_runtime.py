"""Runtime glue for verified activity recording and exactly-once undo requests."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .activity import ActivityLedger, UndoResult, undo_latest
from .authorization import UserPolicy
from .executor import ExecutionResult, HAControlClient
from .pending_approval import PendingApprovalStore
from .request_ledger import RequestLedger


class ActivityRecordingHAClient:
    """HA client decorator that records only verified, user-owned mutations."""

    def __init__(
        self,
        delegate: HAControlClient,
        *,
        activity: ActivityLedger,
        requests: RequestLedger,
    ) -> None:
        self.delegate = delegate
        self.activity = activity
        self.requests = requests

    async def call_service(self, domain: str, service: str, data: dict[str, Any]) -> Any:
        return await self.delegate.call_service(domain, service, data)

    async def get_state(self, entity_id: str) -> dict[str, Any] | None:
        return await self.delegate.get_state(entity_id)

    def record_verified_execution(self, execution: ExecutionResult) -> None:
        if execution.plan.request_id.startswith("undo:"):
            return
        request = self.requests.get(execution.plan.request_id)
        if request is None:
            return
        self.activity.record_verified(
            user_key=request.user_key,
            execution=execution,
            created_ts=int(time.time()),
        )


@dataclass(slots=True, frozen=True)
class UndoRequestRecord:
    request_id: str
    user_key: str
    state: str
    outcome: str
    reason: str
    activity_id: int
    approval_request_id: str
    created_ts: int
    updated_ts: int

    def as_result(self) -> UndoResult:
        return UndoResult(
            self.outcome,
            self.reason,
            self.activity_id,
            self.approval_request_id,
        )


class UndoRequestStore:
    """Exactly-once ledger for a transport message that asks Bobi to undo."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS undo_requests (
                request_id TEXT PRIMARY KEY,
                user_key TEXT NOT NULL,
                state TEXT NOT NULL,
                outcome TEXT NOT NULL DEFAULT '',
                reason TEXT NOT NULL DEFAULT '',
                activity_id INTEGER NOT NULL DEFAULT 0,
                approval_request_id TEXT NOT NULL DEFAULT '',
                created_ts INTEGER NOT NULL,
                updated_ts INTEGER NOT NULL
            )
            """
        )
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    @staticmethod
    def _row(row: sqlite3.Row | None) -> UndoRequestRecord | None:
        if row is None:
            return None
        return UndoRequestRecord(
            request_id=str(row["request_id"]),
            user_key=str(row["user_key"]),
            state=str(row["state"]),
            outcome=str(row["outcome"]),
            reason=str(row["reason"]),
            activity_id=int(row["activity_id"]),
            approval_request_id=str(row["approval_request_id"]),
            created_ts=int(row["created_ts"]),
            updated_ts=int(row["updated_ts"]),
        )

    def get(self, request_id: str) -> UndoRequestRecord | None:
        row = self._db.execute(
            "SELECT * FROM undo_requests WHERE request_id=?",
            (request_id,),
        ).fetchone()
        return self._row(row)

    def claim(self, *, request_id: str, user_key: str, now_ts: int) -> UndoRequestRecord:
        if not request_id.strip() or not user_key.strip():
            raise ValueError("invalid_undo_request_identity")
        self._db.execute("BEGIN IMMEDIATE")
        try:
            row = self._db.execute(
                "SELECT * FROM undo_requests WHERE request_id=?",
                (request_id,),
            ).fetchone()
            existing = self._row(row)
            if existing is not None:
                self._db.rollback()
                if existing.user_key != user_key:
                    raise PermissionError("undo_request_user_mismatch")
                return existing
            self._db.execute(
                """
                INSERT INTO undo_requests(
                    request_id,user_key,state,created_ts,updated_ts
                ) VALUES(?,?,'running',?,?)
                """,
                (request_id, user_key, now_ts, now_ts),
            )
            self._db.commit()
        except Exception:
            if self._db.in_transaction:
                self._db.rollback()
            raise
        created = self.get(request_id)
        if created is None:
            raise RuntimeError("undo_request_not_persisted")
        return created

    def complete(
        self,
        request_id: str,
        result: UndoResult,
        *,
        now_ts: int,
    ) -> UndoRequestRecord:
        with self._db:
            updated = self._db.execute(
                """
                UPDATE undo_requests
                SET state='completed', outcome=?, reason=?, activity_id=?,
                    approval_request_id=?, updated_ts=?
                WHERE request_id=? AND state='running'
                """,
                (
                    result.outcome,
                    result.reason,
                    result.activity_id,
                    result.approval_request_id,
                    now_ts,
                    request_id,
                ),
            )
        if updated.rowcount != 1:
            existing = self.get(request_id)
            if existing is None:
                raise RuntimeError("undo_request_disappeared")
            return existing
        completed = self.get(request_id)
        if completed is None:
            raise RuntimeError("undo_request_disappeared")
        return completed


async def undo_once(
    requests: UndoRequestStore,
    activity: ActivityLedger,
    client: HAControlClient,
    *,
    request_id: str,
    user_key: str,
    policy: UserPolicy,
    pending_approvals: PendingApprovalStore | None,
    now_ts: int,
    verification_attempts: int = 3,
    verification_delay: float = 0.35,
) -> UndoResult:
    claim = requests.claim(request_id=request_id, user_key=user_key, now_ts=now_ts)
    if claim.state == "completed":
        return claim.as_result()
    if claim.state != "running":
        return UndoResult("blocked", "undo_request_not_owned")

    result = await undo_latest(
        activity,
        client,
        user_key=user_key,
        policy=policy,
        undo_request_id=request_id,
        pending_approvals=pending_approvals,
        now_ts=now_ts,
        verification_attempts=verification_attempts,
        verification_delay=verification_delay,
    )
    return requests.complete(request_id, result, now_ts=now_ts).as_result()
