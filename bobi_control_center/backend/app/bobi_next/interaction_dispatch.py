"""Durable deterministic dispatch for Bobi Next interactive selections.

Provider interaction events such as WAHA poll votes are already authenticated,
bound to a Bobi-owned interaction and mapped to stable option keys before they
reach this module.  This boundary deliberately never turns a selection back
into free-form text and never calls AI.

A dispatch is unique per interaction.  The first accepted selection wins for an
action-style interaction; later vote changes may still be recorded by the poll
ledger but cannot trigger a second side effect.  Handlers are selected only by
an explicit context namespace (``approval:...``, ``dialog:...`` etc.).

Handlers must use ``dispatch_id`` as the idempotency key for downstream side
effects.  Once a handler result is durably stored, retries skip the handler and
only retry delivery of its user-visible response.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .messaging import MessageTransport


@dataclass(slots=True, frozen=True)
class InteractionSelection:
    dispatch_id: str
    provider: str
    interaction_id: str
    poll_message_id: str
    chat_id: str
    user_key: str
    context_key: str
    selected_keys: tuple[str, ...]
    source_event_id: str
    provider_timestamp: int


@dataclass(slots=True, frozen=True)
class InteractionHandlerResult:
    outcome: str = "completed"
    response_text: str = ""


class InteractionHandler(Protocol):
    async def __call__(self, selection: InteractionSelection) -> InteractionHandlerResult: ...


TransportResolver = Callable[[str], MessageTransport]


@dataclass(slots=True, frozen=True)
class InteractionDispatch:
    dispatch_id: str
    provider: str
    interaction_id: str
    poll_message_id: str
    chat_id: str
    user_key: str
    context_key: str
    selected_keys: tuple[str, ...]
    source_event_id: str
    provider_timestamp: int
    state: str
    attempts: int
    owner_token: str
    lease_until_ts: int
    handler_done: bool
    outcome: str
    response_text: str
    provider_message_id: str
    last_error: str


@dataclass(slots=True, frozen=True)
class DispatchProcessResult:
    dispatch_id: str
    state: str
    outcome: str


def _json_tuple(raw: object) -> tuple[str, ...]:
    try:
        decoded = json.loads(str(raw or "[]"))
    except (TypeError, ValueError):
        return ()
    if not isinstance(decoded, list):
        return ()
    return tuple(str(item) for item in decoded if str(item).strip())


def _dispatch_id(provider: str, interaction_id: str) -> str:
    raw = f"{provider}\0{interaction_id}".encode()
    return hashlib.sha256(raw).hexdigest()


def _context_namespace(context_key: str) -> str:
    namespace, _, _ = context_key.strip().partition(":")
    normalized = namespace.casefold().strip()
    if not normalized or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for ch in normalized):
        return ""
    return normalized


class InteractionDispatchStore:
    """SQLite exactly-once queue for deterministic interaction continuations."""

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
            CREATE TABLE IF NOT EXISTS interaction_dispatches (
                dispatch_id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                interaction_id TEXT NOT NULL UNIQUE,
                poll_message_id TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                user_key TEXT NOT NULL,
                context_key TEXT NOT NULL,
                selected_keys_json TEXT NOT NULL,
                source_event_id TEXT NOT NULL,
                provider_timestamp INTEGER NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                owner_token TEXT NOT NULL DEFAULT '',
                lease_until_ts INTEGER NOT NULL DEFAULT 0,
                next_attempt_ts INTEGER NOT NULL DEFAULT 0,
                handler_done INTEGER NOT NULL DEFAULT 0,
                outcome TEXT NOT NULL DEFAULT '',
                response_text TEXT NOT NULL DEFAULT '',
                provider_message_id TEXT NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT '',
                created_ts INTEGER NOT NULL,
                completed_ts INTEGER NOT NULL DEFAULT 0,
                UNIQUE(provider, source_event_id)
            );
            CREATE INDEX IF NOT EXISTS ix_interaction_dispatch_due
                ON interaction_dispatches(state, next_attempt_ts, created_ts);
            """
        )
        self._db.commit()

    @staticmethod
    def _row(row: sqlite3.Row | None) -> InteractionDispatch | None:
        if row is None:
            return None
        return InteractionDispatch(
            dispatch_id=str(row["dispatch_id"]),
            provider=str(row["provider"]),
            interaction_id=str(row["interaction_id"]),
            poll_message_id=str(row["poll_message_id"]),
            chat_id=str(row["chat_id"]),
            user_key=str(row["user_key"]),
            context_key=str(row["context_key"]),
            selected_keys=_json_tuple(row["selected_keys_json"]),
            source_event_id=str(row["source_event_id"]),
            provider_timestamp=int(row["provider_timestamp"]),
            state=str(row["state"]),
            attempts=int(row["attempts"]),
            owner_token=str(row["owner_token"]),
            lease_until_ts=int(row["lease_until_ts"]),
            handler_done=bool(row["handler_done"]),
            outcome=str(row["outcome"]),
            response_text=str(row["response_text"]),
            provider_message_id=str(row["provider_message_id"]),
            last_error=str(row["last_error"]),
        )

    def get(self, dispatch_id: str) -> InteractionDispatch | None:
        row = self._db.execute(
            "SELECT * FROM interaction_dispatches WHERE dispatch_id=?",
            (dispatch_id,),
        ).fetchone()
        return self._row(row)

    def get_for_interaction(self, interaction_id: str) -> InteractionDispatch | None:
        row = self._db.execute(
            "SELECT * FROM interaction_dispatches WHERE interaction_id=?",
            (interaction_id,),
        ).fetchone()
        return self._row(row)

    def enqueue(
        self,
        *,
        provider: str,
        interaction_id: str,
        poll_message_id: str,
        chat_id: str,
        user_key: str,
        context_key: str,
        selected_keys: tuple[str, ...],
        source_event_id: str,
        provider_timestamp: int,
        now_ts: int | None = None,
    ) -> InteractionDispatch:
        provider = provider.strip()
        interaction_id = interaction_id.strip()
        poll_message_id = poll_message_id.strip()
        chat_id = chat_id.strip()
        user_key = user_key.strip()
        context_key = context_key.strip()
        source_event_id = source_event_id.strip()
        keys = tuple(str(key).strip() for key in selected_keys if str(key).strip())
        if not all((provider, interaction_id, poll_message_id, chat_id, user_key, source_event_id)):
            raise ValueError("interaction_dispatch_identity_required")
        if not context_key or not _context_namespace(context_key):
            raise ValueError("interaction_context_invalid")
        if not keys:
            raise ValueError("interaction_selection_required")
        identifier = _dispatch_id(provider, interaction_id)
        now = int(now_ts or time.time())
        encoded = json.dumps(list(keys), ensure_ascii=False, separators=(",", ":"))
        with self._db:
            self._db.execute(
                """
                INSERT INTO interaction_dispatches(
                    dispatch_id,provider,interaction_id,poll_message_id,chat_id,user_key,
                    context_key,selected_keys_json,source_event_id,provider_timestamp,
                    state,next_attempt_ts,created_ts
                ) VALUES(?,?,?,?,?,?,?,?,?,?,'pending',?,?)
                ON CONFLICT(interaction_id) DO NOTHING
                """,
                (
                    identifier,
                    provider,
                    interaction_id,
                    poll_message_id,
                    chat_id,
                    user_key,
                    context_key,
                    encoded,
                    source_event_id,
                    max(0, int(provider_timestamp)),
                    now,
                    now,
                ),
            )
        result = self.get_for_interaction(interaction_id)
        if result is None:
            raise RuntimeError("interaction_dispatch_not_persisted")
        return result

    def claim_next(
        self,
        *,
        owner_token: str,
        now_ts: int | None = None,
        lease_seconds: int = 90,
    ) -> InteractionDispatch | None:
        owner = owner_token.strip()
        if not owner:
            raise ValueError("owner_token_required")
        now = int(now_ts or time.time())
        lease_until = now + max(5, int(lease_seconds))
        self._db.execute("BEGIN IMMEDIATE")
        try:
            row = self._db.execute(
                """
                SELECT dispatch_id FROM interaction_dispatches
                WHERE (
                    (state IN ('pending','retry') AND next_attempt_ts <= ?)
                    OR (state='running' AND lease_until_ts < ?)
                )
                ORDER BY created_ts, dispatch_id
                LIMIT 1
                """,
                (now, now),
            ).fetchone()
            if row is None:
                self._db.rollback()
                return None
            dispatch_id = str(row["dispatch_id"])
            self._db.execute(
                """
                UPDATE interaction_dispatches
                SET state='running',owner_token=?,lease_until_ts=?,attempts=attempts+1,last_error=''
                WHERE dispatch_id=?
                """,
                (owner, lease_until, dispatch_id),
            )
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
        return self.get(dispatch_id)

    def mark_handler_result(
        self,
        dispatch: InteractionDispatch,
        *,
        owner_token: str,
        result: InteractionHandlerResult,
    ) -> InteractionDispatch:
        outcome = str(result.outcome or "completed").strip()[:128]
        response = str(result.response_text or "")[:8000]
        with self._db:
            updated = self._db.execute(
                """
                UPDATE interaction_dispatches
                SET handler_done=1,outcome=?,response_text=?
                WHERE dispatch_id=? AND state='running' AND owner_token=?
                """,
                (outcome, response, dispatch.dispatch_id, owner_token),
            )
        if updated.rowcount != 1:
            raise PermissionError("interaction_dispatch_not_owned")
        current = self.get(dispatch.dispatch_id)
        if current is None:
            raise RuntimeError("interaction_dispatch_disappeared")
        return current

    def complete(
        self,
        dispatch: InteractionDispatch,
        *,
        owner_token: str,
        provider_message_id: str = "",
        now_ts: int | None = None,
    ) -> InteractionDispatch:
        now = int(now_ts or time.time())
        with self._db:
            updated = self._db.execute(
                """
                UPDATE interaction_dispatches
                SET state='completed',owner_token='',lease_until_ts=0,
                    provider_message_id=?,completed_ts=?,last_error=''
                WHERE dispatch_id=? AND state='running' AND owner_token=? AND handler_done=1
                """,
                (provider_message_id.strip(), now, dispatch.dispatch_id, owner_token),
            )
        if updated.rowcount != 1:
            raise PermissionError("interaction_dispatch_not_owned")
        current = self.get(dispatch.dispatch_id)
        if current is None:
            raise RuntimeError("interaction_dispatch_disappeared")
        return current

    def fail(
        self,
        dispatch: InteractionDispatch,
        *,
        owner_token: str,
        error: str,
        retry_at_ts: int | None,
    ) -> InteractionDispatch:
        retry_at = int(retry_at_ts or 0)
        state = "retry" if retry_at > 0 else "failed"
        with self._db:
            updated = self._db.execute(
                """
                UPDATE interaction_dispatches
                SET state=?,owner_token='',lease_until_ts=0,next_attempt_ts=?,last_error=?
                WHERE dispatch_id=? AND state='running' AND owner_token=?
                """,
                (
                    state,
                    retry_at,
                    str(error)[:1000],
                    dispatch.dispatch_id,
                    owner_token,
                ),
            )
        if updated.rowcount != 1:
            raise PermissionError("interaction_dispatch_not_owned")
        current = self.get(dispatch.dispatch_id)
        if current is None:
            raise RuntimeError("interaction_dispatch_disappeared")
        return current


