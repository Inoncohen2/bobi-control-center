from __future__ import annotations

import sqlite3

import pytest

from app.bobi_next.authorization import RiskLevel, UserPolicy
from app.bobi_next.setup_store import SetupStore


def _configured_store(tmp_path):
    store = SetupStore(tmp_path / "setup.db")
    provider = store.upsert_provider(
        provider_key="waha:primary",
        provider_type="waha",
        display_name="WhatsApp",
        endpoint="http://messaging.local",
        session="primary",
        engine="GOWS",
        secret_ref="secret://messaging/api",
        now_ts=10,
    )
    user = store.create_user(
        display_name="Owner",
        role="owner",
        user_key="usr_owner",
        now_ts=11,
    )
    return store, provider, user


def test_new_installation_is_not_ready_until_provider_user_and_identity_exist(tmp_path):
    store = SetupStore(tmp_path / "setup.db")
    try:
        initial = store.status()
        assert initial.ready is False
        assert initial.completed is False
        assert initial.missing_steps == (
            "messaging_provider",
            "user",
            "user_identity",
        )

        store.upsert_provider(
            provider_key="waha:primary",
            provider_type="waha",
            display_name="WhatsApp",
            now_ts=10,
        )
        store.create_user(
            display_name="Owner",
            role="owner",
            user_key="usr_owner",
            now_ts=11,
        )
        before_identity = store.status()
        assert before_identity.ready is False
        assert before_identity.missing_steps == ("user_identity",)

        store.link_identity(
            provider_key="waha:primary",
            external_id="external-sender-001",
            user_key="usr_owner",
            identity_label="owner phone",
            now_ts=12,
        )
        ready = store.status()
        assert ready.ready is True
        assert ready.completed is False

        completed = store.mark_completed(now_ts=13)
        assert completed.ready is True
        assert completed.completed is True
    finally:
        store.close()


def test_setup_cannot_be_completed_early(tmp_path):
    store = SetupStore(tmp_path / "setup.db")
    try:
        with pytest.raises(RuntimeError, match="setup_incomplete"):
            store.mark_completed(now_ts=10)
    finally:
        store.close()


def test_external_identity_resolves_to_stable_internal_user(tmp_path):
    store, _, user = _configured_store(tmp_path)
    try:
        store.link_identity(
            provider_key="waha:primary",
            external_id="sender-alpha",
            user_key=user.user_key,
            now_ts=12,
        )
        resolved = store.resolve_user("waha:primary", "sender-alpha")
        assert resolved is not None
        assert resolved.user_key == "usr_owner"

        store.upsert_provider(
            provider_key="future-provider:primary",
            provider_type="official_whatsapp",
            display_name="Official WhatsApp",
            now_ts=13,
        )
        store.link_identity(
            provider_key="future-provider:primary",
            external_id="different-provider-id",
            user_key=user.user_key,
            now_ts=14,
        )
        resolved_elsewhere = store.resolve_user(
            "future-provider:primary",
            "different-provider-id",
        )
        assert resolved_elsewhere is not None
        assert resolved_elsewhere.user_key == user.user_key
    finally:
        store.close()


def test_unknown_or_disabled_identity_fails_closed(tmp_path):
    store, _, user = _configured_store(tmp_path)
    try:
        store.link_identity(
            provider_key="waha:primary",
            external_id="known-sender",
            user_key=user.user_key,
            now_ts=12,
        )
        assert store.resolve_user("waha:primary", "unknown-sender") is None

        store.set_user_enabled(user.user_key, False, now_ts=13)
        assert store.resolve_user("waha:primary", "known-sender") is None
    finally:
        store.close()


def test_external_identity_is_not_stored_as_plaintext(tmp_path):
    path = tmp_path / "setup.db"
    store, _, user = _configured_store(tmp_path)
    external_id = "sender-sensitive-value"
    try:
        store.link_identity(
            provider_key="waha:primary",
            external_id=external_id,
            user_key=user.user_key,
            now_ts=12,
        )
        row = store._db.execute(
            "SELECT identity_hash FROM user_identities WHERE user_key=?",
            (user.user_key,),
        ).fetchone()
        assert row is not None
        assert row["identity_hash"] != external_id
        assert len(row["identity_hash"]) == 64
    finally:
        store.close()

    raw_database = path.read_bytes()
    assert external_id.encode() not in raw_database


