from __future__ import annotations

from app.bobi_next.poll_interactions import PollInteractionStore, PollVoteEvent
from app.bobi_next.waha_interactions import parse_waha_poll_vote


def _vote(
    *,
    vote_id: str = "vote-1",
    option: str = "Yes",
    timestamp: int = 100,
    failed: bool = False,
) -> PollVoteEvent:
    return PollVoteEvent(
        provider="waha-main",
        vote_id=vote_id,
        poll_message_id="poll-1",
        voter_identity="1@c.us",
        selected_options=(option,) if option else (),
        provider_timestamp=timestamp,
        failed=failed,
    )


def test_poll_store_maps_labels_to_stable_choice_keys(tmp_path) -> None:
    store = PollInteractionStore(tmp_path / "interactions.db")
    try:
        registered = store.register(
            provider="waha-main",
            poll_message_id="poll-1",
            chat_id="1@c.us",
            user_key="u1",
            question="Proceed?",
            option_keys={"Yes": "confirm", "No": "cancel"},
            now_ts=10,
        )
        result = store.apply_vote(_vote(), user_key="u1", now_ts=101)

        assert result.accepted is True
        assert result.interaction_id == registered.interaction_id
        assert result.selected_keys == ("confirm",)
        assert store.get("waha-main", "poll-1").selected_keys == ("confirm",)
    finally:
        store.close()


def test_duplicate_vote_is_exactly_once(tmp_path) -> None:
    store = PollInteractionStore(tmp_path / "interactions.db")
    try:
        store.register(
            provider="waha-main",
            poll_message_id="poll-1",
            chat_id="1@c.us",
            user_key="u1",
            question="Proceed?",
            option_keys={"Yes": "confirm", "No": "cancel"},
            now_ts=10,
        )
        first = store.apply_vote(_vote(), user_key="u1", now_ts=101)
        second = store.apply_vote(_vote(), user_key="u1", now_ts=102)

        assert first.accepted is True
        assert second.accepted is False
        assert second.duplicate is True
        assert second.reason == "duplicate_vote"
    finally:
        store.close()


def test_older_out_of_order_vote_cannot_overwrite_newer_selection(tmp_path) -> None:
    store = PollInteractionStore(tmp_path / "interactions.db")
    try:
        store.register(
            provider="waha-main",
            poll_message_id="poll-1",
            chat_id="1@c.us",
            user_key="u1",
            question="Choose",
            option_keys={"A": "a", "B": "b"},
            now_ts=10,
        )
        newest = store.apply_vote(
            _vote(vote_id="vote-new", option="B", timestamp=300),
            user_key="u1",
            now_ts=301,
        )
        stale = store.apply_vote(
            _vote(vote_id="vote-old", option="A", timestamp=200),
            user_key="u1",
            now_ts=302,
        )

        assert newest.selected_keys == ("b",)
        assert stale.accepted is False
        assert stale.reason == "stale_vote"
        assert store.get("waha-main", "poll-1").selected_keys == ("b",)
    finally:
        store.close()


def test_poll_vote_cannot_cross_user_boundary(tmp_path) -> None:
    store = PollInteractionStore(tmp_path / "interactions.db")
    try:
        store.register(
            provider="waha-main",
            poll_message_id="poll-1",
            chat_id="1@c.us",
            user_key="u1",
            question="Proceed?",
            option_keys={"Yes": "confirm"},
            now_ts=10,
        )
        result = store.apply_vote(_vote(), user_key="u2", now_ts=101)

        assert result.accepted is False
        assert result.reason == "interaction_user_mismatch"
        assert store.get("waha-main", "poll-1").selected_keys == ()
    finally:
        store.close()


def test_failed_poll_vote_requests_resend_without_selection(tmp_path) -> None:
    store = PollInteractionStore(tmp_path / "interactions.db")
    try:
        store.register(
            provider="waha-main",
            poll_message_id="poll-1",
            chat_id="1@c.us",
            user_key="u1",
            question="Proceed?",
            option_keys={"Yes": "confirm"},
            now_ts=10,
        )
        result = store.apply_vote(
            _vote(vote_id="vote-fail", option="", failed=True),
            user_key="u1",
            now_ts=101,
        )

        assert result.accepted is False
        assert result.reason == "poll_vote_failed"
        assert result.needs_resend is True
        assert store.get("waha-main", "poll-1").selected_keys == ()
    finally:
        store.close()


def test_parse_waha_poll_vote_keeps_raw_provider_order_timestamp() -> None:
    parsed = parse_waha_poll_vote(
        {
            "event": "poll.vote",
            "session": "default",
            "payload": {
                "vote": {
                    "id": "vote-1",
                    "from": "123@s.whatsapp.net",
                    "selectedOptions": ["A", "B"],
                    "timestamp": 1692861427123,
                },
                "poll": {
                    "id": "poll-1",
                    "fromMe": True,
                },
            },
        }
    )

    assert parsed is not None
    assert parsed.voter_identity == "123@c.us"
    assert parsed.selected_options == ("A", "B")
    assert parsed.provider_timestamp == 1692861427123
    assert parsed.failed is False


def test_parse_waha_poll_ignores_other_peoples_polls() -> None:
    parsed = parse_waha_poll_vote(
        {
            "event": "poll.vote",
            "payload": {
                "vote": {
                    "id": "vote-1",
                    "from": "123@c.us",
                    "selectedOptions": ["A"],
                    "timestamp": 1,
                },
                "poll": {"id": "poll-foreign", "fromMe": False},
            },
        }
    )
    assert parsed is None
