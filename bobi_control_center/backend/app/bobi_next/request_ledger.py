"""Atomic request lifecycle ledger for Bobi Next.

A provider message may be delivered more than once and a worker may crash after
starting work.  This ledger gives every semantic request one owner at a time,
allows expired work to be reclaimed, and records a terminal outcome so the
engine cannot execute or reply twice for the same request id.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

_TERMINAL_STATES = {"completed", "failed", "ignored"}


@dataclass(slots=True, frozen=True)
class RequestRecord:
    request_id: str
    user_key: str
    state: str
    owner_token: str
    input_text: str
    terminal_kind: str
    outbound_message_id: str
    lease_until_ts: int
    attempts: int
    last_error: str
    created_ts: int
    updated_ts: int


@dataclass(slots=True, frozen=True)
class RequestClaim:
    record: RequestRecord
    claimed: bool
    reason: str


class RequestLedger:
    """SQLite request ownership with crash-safe leases and terminal dedupe."""

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
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS request_ledger (
                request_id TEXT PRIMARY KEY,
                user_key TEXT NOT NULL,
                state TEXT NOT NULL,
                owner_token TEXT NOT NULL DEFAULT '',
                input_text TEXT NOT NULL DEFAULT '',
                terminal_kind TEXT NOT NULL DEFAULT '',
                outbound_message_id TEXT NOT NULL DEFAULT '',
                lease_until_ts INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                created_ts INTEGER NOT NULL,
                updated_ts INTEGER NOT NULL
            )
            """
        )
        columns = {
            str(row["name"])
            for row in self._db.execute("PRAGMA table_info(request_ledger)").fetchall()
        }
        additions = {
            "lease_until_ts": "INTEGER NOT NULL DEFAULT 0",
            "attempts": "INTEGER NOT NULL DEFAULT 0",
            "last_error": "TEXT NOT NULL DEFAULT ''",
        }
        for name, declaration in additions.items():
            if name not in columns:
                self._db.execute(
                    f"ALTER TABLE request_ledger ADD COLUMN {name} {declaration}"
                )
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS ix_request_user ON request_ledger(user_key, updated_ts)"
        )
        self._db.commit()

    @staticmethod
    def _record(row: sqlite3.Row | None) -> RequestRecord | None:
        if row is None:
            return None
        keys = set(row.keys())
        return RequestRecord(
            request_id=str(row["request_id"]),
            user_key=str(row["user_key"]),
            state=str(row["state"]),
            owner_token=str(row["owner_token"]),
            input_text=str(row["input_text"]),
            terminal_kind=str(row["terminal_kind"]),
            outbound_message_id=str(row["outbound_message_id"]),
            lease_until_ts=int(row["lease_until_ts"]) if "lease_until_ts" in keys else 0,
            attempts=int(row["attempts"]) if "attempts" in keys else 0,
            last_error=str(row["last_error"]) if "last_error" in keys else "",
            created_ts=int(row["created_ts"]),
            updated_ts=int(row["updated_ts"]),
        )

    def get(self, request_id: str) -> RequestRecord | None:
        row = self._db.execute(
            "SELECT * FROM request_ledger WHERE request_id=?",
            (request_id,),
        ).fetchone()
        return self._record(row)

    def claim(
        self,
        *,
        request_id: str,
        user_key: str,
        input_text: str,
        owner_token: str,
        now_ts: int | None = None,
        lease_seconds: int = 120,
    ) -> RequestClaim:
        if not request_id.strip() or not user_key.strip() or not owner_token.strip():
            raise ValueError("invalid_request_identity")
        now = int(now_ts or time.time())
        lease_until = now + max(5, int(lease_seconds))

        self._db.execute("BEGIN IMMEDIATE")
        try:
            row = self._db.execute(
                "SELECT * FROM request_ledger WHERE request_id=?",
                (request_id,),
            ).fetchone()
            existing = self._record(row)
            if existing is None:
                self._db.execute(
                    """
                    INSERT INTO request_ledger(
                        request_id,user_key,state,owner_token,input_text,
                        lease_until_ts,attempts,created_ts,updated_ts
                    ) VALUES(?,?,'running',?,?,?,?,?,?)
                    """,
                    (
                        request_id,
                        user_key,
                        owner_token,
                        input_text[:4000],
                        lease_until,
                        1,
                        now,
                        now,
                    ),
                )
                self._db.commit()
                created = self.get(request_id)
                if created is None:
                    raise RuntimeError("request_not_persisted")
                return RequestClaim(created, True, "claimed_new")

            if existing.user_key != user_key:
                self._db.rollback()
                return RequestClaim(existing, False, "request_user_mismatch")
            if existing.state in _TERMINAL_STATES:
                self._db.rollback()
                return RequestClaim(existing, False, "request_terminal")
            if existing.state == "running" and existing.lease_until_ts >= now:
                self._db.rollback()
                return RequestClaim(existing, False, "request_owned")

            updated = self._db.execute(
                """
                UPDATE request_ledger
                SET state='running', owner_token=?, input_text=?, lease_until_ts=?,
                    attempts=attempts+1, last_error='', updated_ts=?
                WHERE request_id=?
                  AND state NOT IN ('completed','failed','ignored')
                  AND (state!='running' OR lease_until_ts < ?)
                """,
                (
                    owner_token,
                    input_text[:4000],
                    lease_until,
                    now,
                    request_id,
                    now,
                ),
            )
            if updated.rowcount != 1:
                self._db.rollback()
                current = self.get(request_id)
                if current is None:
                    raise RuntimeError("request_disappeared")
                return RequestClaim(current, False, "claim_race_lost")
            self._db.commit()
        except Exception:
            if self._db.in_transaction:
                self._db.rollback()
            raise

        claimed = self.get(request_id)
        if claimed is None:
            raise RuntimeError("request_disappeared")
        return RequestClaim(claimed, True, "claimed_recovery")

    def complete(
        self,
        request_id: str,
        *,
        owner_token: str,
        terminal_kind: str,
        outbound_message_id: str = "",
        now_ts: int | None = None,
    ) -> RequestRecord:
        return self._finish(
            request_id,
            owner_token=owner_token,
            state="completed",
            terminal_kind=terminal_kind,
            outbound_message_id=outbound_message_id,
            error="",
            now_ts=now_ts,
        )

    def ignore(
        self,
        request_id: str,
        *,
        owner_token: str,
        terminal_kind: str,
        now_ts: int | None = None,
    ) -> RequestRecord:
        return self._finish(
            request_id,
            owner_token=owner_token,
            state="ignored",
            terminal_kind=terminal_kind,
            error="",
            now_ts=now_ts,
        )

    def fail_terminal(
        self,
        request_id: str,
        *,
        owner_token: str,
        error: str,
        terminal_kind: str = "error",
        now_ts: int | None = None,
    ) -> RequestRecord:
        return self._finish(
            request_id,
            owner_token=owner_token,
            state="failed",
            terminal_kind=terminal_kind,
            error=error,
            now_ts=now_ts,
        )

    def retry(
        self,
        request_id: str,
        *,
        owner_token: str,
        error: str,
        now_ts: int | None = None,
    ) -> RequestRecord:
        now = int(now_ts or time.time())
        with self._db:
            updated = self._db.execute(
                """
                UPDATE request_ledger
                SET state='retry', owner_token='', lease_until_ts=0,
                    last_error=?, updated_ts=?
                WHERE request_id=? AND state='running' AND owner_token=?
                """,
                (str(error)[:1000], now, request_id, owner_token),
            )
        if updated.rowcount != 1:
            raise PermissionError("request_not_owned")
        record = self.get(request_id)
        if record is None:
            raise RuntimeError("request_disappeared")
        return record

    def _finish(
        self,
        request_id: str,
        *,
        owner_token: str,
        state: str,
        terminal_kind: str,
        error: str,
        outbound_message_id: str = "",
        now_ts: int | None = None,
    ) -> RequestRecord:
        now = int(now_ts or time.time())
        with self._db:
            updated = self._db.execute(
                """
                UPDATE request_ledger
                SET state=?, owner_token='', lease_until_ts=0, terminal_kind=?,
                    outbound_message_id=?, last_error=?, updated_ts=?
                WHERE request_id=? AND state='running' AND owner_token=?
                """,
                (
                    state,
                    terminal_kind,
                    outbound_message_id,
                    str(error)[:1000],
                    now,
                    request_id,
                    owner_token,
                ),
            )
        if updated.rowcount != 1:
            raise PermissionError("request_not_owned")
        record = self.get(request_id)
        if record is None:
            raise RuntimeError("request_disappeared")
        return record