def test_safe_snapshot_omits_external_identity_endpoint_and_secret_ref(tmp_path):
    store, _, user = _configured_store(tmp_path)
    try:
        external_id = "private-sender-id"
        secret_ref = store.get_provider("waha:primary").secret_ref
        endpoint = store.get_provider("waha:primary").endpoint
        store.link_identity(
            provider_key="waha:primary",
            external_id=external_id,
            user_key=user.user_key,
            now_ts=12,
        )
        snapshot = store.safe_snapshot()
        rendered = repr(snapshot)
        assert external_id not in rendered
        assert secret_ref not in rendered
        assert endpoint not in rendered
        assert snapshot["providers"][0]["has_secret_ref"] is True
        assert snapshot["linked_identities"] == 1
    finally:
        store.close()


def test_user_policy_round_trips_and_can_be_changed_without_helpers(tmp_path):
    store, _, user = _configured_store(tmp_path)
    try:
        assert user.policy.max_without_approval is RiskLevel.MEDIUM
        assert user.policy.can_approve is True

        restricted = UserPolicy(
            user_key=user.user_key,
            allowed_capabilities=frozenset({"power", "temperature"}),
            denied_capabilities=frozenset({"lock"}),
            allowed_domains=frozenset({"switch", "climate"}),
            denied_actions=frozenset({"switch.turn_on"}),
            max_without_approval=RiskLevel.LOW,
            can_approve=False,
        )
        updated = store.update_user_policy(user.user_key, restricted, now_ts=20)
        assert updated.policy == restricted

        store.close()
        store = SetupStore(tmp_path / "setup.db")
        reloaded = store.get_user(user.user_key)
        assert reloaded is not None
        assert reloaded.policy == restricted
    finally:
        store.close()


def test_guest_defaults_are_restricted_and_cannot_approve(tmp_path):
    store = SetupStore(tmp_path / "setup.db")
    try:
        guest = store.create_user(
            display_name="Guest",
            role="guest",
            user_key="usr_guest",
            now_ts=10,
        )
        assert guest.policy.can_approve is False
        assert "lock" not in guest.policy.allowed_domains
        assert "*" not in guest.policy.allowed_domains
        assert guest.policy.max_without_approval is RiskLevel.LOW
    finally:
        store.close()


def test_duplicate_identity_cannot_be_silently_reassigned(tmp_path):
    store, _, _ = _configured_store(tmp_path)
    try:
        second = store.create_user(
            display_name="Second",
            role="member",
            user_key="usr_second",
            now_ts=12,
        )
        store.link_identity(
            provider_key="waha:primary",
            external_id="same-sender",
            user_key="usr_owner",
            now_ts=13,
        )
        with pytest.raises(ValueError, match="identity_already_linked"):
            store.link_identity(
                provider_key="waha:primary",
                external_id="same-sender",
                user_key=second.user_key,
                now_ts=14,
            )
        resolved = store.resolve_user("waha:primary", "same-sender")
        assert resolved is not None
        assert resolved.user_key == "usr_owner"
    finally:
        store.close()


def test_identity_hash_is_installation_specific(tmp_path):
    first_path = tmp_path / "one.db"
    second_path = tmp_path / "two.db"
    first = SetupStore(first_path)
    second = SetupStore(second_path)
    try:
        for store in (first, second):
            store.upsert_provider(
                provider_key="waha:primary",
                provider_type="waha",
                display_name="WhatsApp",
                now_ts=1,
            )
            store.create_user(
                display_name="Owner",
                role="owner",
                user_key="usr_owner",
                now_ts=2,
            )
            store.link_identity(
                provider_key="waha:primary",
                external_id="same-external-id",
                user_key="usr_owner",
                now_ts=3,
            )

        with sqlite3.connect(first_path) as db:
            first_hash = db.execute("SELECT identity_hash FROM user_identities").fetchone()[0]
        with sqlite3.connect(second_path) as db:
            second_hash = db.execute("SELECT identity_hash FROM user_identities").fetchone()[0]
        assert first_hash != second_hash
    finally:
        first.close()
        second.close()
