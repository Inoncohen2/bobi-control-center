"""Durable deterministic interaction routing for Bobi Next.

Interactive provider events (currently WAHA poll votes) are not free-form user
commands and must never be converted into AI text. Bobi registers polls it owns,
then accepts votes only for the exact provider poll id, linked user and declared
option set. Latest provider timestamps win, matching WAHA's documented semantics.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_MAX_OPTIONS = 32
_MAX_OPTION_TEXT = 256


@dataclass(slots=True, frozen=True)
class PollVoteEvent:
    provider: str
    vote_id: str
    poll_message_id: str
    voter_identity: str
    selected_options: tuple[str, ...]
    provider_timestamp: int
    failed: bool = False


@dataclass(slots=True, frozen=True)
class PollInteraction:
    interaction_id: str
    provider: str
    poll_message_id: str
    chat_id: str
    user_key: str
    question: str
    option_keys: dict[str, str]
    multiple_answers: bool
    context_key: str
    state: str
    latest_vote_timestamp: int
    selected_keys: tuple[str, ...]
    expires_ts: int


@dataclass(slots=True, frozen=True)
class VoteResult:
    accepted: bool
    reason: str
    interaction_id: str = ""
    selected_keys: tuple[str, ...] = ()
    duplicate: bool = False
    needs_resend: bool = False


def _json_object(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _json_tuple(raw: Any) -> tuple[str, ...]:
    try:
        value = json.loads(str(raw or "[]"))
    except (TypeError, ValueError):
        return ()
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if str(item).strip())


class PollInteractionStore:
    """SQLite poll registry and exactly-once vote event ledger."""

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
            CREATE TABLE IF NOT EXISTS poll_interactions (
                interaction_id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                poll_message_id TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                user_key TEXT NOT NULL,
                question TEXT NOT NULL,
                option_keys_json TEXT NOT NULL,
                multiple_answers INTEGER NOT NULL DEFAULT 0,
                context_key TEXT NOT NULL DEFAULT '',
                state TEXT NOT NULL DEFAULT 'open',
                latest_vote_timestamp INTEGER NOT NULL DEFAULT 0,
                selected_keys_json TEXT NOT NULL DEFAULT '[]',
                failure_count INTEGER NOT NULL DEFAULT 0,
                created_ts INTEGER NOT NULL,
                expires_ts INTEGER NOT NULL DEFAULT 0,
                UNIQUE(provider, poll_message_id)
            );
            CREATE INDEX IF NOT EXISTS ix_poll_interactions_user
                ON poll_interactions(user_key, state, created_ts DESC);

            CREATE TABLE IF NOT EXISTS poll_vote_events (
                provider TEXT NOT NULL,
                vote_id TEXT NOT NULL,
                poll_message_id TEXT NOT NULL,
                user_key TEXT NOT NULL DEFAULT '',
                provider_timestamp INTEGER NOT NULL,
                selected_options_json TEXT NOT NULL,
                outcome TEXT NOT NULL,
                created_ts INTEGER NOT NULL,
                PRIMARY KEY(provider, vote_id)
            );
            CREATE INDEX IF NOT EXISTS ix_poll_vote_events_poll
                ON poll_vote_events(provider, poll_message_id, provider_timestamp DESC);
            """
        )
        self._db.commit()

    @staticmethod
    def _row_to_interaction(row: sqlite3.Row | None) -> PollInteraction | None:
        if row is None:
            return None
        option_keys_raw = _json_object(row["option_keys_json"])
        option_keys = {
            str(label): str(key)
            for label, key in option_keys_raw.items()
            if str(label).strip() and str(key).strip()
        }
        return PollInteraction(
            interaction_id=str(row["interaction_id"]),
            provider=str(row["provider"]),
            poll_message_id=str(row["poll_message_id"]),
            chat_id=str(row["chat_id"]),
            user_key=str(row["user_key"]),
            question=str(row["question"]),
            option_keys=option_keys,
            multiple_answers=bool(row["multiple_answers"]),
            context_key=str(row["context_key"]),
            state=str(row["state"]),
            latest_vote_timestamp=int(row["latest_vote_timestamp"]),
            selected_keys=_json_tuple(row["selected_keys_json"]),
            expires_ts=int(row["expires_ts"]),
        )

    def register(
        self,
        *,
        provider: str,
        poll_message_id: str,
        chat_id: str,
        user_key: str,
        question: str,
        option_keys: dict[str, str],
        multiple_answers: bool = False,
        context_key: str = "",
        interaction_id: str = "",
        expires_ts: int = 0,
        now_ts: int | None = None,
    ) -> PollInteraction:
        provider = provider.strip()
        poll_message_id = poll_message_id.strip()
        user_key = user_key.strip()
        chat_id = chat_id.strip()
        if not provider or not poll_message_id or not user_key or not chat_id:
            raise ValueError("poll_interaction_identity_required")
        if not isinstance(option_keys, dict) or not 1 <= len(option_keys) <= _MAX_OPTIONS:
            raise ValueError("poll_options_invalid")
        normalized: dict[str, str] = {}
        for raw_label, raw_key in option_keys.items():
            label = str(raw_label).strip()[:_MAX_OPTION_TEXT]
            key = str(raw_key).strip()[:128]
            if not label or not key or label in normalized:
                raise ValueError("poll_options_invalid")
            normalized[label] = key
        if len(set(normalized.values())) != len(normalized):
            raise ValueError("poll_option_keys_not_unique")
        created = int(now_ts or time.time())
        identifier = interaction_id.strip() or str(uuid.uuid4())
        encoded_options = json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._db:
            self._db.execute(
                """
                INSERT INTO poll_interactions(
                    interaction_id,provider,poll_message_id,chat_id,user_key,question,
                    option_keys_json,multiple_answers,context_key,state,
                    latest_vote_timestamp,selected_keys_json,failure_count,created_ts,expires_ts
                ) VALUES(?,?,?,?,?,?,?,?,?,'open',0,'[]',0,?,?)
                """,
                (
                    identifier,
                    provider,
                    poll_message_id,
                    chat_id,
                    user_key,
                    question.strip()[:1000],
                    encoded_options,
                    int(bool(multiple_answers)),
                    context_key.strip()[:512],
                    created,
                    max(0, int(expires_ts)),
                ),
            )
        result = self.get(provider, poll_message_id)
        if result is None:
            raise RuntimeError("poll_interaction_not_persisted")
        return result

    def get(self, provider: str, poll_message_id: str) -> PollInteraction | None:
        row = self._db.execute(
            "SELECT * FROM poll_interactions WHERE provider=? AND poll_message_id=?",
            (provider, poll_message_id),
        ).fetchone()
        return self._row_to_interaction(row)

    def _record_event(
        self,
        event: PollVoteEvent,
        *,
        user_key: str,
        outcome: str,
        now_ts: int,
    ) -> bool:
        selected_json = json.dumps(
            list(event.selected_options),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            self._db.execute(
                """
                INSERT INTO poll_vote_events(
                    provider,vote_id,poll_message_id,user_key,provider_timestamp,
                    selected_options_json,outcome,created_ts
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    event.provider,
                    event.vote_id,
                    event.poll_message_id,
                    user_key,
                    int(event.provider_timestamp),
                    selected_json,
                    outcome,
                    now_ts,
                ),
            )
        except sqlite3.IntegrityError:
            return False
        return True

    def apply_vote(
        self,
        event: PollVoteEvent,
        *,
        user_key: str,
        now_ts: int | None = None,
    ) -> VoteResult:
        now = int(now_ts or time.time())
        self._db.execute("BEGIN IMMEDIATE")
        try:
            interaction = self.get(event.provider, event.poll_message_id)
            if interaction is None:
                inserted = self._record_event(
                    event,
                    user_key=user_key,
                    outcome="unknown_poll",
                    now_ts=now,
                )
                self._db.commit()
                return VoteResult(False, "unknown_poll", duplicate=not inserted)

            if event.failed:
                inserted = self._record_event(
                    event,
                    user_key=user_key,
                    outcome="decrypt_failed",
                    now_ts=now,
                )
                if inserted:
                    self._db.execute(
                        """
                        UPDATE poll_interactions
                        SET failure_count=failure_count+1
                        WHERE interaction_id=?
                        """,
                        (interaction.interaction_id,),
                    )
                self._db.commit()
                return VoteResult(
                    False,
                    "poll_vote_failed",
                    interaction.interaction_id,
                    duplicate=not inserted,
                    needs_resend=inserted,
                )

            max_selections = len(interaction.option_keys) if interaction.multiple_answers else 1
            if interaction.state != "open":
                outcome = "interaction_closed"
            elif interaction.expires_ts and now > interaction.expires_ts:
                outcome = "interaction_expired"
            elif interaction.user_key != user_key:
                outcome = "interaction_user_mismatch"
            elif event.provider_timestamp < interaction.latest_vote_timestamp:
                outcome = "stale_vote"
            elif len(event.selected_options) > max_selections:
                outcome = "invalid_selection_count"
            elif any(
                option not in interaction.option_keys
                for option in event.selected_options
            ):
                outcome = "unknown_option"
            else:
                outcome = "accepted"

            inserted = self._record_event(
                event,
                user_key=user_key,
                outcome=outcome,
                now_ts=now,
            )
            if not inserted:
                self._db.rollback()
                return VoteResult(
                    False,
                    "duplicate_vote",
                    interaction.interaction_id,
                    interaction.selected_keys,
                    duplicate=True,
                )

            if outcome != "accepted":
                if outcome == "interaction_expired":
                    self._db.execute(
                        "UPDATE poll_interactions SET state='expired' WHERE interaction_id=?",
                        (interaction.interaction_id,),
                    )
                self._db.commit()
                return VoteResult(
                    False,
                    outcome,
                    interaction.interaction_id,
                    interaction.selected_keys,
                )

            keys = tuple(interaction.option_keys[option] for option in event.selected_options)
            self._db.execute(
                """
                UPDATE poll_interactions
                SET latest_vote_timestamp=?, selected_keys_json=?
                WHERE interaction_id=?
                """,
                (
                    int(event.provider_timestamp),
                    json.dumps(list(keys), ensure_ascii=False, separators=(",", ":")),
                    interaction.interaction_id,
                ),
            )
            self._db.commit()
            return VoteResult(True, "accepted", interaction.interaction_id, keys)
        except Exception:
            self._db.rollback()
            raise
