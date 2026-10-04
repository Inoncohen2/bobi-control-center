"""Safe outbound poll registration for Bobi Next.

Provider delivery happens before registration because WAHA owns the canonical
poll message id. The documented poll API does not provide caller-defined ids, so
Bobi refuses to register an interaction without the real provider id. If a
process dies after provider acceptance but before SQLite registration, any later
vote is intentionally rejected as ``unknown_poll`` instead of being guessed.
"""

from __future__ import annotations

import time
from typing import Protocol

from .poll_interactions import PollInteraction, PollInteractionStore

_MAX_OPTIONS = 32
_MAX_OPTION_TEXT = 256
_MAX_OPTION_KEY = 128


class PollTransport(Protocol):
    async def send_poll(
        self,
        chat_id: str,
        question: str,
        options: tuple[str, ...] | list[str],
        *,
        multiple_answers: bool = False,
    ) -> str: ...


def _validated_option_keys(option_keys: dict[str, str]) -> dict[str, str]:
    if not isinstance(option_keys, dict) or not 1 <= len(option_keys) <= _MAX_OPTIONS:
        raise ValueError("poll_options_invalid")
    normalized: dict[str, str] = {}
    for raw_label, raw_key in option_keys.items():
        label = str(raw_label).strip()
        key = str(raw_key).strip()
        if (
            not label
            or not key
            or len(label) > _MAX_OPTION_TEXT
            or len(key) > _MAX_OPTION_KEY
            or label in normalized
        ):
            raise ValueError("poll_options_invalid")
        normalized[label] = key
    if len(set(normalized.values())) != len(normalized):
        raise ValueError("poll_option_keys_not_unique")
    return normalized


async def send_registered_poll(
    transport: PollTransport,
    store: PollInteractionStore,
    *,
    provider: str,
    chat_id: str,
    user_key: str,
    question: str,
    option_keys: dict[str, str],
    multiple_answers: bool = False,
    context_key: str = "",
    expires_ts: int = 0,
    now_ts: int | None = None,
) -> PollInteraction:
    """Send a provider poll and register only its canonical returned id."""

    normalized = _validated_option_keys(option_keys)
    provider_key = provider.strip()
    normalized_chat = chat_id.strip()
    normalized_user = user_key.strip()
    normalized_question = question.strip()
    if not provider_key or not normalized_chat or not normalized_user:
        raise ValueError("poll_interaction_identity_required")
    if not normalized_question:
        raise ValueError("poll_question_required")

    provider_id = (
        await transport.send_poll(
            normalized_chat,
            normalized_question,
            tuple(normalized),
            multiple_answers=multiple_answers,
        )
    ).strip()
    if not provider_id:
        raise RuntimeError("poll_provider_message_id_missing")

    return store.register(
        provider=provider_key,
        poll_message_id=provider_id,
        chat_id=normalized_chat,
        user_key=normalized_user,
        question=normalized_question,
        option_keys=normalized,
        multiple_answers=multiple_answers,
        context_key=context_key,
        expires_ts=expires_ts,
        now_ts=int(now_ts or time.time()),
    )
