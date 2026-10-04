from __future__ import annotations

from app.bobi_next.interaction_dispatch import InteractionDispatchStore
from app.bobi_next.poll_dispatch_bridge import reconcile_poll_dispatches
from app.bobi_next.poll_interactions import (
    PollInteractionStore,
    PollVoteEvent,
)


def _vote(
    vote_id: str,
    selected: tuple[str, ...],
    timestamp: int,
) -> PollVoteEvent:
    return PollVoteEvent(
        provider="waha:main",
        vote_id=vote_id,
        poll_message_id="poll-1",
        voter_identity="1@c.us",
        selected_options=selected,
        provider_timestamp=timestamp,
    )


def test_reconcile_recovers_first_non_empty_accepted_vote_after_crash(tmp_path) -> None:
    interactions = PollInteractionStore(tmp_path / "interactions.db")
    dispatches = InteractionDispatchStore(tmp_path / "dispatch.db")
    try:
        interaction = interactions.register(
            provider="waha:main",
            poll_message_id="poll-1",
            chat_id="1@c.us",
            user_key="u1",
            question="Proceed?",
            option_keys={"Yes": "yes", "No": "no"},
            context_key="dialog:confirm-boiler",
            now_ts=1,
        )

        # An empty accepted selection is an un-vote and must not trigger work.
        assert interactions.apply_vote(_vote("vote-empty", (), 10), user_key="u1", now_ts=10).accepted
        # This accepted vote is durably committed before dispatch, simulating
        # the crash window the bridge must recover from.
        assert interactions.apply_vote(_vote("vote-yes", ("Yes",), 20), user_key="u1", now_ts=20).accepted
        # A later change may update poll state but cannot replace the first
        # actionable selection for an action-style continuation.
        assert interactions.apply_vote(_vote("vote-no", ("No",), 30), user_key="u1", now_ts=30).accepted

        created = reconcile_poll_dispatches(interactions, dispatches, now_ts=40)
        assert created == 1
        dispatch = dispatches.get_for_interaction(interaction.interaction_id)
        assert dispatch is not None
        assert dispatch.selected_keys == ("yes",)
        assert dispatch.source_event_id == "vote-yes"
        assert dispatch.provider_timestamp == 20

        # Recovery/retry is idempotent.
        assert reconcile_poll_dispatches(interactions, dispatches, now_ts=41) == 0
    finally:
        dispatches.close()
        interactions.close()


def test_reconcile_ignores_non_contextual_poll(tmp_path) -> None:
    interactions = PollInteractionStore(tmp_path / "interactions.db")
    dispatches = InteractionDispatchStore(tmp_path / "dispatch.db")
    try:
        interaction = interactions.register(
            provider="waha:main",
            poll_message_id="poll-1",
            chat_id="1@c.us",
            user_key="u1",
            question="Favourite?",
            option_keys={"A": "a", "B": "b"},
            context_key="",
            now_ts=1,
        )
        assert interactions.apply_vote(_vote("vote-a", ("A",), 20), user_key="u1", now_ts=20).accepted

        assert reconcile_poll_dispatches(interactions, dispatches, now_ts=30) == 0
        assert dispatches.get_for_interaction(interaction.interaction_id) is None
    finally:
        dispatches.close()
        interactions.close()
