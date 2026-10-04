"""WAHA interactive event parsing and deterministic poll-vote ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .poll_interactions import PollInteractionStore, PollVoteEvent, VoteResult
from .setup_store import SetupStore

_WA_DIRECT_SUFFIX = "@" + "c.us"
_WA_INTERNAL_SUFFIX = "@" + "s.whatsapp.net"
_MAX_SELECTED_OPTIONS = 32


@dataclass(slots=True, frozen=True)
class ParsedWahaPollVote:
    vote_id: str
    poll_message_id: str
    voter_identity: str
    selected_options: tuple[str, ...]
    provider_timestamp: int
    failed: bool


def _normalize_identity(value: Any) -> str:
    identity = str(value or "").strip()
    if identity.endswith(_WA_INTERNAL_SUFFIX):
        return f"{identity.removesuffix(_WA_INTERNAL_SUFFIX)}{_WA_DIRECT_SUFFIX}"
    return identity


def parse_waha_poll_vote(event: dict[str, Any]) -> ParsedWahaPollVote | None:
    """Parse Bobi-relevant WAHA poll events without treating them as text."""

    event_name = str(event.get("event") or "")
    if event_name not in {"poll.vote", "poll.vote.failed"}:
        return None
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return None
    vote_raw = payload.get("vote")
    poll_raw = payload.get("poll")
    if not isinstance(vote_raw, dict) or not isinstance(poll_raw, dict):
        return None
    # WAHA emits votes for polls from other participants too. Bobi only owns
    # polls it sent itself; other polls are terminally ignored.
    if not bool(poll_raw.get("fromMe", False)):
        return None

    vote_id = str(vote_raw.get("id") or "").strip()
    poll_message_id = str(poll_raw.get("id") or "").strip()
    voter = _normalize_identity(vote_raw.get("from"))
    if not vote_id or not poll_message_id or not voter:
        return None

    selected_raw = vote_raw.get("selectedOptions")
    if not isinstance(selected_raw, list):
        selected_raw = []
    selected = tuple(
        str(option).strip()[:256]
        for option in selected_raw[:_MAX_SELECTED_OPTIONS]
        if str(option).strip()
    )
    try:
        timestamp = int(float(vote_raw.get("timestamp") or 0))
    except (TypeError, ValueError, OverflowError):
        timestamp = 0
    if timestamp < 0:
        timestamp = 0

    return ParsedWahaPollVote(
        vote_id=vote_id[:1024],
        poll_message_id=poll_message_id[:1024],
        voter_identity=voter[:512],
        selected_options=selected,
        provider_timestamp=timestamp,
        failed=event_name == "poll.vote.failed",
    )


def ingest_waha_poll_vote(
    event: dict[str, Any],
    *,
    provider_key: str,
    setup: SetupStore,
    interactions: PollInteractionStore,
    now_ts: int | None = None,
) -> VoteResult | None:
    parsed = parse_waha_poll_vote(event)
    if parsed is None:
        return None
    provider = setup.get_provider(provider_key)
    if provider is None or not provider.enabled or provider.provider_type != "waha":
        return VoteResult(False, "provider_not_configured")
    if provider.session and str(event.get("session") or "") != provider.session:
        return VoteResult(False, "session_mismatch")
    user = setup.resolve_user(provider_key, parsed.voter_identity)
    if user is None:
        return VoteResult(False, "unknown_or_disabled_sender")
    return interactions.apply_vote(
        PollVoteEvent(
            provider=provider_key,
            vote_id=parsed.vote_id,
            poll_message_id=parsed.poll_message_id,
            voter_identity=parsed.voter_identity,
            selected_options=parsed.selected_options,
            provider_timestamp=parsed.provider_timestamp,
            failed=parsed.failed,
        ),
        user_key=user.user_key,
        now_ts=now_ts,
    )