def selection_from_dispatch(dispatch: InteractionDispatch) -> InteractionSelection:
    return InteractionSelection(
        dispatch_id=dispatch.dispatch_id,
        provider=dispatch.provider,
        interaction_id=dispatch.interaction_id,
        poll_message_id=dispatch.poll_message_id,
        chat_id=dispatch.chat_id,
        user_key=dispatch.user_key,
        context_key=dispatch.context_key,
        selected_keys=dispatch.selected_keys,
        source_event_id=dispatch.source_event_id,
        provider_timestamp=dispatch.provider_timestamp,
    )


async def process_next_interaction(
    store: InteractionDispatchStore,
    handlers: Mapping[str, InteractionHandler],
    transport_for: TransportResolver,
    *,
    owner_token: str,
    now_ts: int,
    retry_delay_seconds: int = 15,
    max_attempts: int = 3,
) -> DispatchProcessResult | None:
    """Process one deterministic selection without exposing it to AI."""

    dispatch = store.claim_next(owner_token=owner_token, now_ts=now_ts)
    if dispatch is None:
        return None

    try:
        current = dispatch
        if not current.handler_done:
            namespace = _context_namespace(current.context_key)
            handler = handlers.get(namespace)
            if handler is None:
                result = InteractionHandlerResult(outcome="unhandled_context")
            else:
                result = await handler(selection_from_dispatch(current))
                if not isinstance(result, InteractionHandlerResult):
                    raise TypeError("interaction_handler_result_invalid")
            current = store.mark_handler_result(
                current,
                owner_token=owner_token,
                result=result,
            )

        provider_message_id = current.provider_message_id
        if current.response_text and not provider_message_id:
            transport = transport_for(current.provider)
            provider_message_id = await transport.send_text(
                current.chat_id,
                current.response_text,
                reply_to=current.poll_message_id,
                idempotency_key=current.dispatch_id,
            )
        completed = store.complete(
            current,
            owner_token=owner_token,
            provider_message_id=provider_message_id,
            now_ts=now_ts,
        )
        return DispatchProcessResult(completed.dispatch_id, completed.state, completed.outcome)
    except Exception as exc:
        retry = dispatch.attempts < max(1, int(max_attempts))
        failed = store.fail(
            store.get(dispatch.dispatch_id) or dispatch,
            owner_token=owner_token,
            error=f"{type(exc).__name__}:{exc}",
            retry_at_ts=(now_ts + max(1, int(retry_delay_seconds))) if retry else None,
        )
        return DispatchProcessResult(failed.dispatch_id, failed.state, failed.outcome)
