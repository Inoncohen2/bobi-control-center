"""Provider-neutral messaging core for Bobi Next.

Inbound webhooks are persisted before processing, deduplicated by provider
message id and consumed in strict per-chat order.  Outbound replies use a
persistent outbox and deterministic idempotency keys so provider adapters can
avoid duplicate replies across retries or worker crashes.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(slots=True, frozen=True)
class InboundMessage:
    row_id: int
    provider: str
    message_id: str
    chat_id: str
    user_key: str
    text: str
    kind: str
    received_ts: int
    state: str
    attempts: int = 0
    owner_token: str = ""
    lease_until_ts: int = 0
    last_error: str = ""


@dataclass(slots=True, frozen=True)
class OutboundMessage:
    response_key: str
    provider: str
    chat_id: str
    in_reply_to: str
    text: str
    state: str
    provider_message_id: str = ""


@dataclass(slots=True, frozen=True)
class MessageResponse:
    text: str
    reaction: str = ""


class MessageTransport(Protocol):
    async def react(self, message: InboundMessage, emoji: str) -> None: ...

    async def set_typing(self, chat_id: str, enabled: bool) -> None: ...

    async def send_text(
        self,
        chat_id: str,
        text: str,
        *,
        reply_to: str,
        idempotency_key: str,
    ) -> str: ...


MessageHandler = Callable[[InboundMessage], Awaitable[MessageResponse]]
ReactionSelector = Callable[[InboundMessage], str]


def _response_key(message: InboundMessage, role: str = "primary") -> str:
    raw = f"{message.provider}\0{message.message_id}\0{role}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class MessageStore:
    """SQLite inbox/outbox with webhook dedupe and per-chat sequencing."""

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
            CREATE TABLE IF NOT EXISTS inbound_messages (
                row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                message_id TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                user_key TEXT NOT NULL,
                text TEXT NOT NULL,
                kind TEXT NOT NULL,
                received_ts INTEGER NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                owner_token TEXT NOT NULL DEFAULT '',
                lease_until_ts INTEGER NOT NULL DEFAULT 0,
                next_attempt_ts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                completed_ts INTEGER NOT NULL DEFAULT 0,
                UNIQUE(provider, message_id)
            );
            CREATE INDEX IF NOT EXISTS ix_inbound_due
                ON inbound_messages(state, next_attempt_ts, received_ts, row_id);
            CREATE INDEX IF NOT EXISTS ix_inbound_chat
                ON inbound_messages(provider, chat_id, received_ts, row_id);

            CREATE TABLE IF NOT EXISTS outbound_messages (
                response_key TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                in_reply_to TEXT NOT NULL,
                text TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'prepared',
                provider_message_id TEXT NOT NULL DEFAULT '',
                created_ts INTEGER NOT NULL,
                sent_ts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS ix_outbound_reply
                ON outbound_messages(provider, in_reply_to);
            """
        )
        self._db.commit()

    @staticmethod
    def _inbound(row: sqlite3.Row | None) -> InboundMessage | None:
        if row is None:
            return None
        return InboundMessage(
            row_id=int(row["row_id"]),
            provider=str(row["provider"]),
            message_id=str(row["message_id"]),
            chat_id=str(row["chat_id"]),
            user_key=str(row["user_key"]),
            text=str(row["text"]),
            kind=str(row["kind"]),
            received_ts=int(row["received_ts"]),
            state=str(row["state"]),
            attempts=int(row["attempts"]),
            owner_token=str(row["owner_token"]),
            lease_until_ts=int(row["lease_until_ts"]),
            last_error=str(row["last_error"]),
        )

    @staticmethod
    def _outbound(row: sqlite3.Row | None) -> OutboundMessage | None:
        if row is None:
            return None
        return OutboundMessage(
            response_key=str(row["response_key"]),
            provider=str(row["provider"]),
            chat_id=str(row["chat_id"]),
            in_reply_to=str(row["in_reply_to"]),
            text=str(row["text"]),
            state=str(row["state"]),
            provider_message_id=str(row["provider_message_id"]),
        )

    def enqueue(
        self,
        *,
        provider: str,
        message_id: str,
        chat_id: str,
        user_key: str,
        text: str,
        kind: str = "text",
        received_ts: int | None = None,
    ) -> bool:
        if not provider.strip() or not message_id.strip() or not chat_id.strip():
            raise ValueError("invalid_message_identity")
        now = int(received_ts or time.time())
        try:
            with self._db:
                self._db.execute(
                    """
                    INSERT INTO inbound_messages(
                        provider,message_id,chat_id,user_key,text,kind,received_ts,
                        state,next_attempt_ts
                    ) VALUES(?,?,?,?,?,?,?,'pending',?)
                    """,
                    (provider, message_id, chat_id, user_key, text, kind, now, now),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def get_inbound(self, provider: str, message_id: str) -> InboundMessage | None:
        row = self._db.execute(
            "SELECT * FROM inbound_messages WHERE provider=? AND message_id=?",
            (provider, message_id),
        ).fetchone()
        return self._inbound(row)

    def claim_next(
        self,
        *,
        owner_token: str,
        now_ts: int | None = None,
        lease_seconds: int = 90,
    ) -> InboundMessage | None:
        if not owner_token.strip():
            raise ValueError("owner_token_required")
        now = int(now_ts or time.time())
        lease_until = now + max(5, int(lease_seconds))

        self._db.execute("BEGIN IMMEDIATE")
        try:
            row = self._db.execute(
                """
                SELECT m.row_id
                FROM inbound_messages AS m
                WHERE (
                    (m.state IN ('pending','retry') AND m.next_attempt_ts <= ?)
                    OR (m.state='running' AND m.lease_until_ts < ?)
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM inbound_messages AS older
                    WHERE older.provider=m.provider
                      AND older.chat_id=m.chat_id
                      AND older.state NOT IN ('completed','failed','ignored')
                      AND (
                        older.received_ts < m.received_ts
                        OR (
                            older.received_ts=m.received_ts
                            AND older.row_id < m.row_id
                        )
                      )
                )
                ORDER BY m.received_ts, m.row_id
                LIMIT 1
                """,
                (now, now),
            ).fetchone()
            if row is None:
                self._db.rollback()
                return None
            row_id = int(row["row_id"])
            self._db.execute(
                """
                UPDATE inbound_messages
                SET state='running', owner_token=?, lease_until_ts=?,
                    attempts=attempts+1, last_error=''
                WHERE row_id=?
                """,
                (owner_token, lease_until, row_id),
            )
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise

        claimed = self._db.execute(
            "SELECT * FROM inbound_messages WHERE row_id=?",
            (row_id,),
        ).fetchone()
        return self._inbound(claimed)

    def complete(
        self,
        message: InboundMessage,
        *,
        owner_token: str,
        now_ts: int | None = None,
    ) -> InboundMessage:
        now = int(now_ts or time.time())
        with self._db:
            result = self._db.execute(
                """
                UPDATE inbound_messages
                SET state='completed', owner_token='', lease_until_ts=0,
                    completed_ts=?, last_error=''
                WHERE row_id=? AND state='running' AND owner_token=?
                """,
                (now, message.row_id, owner_token),
            )
        if result.rowcount != 1:
            raise PermissionError("message_not_owned")
        updated = self.get_inbound(message.provider, message.message_id)
        if updated is None:
            raise RuntimeError("message_disappeared")
        return updated

    def fail(
        self,
        message: InboundMessage,
        *,
        owner_token: str,
        error: str,
        retry_at_ts: int | None = None,
    ) -> InboundMessage:
        retry_at = int(retry_at_ts or 0)
        state = "retry" if retry_at > 0 else "failed"
        with self._db:
            result = self._db.execute(
                """
                UPDATE inbound_messages
                SET state=?, owner_token='', lease_until_ts=0,
                    next_attempt_ts=?, last_error=?
                WHERE row_id=? AND state='running' AND owner_token=?
                """,
                (
                    state,
                    retry_at,
                    str(error)[:1000],
                    message.row_id,
                    owner_token,
                ),
            )
        if result.rowcount != 1:
            raise PermissionError("message_not_owned")
        updated = self.get_inbound(message.provider, message.message_id)
        if updated is None:
            raise RuntimeError("message_disappeared")
        return updated

    def prepare_outbound(
        self,
        message: InboundMessage,
        *,
        text: str,
        role: str = "primary",
        now_ts: int | None = None,
    ) -> OutboundMessage:
        key = _response_key(message, role)
        now = int(now_ts or time.time())
        with self._db:
            self._db.execute(
                """
                INSERT INTO outbound_messages(
                    response_key,provider,chat_id,in_reply_to,text,state,created_ts
                ) VALUES(?,?,?,?,?,'prepared',?)
                ON CONFLICT(response_key) DO NOTHING
                """,
                (key, message.provider, message.chat_id, message.message_id, text, now),
            )
        row = self._db.execute(
            "SELECT * FROM outbound_messages WHERE response_key=?",
            (key,),
        ).fetchone()
        outbound = self._outbound(row)
        if outbound is None:
            raise RuntimeError("outbound_not_persisted")
        if outbound.text != text:
            raise RuntimeError("outbound_payload_changed")
        return outbound

    def mark_outbound_sent(
        self,
        response_key: str,
        *,
        provider_message_id: str,
        now_ts: int | None = None,
    ) -> OutboundMessage:
        now = int(now_ts or time.time())
        with self._db:
            self._db.execute(
                """
                UPDATE outbound_messages
                SET state='sent', provider_message_id=?, sent_ts=?, last_error=''
                WHERE response_key=?
                """,
                (provider_message_id, now, response_key),
            )
        row = self._db.execute(
            "SELECT * FROM outbound_messages WHERE response_key=?",
            (response_key,),
        ).fetchone()
        outbound = self._outbound(row)
        if outbound is None:
            raise RuntimeError("outbound_disappeared")
        return outbound


async def process_next_message(
    store: MessageStore,
    transport: MessageTransport,
    handler: MessageHandler,
    *,
    owner_token: str,
    now_ts: int,
    reaction_for: ReactionSelector | None = None,
    retry_delay_seconds: int = 15,
    max_attempts: int = 3,
) -> InboundMessage | None:
    """Process one message using reaction -> typing -> reply lifecycle."""

    message = store.claim_next(owner_token=owner_token, now_ts=now_ts)
    if message is None:
        return None

    typing_started = False
    try:
        emoji = reaction_for(message) if reaction_for is not None else ""
        if emoji:
            await transport.react(message, emoji)
        await transport.set_typing(message.chat_id, True)
        typing_started = True

        response = await handler(message)
        outbound = store.prepare_outbound(message, text=response.text, now_ts=now_ts)
        if outbound.state != "sent":
            provider_id = await transport.send_text(
                message.chat_id,
                outbound.text,
                reply_to=message.message_id,
                idempotency_key=outbound.response_key,
            )
            store.mark_outbound_sent(
                outbound.response_key,
                provider_message_id=provider_id,
                now_ts=now_ts,
            )
        return store.complete(message, owner_token=owner_token, now_ts=now_ts)
    except Exception as exc:
        retry = message.attempts < max(1, int(max_attempts))
        store.fail(
            message,
            owner_token=owner_token,
            error=f"{type(exc).__name__}:{exc}",
            retry_at_ts=(now_ts + max(1, int(retry_delay_seconds))) if retry else None,
        )
        return store.get_inbound(message.provider, message.message_id)
    finally:
        if typing_started:
            try:
                await transport.set_typing(message.chat_id, False)
            except Exception:
                pass
