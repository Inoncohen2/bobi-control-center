"""Durable local scheduler for Bobi Next.

Scheduled Bobi actions live in Bobi storage, not HA timers/helpers/automations.
The store uses atomic leases so a job cannot be executed twice by concurrent
workers. Jobs store semantic/action payloads; live HA state and permissions are
re-evaluated when the job actually runs.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True, frozen=True)
class ScheduledJob:
    job_id: str
    user_key: str
    run_at_ts: int
    payload: dict[str, Any]
    state: str
    recurrence_seconds: int = 0
    attempts: int = 0
    owner_token: str = ""
    lease_until_ts: int = 0
    last_error: str = ""


class ScheduleStore:
    """SQLite-backed job queue with fail-closed ownership semantics."""

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
            CREATE TABLE IF NOT EXISTS scheduled_jobs (
                job_id TEXT PRIMARY KEY,
                user_key TEXT NOT NULL,
                run_at_ts INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                recurrence_seconds INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0,
                owner_token TEXT NOT NULL DEFAULT '',
                lease_until_ts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                created_ts INTEGER NOT NULL,
                updated_ts INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_scheduled_jobs_due
                ON scheduled_jobs(state, run_at_ts, lease_until_ts);
            CREATE INDEX IF NOT EXISTS ix_scheduled_jobs_user
                ON scheduled_jobs(user_key, created_ts DESC);
            """
        )
        self._db.commit()

    @staticmethod
    def _row(row: sqlite3.Row | None) -> ScheduledJob | None:
        if row is None:
            return None
        payload = json.loads(row["payload_json"] or "{}")
        if not isinstance(payload, dict):
            payload = {}
        return ScheduledJob(
            job_id=row["job_id"],
            user_key=row["user_key"],
            run_at_ts=int(row["run_at_ts"]),
            payload=payload,
            state=row["state"],
            recurrence_seconds=int(row["recurrence_seconds"]),
            attempts=int(row["attempts"]),
            owner_token=row["owner_token"],
            lease_until_ts=int(row["lease_until_ts"]),
            last_error=row["last_error"],
        )

    def create(
        self,
        *,
        job_id: str,
        user_key: str,
        run_at_ts: int,
        payload: dict[str, Any],
        recurrence_seconds: int = 0,
        now_ts: int | None = None,
    ) -> ScheduledJob:
        now = int(now_ts or time.time())
        if int(run_at_ts) <= 0:
            raise ValueError("invalid_run_at")
        if recurrence_seconds < 0:
            raise ValueError("invalid_recurrence")
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        try:
            with self._db:
                self._db.execute(
                    """
                    INSERT INTO scheduled_jobs(
                        job_id,user_key,run_at_ts,payload_json,state,
                        recurrence_seconds,created_ts,updated_ts
                    ) VALUES(?,?,?,?,?,?,?,?)
                    """,
                    (
                        job_id,
                        user_key,
                        int(run_at_ts),
                        encoded,
                        "pending",
                        int(recurrence_seconds),
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("duplicate_job_id") from exc
        job = self.get(job_id)
        if job is None:
            raise RuntimeError("scheduled_job_not_persisted")
        return job

    def get(self, job_id: str) -> ScheduledJob | None:
        row = self._db.execute(
            "SELECT * FROM scheduled_jobs WHERE job_id=?",
            (job_id,),
        ).fetchone()
        return self._row(row)

    def list_for_user(
        self,
        user_key: str,
        *,
        include_terminal: bool = False,
        limit: int = 100,
    ) -> tuple[ScheduledJob, ...]:
        terminal = "" if include_terminal else "AND state NOT IN ('completed','cancelled')"
        rows = self._db.execute(
            f"""
            SELECT * FROM scheduled_jobs
            WHERE user_key=? {terminal}
            ORDER BY run_at_ts, created_ts
            LIMIT ?
            """,
            (user_key, max(1, min(int(limit), 500))),
        ).fetchall()
        return tuple(job for row in rows if (job := self._row(row)) is not None)

    def claim_due(
        self,
        *,
        owner_token: str,
        now_ts: int | None = None,
        lease_seconds: int = 60,
        limit: int = 20,
    ) -> tuple[ScheduledJob, ...]:
        """Atomically lease due jobs to one worker.

        Expired running leases can be reclaimed after a crash. A successful
        claim increments attempts once and returns only jobs owned by this call.
        """

        if not owner_token.strip():
            raise ValueError("owner_token_required")
        now = int(now_ts or time.time())
        lease_until = now + max(5, int(lease_seconds))
        bounded_limit = max(1, min(int(limit), 100))

        self._db.execute("BEGIN IMMEDIATE")
        try:
            rows = self._db.execute(
                """
                SELECT job_id FROM scheduled_jobs
                WHERE run_at_ts <= ?
                  AND (
                    state IN ('pending','retry')
                    OR (state='running' AND lease_until_ts < ?)
                  )
                ORDER BY run_at_ts, created_ts
                LIMIT ?
                """,
                (now, now, bounded_limit),
            ).fetchall()
            job_ids = [row["job_id"] for row in rows]
            for job_id in job_ids:
                self._db.execute(
                    """
                    UPDATE scheduled_jobs
                    SET state='running', owner_token=?, lease_until_ts=?,
                        attempts=attempts+1, updated_ts=?
                    WHERE job_id=?
                    """,
                    (owner_token, lease_until, now, job_id),
                )
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise

        return tuple(
            job
            for job_id in job_ids
            if (job := self.get(job_id)) is not None and job.owner_token == owner_token
        )

    def complete(
        self,
        job_id: str,
        *,
        owner_token: str,
        now_ts: int | None = None,
    ) -> ScheduledJob:
        now = int(now_ts or time.time())
        job = self.get(job_id)
        if job is None:
            raise KeyError("job_not_found")
        if job.state != "running" or job.owner_token != owner_token:
            raise PermissionError("job_not_owned")

        if job.recurrence_seconds > 0:
            next_run = max(job.run_at_ts + job.recurrence_seconds, now + 1)
            state = "pending"
        else:
            next_run = job.run_at_ts
            state = "completed"

        with self._db:
            self._db.execute(
                """
                UPDATE scheduled_jobs
                SET state=?, run_at_ts=?, owner_token='', lease_until_ts=0,
                    last_error='', updated_ts=?
                WHERE job_id=? AND state='running' AND owner_token=?
                """,
                (state, next_run, now, job_id, owner_token),
            )
        updated = self.get(job_id)
        if updated is None:
            raise RuntimeError("job_disappeared")
        return updated

    def hold_for_approval(
        self,
        job_id: str,
        *,
        owner_token: str,
        reason: str,
        now_ts: int | None = None,
    ) -> ScheduledJob:
        """Pause a claimed job without retrying or performing a side effect."""

        now = int(now_ts or time.time())
        job = self.get(job_id)
        if job is None:
            raise KeyError("job_not_found")
        if job.state != "running" or job.owner_token != owner_token:
            raise PermissionError("job_not_owned")
        with self._db:
            self._db.execute(
                """
                UPDATE scheduled_jobs
                SET state='awaiting_approval', owner_token='', lease_until_ts=0,
                    last_error=?, updated_ts=?
                WHERE job_id=? AND state='running' AND owner_token=?
                """,
                (str(reason)[:1000], now, job_id, owner_token),
            )
        updated = self.get(job_id)
        if updated is None:
            raise RuntimeError("job_disappeared")
        return updated

    def resume_after_approval(
        self,
        job_id: str,
        *,
        now_ts: int | None = None,
    ) -> ScheduledJob:
        """Make an approval-held job eligible for a fresh policy/state evaluation."""

        now = int(now_ts or time.time())
        job = self.get(job_id)
        if job is None:
            raise KeyError("job_not_found")
        if job.state != "awaiting_approval":
            raise RuntimeError("job_not_awaiting_approval")
        with self._db:
            self._db.execute(
                """
                UPDATE scheduled_jobs
                SET state='pending', run_at_ts=?, owner_token='', lease_until_ts=0,
                    last_error='', updated_ts=?
                WHERE job_id=? AND state='awaiting_approval'
                """,
                (now, now, job_id),
            )
        updated = self.get(job_id)
        if updated is None:
            raise RuntimeError("job_disappeared")
        return updated

    def fail(
        self,
        job_id: str,
        *,
        owner_token: str,
        error: str,
        retry_at_ts: int | None = None,
        now_ts: int | None = None,
    ) -> ScheduledJob:
        now = int(now_ts or time.time())
        job = self.get(job_id)
        if job is None:
            raise KeyError("job_not_found")
        if job.state != "running" or job.owner_token != owner_token:
            raise PermissionError("job_not_owned")
        retry_at = int(retry_at_ts or 0)
        state = "retry" if retry_at > now else "failed"
        run_at = retry_at if state == "retry" else job.run_at_ts
        with self._db:
            self._db.execute(
                """
                UPDATE scheduled_jobs
                SET state=?, run_at_ts=?, owner_token='', lease_until_ts=0,
                    last_error=?, updated_ts=?
                WHERE job_id=? AND state='running' AND owner_token=?
                """,
                (state, run_at, str(error)[:1000], now, job_id, owner_token),
            )
        updated = self.get(job_id)
        if updated is None:
            raise RuntimeError("job_disappeared")
        return updated

    def cancel(self, job_id: str, *, now_ts: int | None = None) -> ScheduledJob:
        now = int(now_ts or time.time())
        job = self.get(job_id)
        if job is None:
            raise KeyError("job_not_found")
        if job.state == "running":
            raise RuntimeError("job_currently_running")
        if job.state in {"completed", "cancelled"}:
            return job
        with self._db:
            self._db.execute(
                """
                UPDATE scheduled_jobs
                SET state='cancelled', owner_token='', lease_until_ts=0, updated_ts=?
                WHERE job_id=?
                """,
                (now, job_id),
            )
        updated = self.get(job_id)
        if updated is None:
            raise RuntimeError("job_disappeared")
        return updated
