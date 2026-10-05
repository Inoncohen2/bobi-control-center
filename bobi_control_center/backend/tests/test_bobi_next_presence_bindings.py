from __future__ import annotations

import pytest

from app.bobi_next.models import DeviceRecord, EntityRecord
from app.bobi_next.presence_bindings import PresenceBindingStore


def _entity(
    entity_id: str = "person.user",
    *,
    domain: str = "person",
    device_id: str = "presence-device",
    platform: str = "person",
    unique_id: str = "user-1",
) -> EntityRecord:
    return EntityRecord(
        entity_id=entity_id,
        domain=domain,
        name="User",
        state="home",
        device_id=device_id,
        platform=platform,
        unique_id=unique_id,
        capabilities=frozenset(),
    )


def _device(entity: EntityRecord) -> DeviceRecord:
    return DeviceRecord(
        bobi_id="presence:user-1",
        stable_key="device:presence-device",
        name="User",
        entities=(entity,),
        capabilities=frozenset(),
    )


def test_binding_requires_discovered_presence_domain_and_stable_identity(tmp_path) -> None:
    store = PresenceBindingStore(tmp_path / "presence.db")
    try:
        with pytest.raises(ValueError, match="presence_entity_domain_invalid"):
            store.bind(user_key="u1", entity=_entity(domain="light"), now_ts=100)

        unstable = _entity(
            entity_id="person.unstable",
            device_id="",
            platform="",
            unique_id="",
        )
        with pytest.raises(ValueError, match="presence_entity_stable_identity_required"):
            store.bind(user_key="u1", entity=unstable, now_ts=100)
    finally:
        store.close()


def test_binding_resolves_after_entity_id_rename(tmp_path) -> None:
    store = PresenceBindingStore(tmp_path / "presence.db")
    original = _entity("person.old_name")
    renamed = _entity("person.new_name")
    try:
        binding = store.bind(user_key="u1", entity=original, now_ts=100)
        assert binding.entity.entity_id == "person.old_name"
        live = store.resolve_live("u1", (_device(renamed),))
        assert live is not None
        assert live.entity_id == "person.new_name"
    finally:
        store.close()


def test_rebinding_updates_identity_without_duplicate_user_rows(tmp_path) -> None:
    store = PresenceBindingStore(tmp_path / "presence.db")
    first = _entity("person.first", unique_id="first")
    second = _entity("device_tracker.phone", domain="device_tracker", platform="mobile_app", unique_id="phone")
    try:
        store.bind(user_key="u1", entity=first, now_ts=100)
        updated = store.bind(user_key="u1", entity=second, now_ts=200)
        assert updated.entity.domain == "device_tracker"
        assert updated.entity.entity_id == "device_tracker.phone"
        assert updated.created_ts == 100
        assert updated.updated_ts == 200
    finally:
        store.close()


def test_unbound_or_missing_live_entity_fails_closed(tmp_path) -> None:
    store = PresenceBindingStore(tmp_path / "presence.db")
    try:
        assert store.resolve_live("missing", ()) is None
        store.bind(user_key="u1", entity=_entity(), now_ts=100)
        assert store.resolve_live("u1", ()) is None
        assert store.unbind("u1") is True
        assert store.get("u1") is None
        assert store.unbind("u1") is False
    finally:
        store.close()
