"""Durable proactive reminder delivery for Bobi Next.

Reminders are Bobi-owned jobs, not Home Assistant timers/helpers/automations.
The state machine separates loading from sending so a crash after a provider may
have accepted a message becomes ``uncertain`` and is never auto-retried. This
prefers a missed reminder over duplicate/spam side effects when delivery truth is
unknown.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .messaging import MessageTransport

_MAX_TEXT = 4000
_MAX_ID = 256
_MAX_CHAT = 512


@dataclass(slots=True, frozen=True)
class Reminder:
    reminder_id: str
    user_key: str
    provider_key: str
    chat_id: str
    text: str
    run_at_ts: int
    recurrence_seconds: int
    state: str
    occurrence: int = 0
    attempts: int = 0
    owner_token: str = ""
    lease_until_ts: int = 0
    provider_message_id: str = ""
    source_message_id: str = ""
    last_error: str = ""


def reminder_delivery_key(reminder: Reminder) -> str:
    raw = f"{reminder.provider_key}\0{reminder.reminder_id}\0{reminder.occurrence}".encode()
    return hashlib.sha256(raw).hexdigest()


def _next_future_run(run_at_ts: int, recurrence_seconds: int, now_ts: int) -> int:
    if recurrence_seconds <= 0:
        return run_at_ts
    if run_at_ts > now_ts:
        return run_at_ts
    skipped = ((now_ts - run_at_ts) // recurrence_seconds) + 1
    return run_at_ts + skipped * recurrence_seconds


class ReminderStore:
    """SQLite reminder queue with conservative crash semantics."""

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
            CREATE TABLE IF NOT EXISTS reminders (
                reminder_id TEXT PRIMARY KEY,
                user_key TEXT NOT NULL,
                provider_key TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                text TEXT NOT NULL,
                run_at_ts INTEGER NOT NULL,
                recurrence_seconds INTEGER NOT NULL DEFAULT 0,
                state TEXT NOT NULL DEFAULT 'pending',
                occurrence INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0,
                owner_token TEXT NOT NULL DEFAULT '',
                lease_until_ts INTEGER NOT NULL DEFAULT 0,
                provider_message_id TEXT NOT NULL DEFAULT '',
                source_message_id TEXT NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT '',
                created_ts INTEGER NOT NULL,
                updated_ts INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_reminders_due
                ON reminders(state, run_at_ts, lease_until_ts);
            CREATE INDEX IF NOT EXISTS ix_reminders_user
                ON reminders(user_key, run_at_ts, created_ts);
            """
        )
        self._db.commit()

    @staticmethod
    def _row(row: sqlite3.Row | None) -> Reminder | None:
        if row is None:
            return None
        return Reminder(
            reminder_id=str(row["reminder_id"]),
            user_key=str(row["user_key"]),
            provider_key=str(row["provider_key"]),
            chat_id=str(row["chat_id"]),
            text=str(row["text"]),
            run_at_ts=int(row["run_at_ts"]),
            recurrence_seconds=int(row["recurrence_seconds"]),
            state=str(row["state"]),
            occurrence=int(row["occurrence"]),
            attempts=int(row["attempts"]),
            owner_token=str(row["owner_token"]),
            lease_until_ts=int(row["lease_until_ts"]),
            provider_message_id=str(row["provider_message_id"]),
            source_message_id=str(row["source_message_id"]),
            last_error=str(row["last_error"]),
        )

    def create(
        self,
        *,
        reminder_id: str,
        user_key: str,
        provider_key: str,
        chat_id: str,
        text: str,
        run_at_ts: int,
        recurrence_seconds: int = 0,
        source_message_id: str = "",
        now_ts: int | None = None,
    ) -> Reminder:
        identifier = str(reminder_id or "").strip()[:_MAX_ID]
        user = str(user_key or "").strip()[:_MAX_ID]
        provider = str(provider_key or "").strip()[:_MAX_ID]
        chat = str(chat_id or "").strip()[:_MAX_CHAT]
        content = " ".join(str(text or "").strip().split())[:_MAX_TEXT]
        run_at = int(run_at_ts)
        recurrence = int(recurrence_seconds)
        if not identifier or not user or not provider or not chat:
            raise ValueError("reminder_identity_required")
        if not content:
            raise ValueError("reminder_text_required")
        if run_at <= 0:
            raise ValueError("reminder_run_at_invalid")
        if recurrence < 0:
            raise ValueError("reminder_recurrence_invalid")
        now = int(now_ts or time.time())
        try:
            with self._db:
                self._db.execute(
                    """
                    INSERT INTO reminders(
                        reminder_id,user_key,provider_key,chat_id,text,run_at_ts,
                        recurrence_seconds,state,occurrence,attempts,owner_token,
                        lease_until_ts,provider_message_id,source_message_id,
                        last_error,created_ts,updated_ts
                    ) VALUES(?,?,?,?,?,?,?,'pending',0,0,'',0,'',?,'',?,?)
                    """,
                    (
                        identifier,
                        user,
                        provider,
                        chat,
                        content,
                        run_at,
                        recurrence,
                        str(source_message_id or "")[:_MAX_ID],
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("duplicate_reminder_id") from exc
        reminder = self.get(identifier)
        if reminder is None:
            raise RuntimeError("reminder_not_persisted")
        return reminder

    def get(self, reminder_id: str) -> Reminder | None:
        row = self._db.execute(
            "SELECT * FROM reminders WHERE reminder_id=?",
            (str(reminder_id or "").strip(),),
        ).fetchone()
        return self._row(row)

    def list_for_user(
        self,
        user_key: str,
        *,
        include_terminal: bool = False,
        limit: int = 100,
    ) -> tuple[Reminder, ...]:
        terminal = "" if include_terminal else "AND state NOT IN ('sent','cancelled','failed')"
        rows = self._db.execute(
            f"""
            SELECT * FROM reminders
            WHERE user_key=? {terminal}
            ORDER BY run_at_ts, created_ts
            LIMIT ?
            """,
            (str(user_key), max(1, min(int(limit), 500))),
        ).fetchall()
        return tuple(item for row in rows if (item := self._row(row)) is not None)

    def claim_due(
        self,
        *,
        owner_token: str,
        now_ts: int | None = None,
        lease_seconds: int = 90,
    ) -> Reminder | None:
        owner = str(owner_token or "").strip()
        if not owner:
            raise ValueError("reminder_owner_required")
        now = int(now_ts or time.time())
        lease_until = now + max(5, int(lease_seconds))
        self._db.execute("BEGIN IMMEDIATE")
        try:
            # Loading means no provider call has started and is safe to retry.
            self._db.execute(
                """
                UPDATE reminders
                SET state='retry', owner_token='', lease_until_ts=0,
                    last_error='loading_lease_expired', updated_ts=?
                WHERE state='loading' AND lease_until_ts < ?
                """,
                (now, now),
            )
            # Sending may already have reached the provider; never auto-repeat.
            self._db.execute(
                """
                UPDATE reminders
                SET state='uncertain', owner_token='', lease_until_ts=0,
                    last_error='sending_lease_expired', updated_ts=?
                WHERE state='sending' AND lease_until_ts < ?
                """,
                (now, now),
            )
            row = self._db.execute(
                """
                SELECT reminder_id FROM reminders
                WHERE state IN ('pending','retry') AND run_at_ts <= ?
                ORDER BY run_at_ts, created_ts LIMIT 1
                """,
                (now,),
            ).fetchone()
            if row is None:
                self._db.commit()
                return None
            reminder_id = str(row["reminder_id"])
            self._db.execute(
                """
                UPDATE reminders
                SET state='loading', owner_token=?, lease_until_ts=?,
                    attempts=attempts+1, last_error='', updated_ts=?
                WHERE reminder_id=?
                """,
                (owner, lease_until, now, reminder_id),
            )
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
        reminder = self.get(reminder_id)
        if reminder is None or reminder.owner_token != owner:
            raise RuntimeError("reminder_claim_failed")
        return reminder

    def begin_send(
        self,
        reminder: Reminder,
        *,
        owner_token: str,
        now_ts: int | None = None,
        lease_seconds: int = 90,
    ) -> Reminder:
        now = int(now_ts or time.time())
        lease_until = now + max(5, int(lease_seconds))
        with self._db:
            result = self._db.execute(
                """
                UPDATE reminders SET state='sending', lease_until_ts=?, updated_ts=?
                WHERE reminder_id=? AND state='loading' AND owner_token=?
                """,
                (lease_until, now, reminder.reminder_id, owner_token),
            )
        if result.rowcount != 1:
            raise PermissionError("reminder_not_owned")
        updated = self.get(reminder.reminder_id)
        if updated is None:
            raise RuntimeError("reminder_disappeared")
        return updated

    def fail_before_send(
        self,
        reminder: Reminder,
        *,
        owner_token: str,
        error: str,
        retry_at_ts: int = 0,
        now_ts: int | None = None,
    ) -> Reminder:
        now = int(now_ts or time.time())
        retry_at = max(0, int(retry_at_ts))
        state = "retry" if retry_at else "failed"
        run_at = retry_at or reminder.run_at_ts
        with self._db:
            result = self._db.execute(
                """
                UPDATE reminders
                SET state=?, run_at_ts=?, owner_token='', lease_until_ts=0,
                    last_error=?, updated_ts=?
                WHERE reminder_id=? AND state='loading' AND owner_token=?
                """,
                (
                    state,
                    run_at,
                    str(error)[:1000],
                    now,
                    reminder.reminder_id,
                    owner_token,
                ),
            )
        if result.rowcount != 1:
            raise PermissionError("reminder_not_owned")
        updated = self.get(reminder.reminder_id)
        if updated is None:
            raise RuntimeError("reminder_disappeared")
        return updated

    def mark_uncertain(
        self,
        reminder: Reminder,
        *,
        owner_token: str,
        error: str,
        now_ts: int | None = None,
    ) -> Reminder:
        now = int(now_ts or time.time())
        with self._db:
            result = self._db.execute(
                """
                UPDATE reminders
                SET state='uncertain', owner_token='', lease_until_ts=0,
                    last_error=?, updated_ts=?
                WHERE reminder_id=? AND state='sending' AND owner_token=?
                """,
                (str(error)[:1000], now, reminder.reminder_id, owner_token),
            )
        if result.rowcount != 1:
            raise PermissionError("reminder_not_owned")
        updated = self.get(reminder.reminder_id)
        if updated is None:
            raise RuntimeError("reminder_disappeared")
        return updated

    def complete(
        self,
        reminder: Reminder,
        *,
        owner_token: str,
        provider_message_id: str,
        now_ts: int | None = None,
    ) -> Reminder:
        provider_id = str(provider_message_id or "").strip()
        if not provider_id:
            raise ValueError("reminder_provider_message_id_required")
        now = int(now_ts or time.time())
        if reminder.recurrence_seconds > 0:
            state = "pending"
            next_run = _next_future_run(
                reminder.run_at_ts + reminder.recurrence_seconds,
                reminder.recurrence_seconds,
                now,
            )
            occurrence = reminder.occurrence + 1
            attempts = 0
            stored_provider_id = ""
        else:
            state = "sent"
            next_run = reminder.run_at_ts
            occurrence = reminder.occurrence
            attempts = reminder.attempts
            stored_provider_id = provider_id
        with self._db:
            result = self._db.execute(
                """
                UPDATE reminders
                SET state=?, run_at_ts=?, occurrence=?, attempts=?, owner_token='',
                    lease_until_ts=0, provider_message_id=?, last_error='', updated_ts=?
                WHERE reminder_id=? AND state='sending' AND owner_token=?
                """,
                (
                    state,
                    next_run,
                    occurrence,
                    attempts,
                    stored_provider_id,
                    now,
                    reminder.reminder_id,
                    owner_token,
                ),
            )
        if result.rowcount != 1:
            raise PermissionError("reminder_not_owned")
        updated = self.get(reminder.reminder_id)
        if updated is None:
            raise RuntimeError("reminder_disappeared")
        return updated

    def cancel(self, reminder_id: str, *, user_key: str, now_ts: int | None = None) -> Reminder:
        now = int(now_ts or time.time())
        with self._db:
            result = self._db.execute(
                """
                UPDATE reminders
                SET state='cancelled', owner_token='', lease_until_ts=0, updated_ts=?
                WHERE reminder_id=? AND user_key=?
                  AND state IN ('pending','retry','loading')
                """,
                (now, reminder_id, user_key),
            )
        if result.rowcount != 1:
            raise ValueError("reminder_not_cancellable")
        updated = self.get(reminder_id)
        if updated is None:
            raise RuntimeError("reminder_disappeared")
        return updated

    def resolve_uncertain(
        self,
        reminder_id: str,
        *,
        resolution: str,
        provider_message_id: str = "",
        now_ts: int | None = None,
    ) -> Reminder:
        if resolution not in {"sent", "retry", "cancelled"}:
            raise ValueError("reminder_resolution_invalid")
        reminder = self.get(reminder_id)
        if reminder is None or reminder.state != "uncertain":
            raise ValueError("reminder_not_uncertain")
        now = int(now_ts or time.time())
        if resolution == "sent":
            if not provider_message_id.strip():
                raise ValueError("reminder_provider_message_id_required")
            # Re-enter the normal completion logic under a temporary owned state.
            owner = f"reconcile:{reminder_id}"
            with self._db:
                self._db.execute(
                    """
                    UPDATE reminders SET state='sending', owner_token=?, updated_ts=?
                    WHERE reminder_id=? AND state='uncertain'
                    """,
                    (owner, now, reminder_id),
                )
            current = self.get(reminder_id)
            if current is None:
                raise RuntimeError("reminder_disappeared")
            return self.complete(
                current,
                owner_token=owner,
                provider_message_id=provider_message_id,
                now_ts=now,
            )
        with self._db:
            self._db.execute(
                """
                UPDATE reminders
                SET state=?, run_at_ts=?, owner_token='', lease_until_ts=0,
                    last_error='', updated_ts=?
                WHERE reminder_id=? AND state='uncertain'
                """,
                (
                    resolution,
                    now if resolution == "retry" else reminder.run_at_ts,
                    now,
                    reminder_id,
                ),
            )
        updated = self.get(reminder_id)
        if updated is None:
            raise RuntimeError("reminder_disappeared")
        return updated


TransportProvider = Callable[[str], MessageTransport]
UserEnabled = Callable[[str], bool]


async def process_next_reminder(
    store: ReminderStore,
    transport_for: TransportProvider,
    *,
    owner_token: str,
    now_ts: int | None = None,
    lease_seconds: int = 90,
    retry_delay_seconds: int = 30,
    user_enabled: UserEnabled | None = None,
) -> Reminder | None:
    """Deliver one due reminder with conservative exactly-once semantics."""

    now = int(now_ts or time.time())
    reminder = store.claim_due(
        owner_token=owner_token,
        now_ts=now,
        lease_seconds=lease_seconds,
    )
    if reminder is None:
        return None
    if user_enabled is not None and not user_enabled(reminder.user_key):
        return store.fail_before_send(
            reminder,
            owner_token=owner_token,
            error="reminder_user_disabled",
            now_ts=now,
        )
    try:
        transport = transport_for(reminder.provider_key)
    except Exception as exc:
        return store.fail_before_send(
            reminder,
            owner_token=owner_token,
            error=f"transport:{type(exc).__name__}",
            retry_at_ts=now + max(1, int(retry_delay_seconds)),
            now_ts=now,
        )

    sending = store.begin_send(
        reminder,
        owner_token=owner_token,
        now_ts=now,
        lease_seconds=lease_seconds,
    )
    try:
        provider_id = await transport.send_text(
            sending.chat_id,
            f"⏰ {sending.text}",
            reply_to="",
            idempotency_key=reminder_delivery_key(sending),
        )
    except Exception as exc:
        return store.mark_uncertain(
            sending,
            owner_token=owner_token,
            error=f"provider_send:{type(exc).__name__}",
            now_ts=now,
        )
    return store.complete(
        sending,
        owner_token=owner_token,
        provider_message_id=provider_id,
        now_ts=now,
    )
