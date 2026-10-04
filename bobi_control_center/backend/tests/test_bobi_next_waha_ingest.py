from __future__ import annotations

import sqlite3

from app.bobi_next.messaging import MessageStore
from app.bobi_next.setup_store import SetupStore
from app.bobi_next.waha_ingest import ingest_waha_event


def _stores(tmp_path):
    setup = SetupStore(tmp_path / "setup.db")
    messages = MessageStore(tmp_path / "messages.db")
    setup.upsert_provider(
        provider_key="waha:primary",
        provider_type="waha",
        display_name="WhatsApp",
        session="primary",
        engine="GOWS",
        now_ts=1,
    )
    setup.create_user(
        display_name="Owner",
        role="owner",
        user_key="usr_owner",
        now_ts=2,
    )
    setup.link_identity(
        provider_key="waha:primary",
        external_id="111@c.us",
        user_key="usr_owner",
        now_ts=3,
    )
    return setup, messages


def _event(
    *,
    message_id="m1",
    sender="111@c.us",
    session="primary",
    body="hello",
    has_media=False,
    media=None,
):
    return {
        "event": "message",
        "session": session,
        "payload": {
            "id": message_id,
            "timestamp": 100,
            "from": sender,
            "fromMe": False,
            "body": body,
            "hasMedia": has_media,
            "media": media,
        },
    }


def test_known_configured_sender_is_mapped_to_internal_user_and_enqueued(tmp_path):
    setup, messages = _stores(tmp_path)
    try:
        result = ingest_waha_event(
            _event(),
            provider_key="waha:primary",
            setup=setup,
            messages=messages,
            now_ts=100,
        )
        assert result.accepted is True
        assert result.user_key == "usr_owner"

        stored = messages.get_inbound("waha:primary", "m1")
        assert stored is not None
        assert stored.user_key == "usr_owner"
        assert stored.chat_id == "111@c.us"
        assert stored.text == "hello"
        assert stored.metadata["session"] == "primary"
    finally:
        setup.close()
        messages.close()


def test_unknown_sender_is_rejected_without_creating_guest(tmp_path):
    setup, messages = _stores(tmp_path)
    try:
        result = ingest_waha_event(
            _event(sender="999@c.us"),
            provider_key="waha:primary",
            setup=setup,
            messages=messages,
            now_ts=100,
        )
        assert result.accepted is False
        assert result.reason == "unknown_or_disabled_sender"
        assert messages.get_inbound("waha:primary", "m1") is None
        assert len(setup.list_users()) == 1
    finally:
        setup.close()
        messages.close()


def test_provider_session_mismatch_fails_closed(tmp_path):
    setup, messages = _stores(tmp_path)
    try:
        result = ingest_waha_event(
            _event(session="other"),
            provider_key="waha:primary",
            setup=setup,
            messages=messages,
        )
        assert result.accepted is False
        assert result.reason == "session_mismatch"
        assert messages.get_inbound("waha:primary", "m1") is None
    finally:
        setup.close()
        messages.close()


def test_duplicate_webhook_is_reported_and_not_enqueued_twice(tmp_path):
    setup, messages = _stores(tmp_path)
    try:
        first = ingest_waha_event(
            _event(),
            provider_key="waha:primary",
            setup=setup,
            messages=messages,
        )
        second = ingest_waha_event(
            _event(),
            provider_key="waha:primary",
            setup=setup,
            messages=messages,
        )
        assert first.accepted is True
        assert second.accepted is False
        assert second.duplicate is True
        assert second.reason == "duplicate_message"
    finally:
        setup.close()
        messages.close()


def test_voice_media_metadata_survives_durable_inbox_round_trip(tmp_path):
    setup, messages = _stores(tmp_path)
    try:
        result = ingest_waha_event(
            _event(
                message_id="voice-1",
                body="",
                has_media=True,
                media={
                    "url": "http://provider.local/files/voice.ogg",
                    "mimetype": "audio/ogg; codecs=opus",
                    "filename": "voice.ogg",
                },
            ),
            provider_key="waha:primary",
            setup=setup,
            messages=messages,
        )
        assert result.accepted is True
        stored = messages.get_inbound("waha:primary", "voice-1")
        assert stored is not None
        assert stored.kind == "voice"
        assert stored.metadata["media"] == {
            "url": "http://provider.local/files/voice.ogg",
            "mimetype": "audio/ogg; codecs=opus",
            "filename": "voice.ogg",
        }
    finally:
        setup.close()
        messages.close()


def test_outgoing_waha_message_is_ignored_before_identity_resolution(tmp_path):
    setup, messages = _stores(tmp_path)
    try:
        event = _event(sender="999@c.us")
        event["payload"]["fromMe"] = True
        result = ingest_waha_event(
            event,
            provider_key="waha:primary",
            setup=setup,
            messages=messages,
        )
        assert result.accepted is False
        assert result.reason == "ignored_event"
    finally:
        setup.close()
        messages.close()


def test_message_store_migrates_pre_metadata_database_without_losing_rows(tmp_path):
    path = tmp_path / "legacy-messages.db"
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            CREATE TABLE inbound_messages (
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
            CREATE TABLE outbound_messages (
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
            """
        )
        db.execute(
            """
            INSERT INTO inbound_messages(
                provider,message_id,chat_id,user_key,text,kind,received_ts,
                state,next_attempt_ts
            ) VALUES('waha:test','old-1','chat','usr','old','text',1,'pending',1)
            """
        )
        db.commit()

    store = MessageStore(path)
    try:
        old = store.get_inbound("waha:test", "old-1")
        assert old is not None
        assert old.text == "old"
        assert old.metadata == {}

        inserted = store.enqueue(
            provider="waha:test",
            message_id="new-1",
            chat_id="chat",
            user_key="usr",
            text="new",
            metadata={"media": {"mimetype": "image/jpeg"}},
            received_ts=2,
        )
        assert inserted is True
        new = store.get_inbound("waha:test", "new-1")
        assert new is not None
        assert new.metadata["media"]["mimetype"] == "image/jpeg"
    finally:
        store.close()
