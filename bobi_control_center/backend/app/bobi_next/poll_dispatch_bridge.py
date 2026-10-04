"""Crash-safe bridge from the poll vote ledger to interaction dispatch.

Poll votes and interaction dispatches intentionally live in separate durable
stores.  A process can therefore stop after the WAHA vote was committed but
before a continuation was queued.  This bridge treats the poll vote ledger as
the source of truth and deterministically reconstructs the *first non-empty
accepted* selection for every Bobi-owned interaction that has a context key.

The bridge never feeds a poll choice to AI.  Provider option labels are mapped
back to the stable option keys registered by Bobi before an interaction is
queued.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from .interaction_dispatch import InteractionDispatchStore
from .poll_interactions import PollInteractionStore


@dataclass(slots=True, frozen=True)
class PollDispatchCandidate:
    provider: str
    interaction_id: str
    poll_message_id: str
    chat_id: str
    user_key: str
    context_key: str
    selected_keys: tuple[str, ...]
    source_event_id: str
    provider_timestamp: int


def _json_object(raw: Any) -> dict[str, str]:
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, ValueError):
        return {}
    if not isinstance(value, dict):
        return {}
    return {
        str(key): str(item)
        for key, item in value.items()
        if str(key).strip() and str(item).strip()
    }


def _json_tuple(raw: Any) -> tuple[str, ...]:
    try:
        value = json.loads(str(raw or "[]"))
    except (TypeError, ValueError):
        return ()
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if str(item).strip())


def _candidates(
    interactions: PollInteractionStore,
    *,
    provider: str = "",
    poll_message_id: str = "",
) -> tuple[PollDispatchCandidate, ...]:
    clauses = ["pi.context_key <> ''", "e.outcome='accepted'"]
    params: list[str] = []
    if provider.strip():
        clauses.append("pi.provider=?")
        params.append(provider.strip())
    if poll_message_id.strip():
        clauses.append("pi.poll_message_id=?")
        params.append(poll_message_id.strip())

    query = f"""
        SELECT
            pi.interaction_id,
            pi.provider,
            pi.poll_message_id,
            pi.chat_id,
            pi.user_key,
            pi.context_key,
            pi.option_keys_json,
            e.vote_id,
            e.provider_timestamp,
            e.selected_options_json,
            e.created_ts
        FROM poll_interactions AS pi
        JOIN poll_vote_events AS e
          ON e.provider=pi.provider
         AND e.poll_message_id=pi.poll_message_id
        WHERE {' AND '.join(clauses)}
        ORDER BY
            pi.interaction_id,
            e.provider_timestamp,
            e.created_ts,
            e.vote_id
    """

    db = sqlite3.connect(interactions.path)
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute(query, tuple(params)).fetchall()
    finally:
        db.close()

    chosen: set[str] = set()
    result: list[PollDispatchCandidate] = []
    for row in rows:
        interaction_id = str(row["interaction_id"])
        if interaction_id in chosen:
            continue
        selected_options = _json_tuple(row["selected_options_json"])
        if not selected_options:
            # WAHA can emit an accepted empty selection when a user clears a
            # poll vote.  That is state, not an action continuation.
            continue
        option_keys = _json_object(row["option_keys_json"])
        if any(option not in option_keys for option in selected_options):
            # The original ledger says accepted, so this should be impossible
            # unless durable data was corrupted.  Fail closed rather than guess.
            continue
        selected_keys = tuple(option_keys[option] for option in selected_options)
        if not selected_keys:
            continue
        chosen.add(interaction_id)
        result.append(
            PollDispatchCandidate(
                provider=str(row["provider"]),
                interaction_id=interaction_id,
                poll_message_id=str(row["poll_message_id"]),
                chat_id=str(row["chat_id"]),
                user_key=str(row["user_key"]),
                context_key=str(row["context_key"]),
                selected_keys=selected_keys,
                source_event_id=str(row["vote_id"]),
                provider_timestamp=int(row["provider_timestamp"]),
            )
        )
    return tuple(result)


def reconcile_poll_dispatches(
    interactions: PollInteractionStore,
    dispatches: InteractionDispatchStore,
    *,
    provider: str = "",
    poll_message_id: str = "",
    now_ts: int | None = None,
) -> int:
    """Queue any accepted contextual poll selection not already dispatched.

    Returning the number of newly queued interactions makes startup recovery
    observable without exposing user content in logs.
    """

    now = int(now_ts or time.time())
    created = 0
    for candidate in _candidates(
        interactions,
        provider=provider,
        poll_message_id=poll_message_id,
    ):
        if dispatches.get_for_interaction(candidate.interaction_id) is not None:
            continue
        dispatches.enqueue(
            provider=candidate.provider,
            interaction_id=candidate.interaction_id,
            poll_message_id=candidate.poll_message_id,
            chat_id=candidate.chat_id,
            user_key=candidate.user_key,
            context_key=candidate.context_key,
            selected_keys=candidate.selected_keys,
            source_event_id=candidate.source_event_id,
            provider_timestamp=candidate.provider_timestamp,
            now_ts=now,
        )
        created += 1
    return created
