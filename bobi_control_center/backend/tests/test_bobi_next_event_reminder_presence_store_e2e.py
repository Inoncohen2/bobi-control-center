from __future__ import annotations

from app.bobi_next.authorization import UserPolicy
from app.bobi_next.event_reminder_capture import capture_event_reminder
from app.bobi_next.intent import SemanticIntent
from app.bobi_next.models import DeviceRecord, EntityRecord
from app.bobi_next.presence_bindings import PresenceAwareEventReminderStore


def _presence() -> tuple[DeviceRecord, EntityRecord]:
    entity = EntityRecord(
        entity_id="person.user",
        domain="person",
        name="User",
        state="not_home",
        device_id="presence-device",
        platform="person",
        unique_id="user-1",
        capabilities=frozenset(),
    )
    return (
        DeviceRecord(
            bobi_id="presence:user-1",
            stable_key="device:presence-device",
            name="User",
            entities=(entity,),
            capabilities=frozenset(),
        ),
        entity,
    )


def _intent() -> SemanticIntent:
    return SemanticIntent(
        raw_text="תזכיר לי לקחת את החבילה כשאני מגיעה הביתה",
        family="reminder",
        domain="reminder",
        operation="create",
        target_text="לקחת את החבילה",
        conditional=True,
        confidence=0.99,
        condition_payload={
            "kind": "state",
            "trigger_target_text": "אני",
            "trigger_domain": "person",
            "to_state": "home",
            "once": True,
        },
    )


def test_presence_aware_store_resolves_self_without_engine_entity_injection(tmp_path) -> None:
    store = PresenceAwareEventReminderStore(
        tmp_path / "event-reminders.db",
        presence_path=tmp_path / "presence.db",
    )
    device, entity = _presence()
    try:
        store.presence_bindings.bind(user_key="u1", entity=entity, now_ts=50)
        result = capture_event_reminder(
            request_id="req-1",
            user_key="u1",
            provider_key="wa-main",
            chat_id="chat-1",
            source_message_id="m1",
            intent=_intent(),
            devices=(device,),
            policy=UserPolicy("u1"),
            store=store,
            now_ts=100,
        )

        assert result.outcome == "created"
        assert result.resolution is not None
        assert result.resolution.resolution_kind == "presence_binding"
        assert result.definition is not None
        assert result.definition.trigger.entity.entity_id == "person.user"
    finally:
        store.close()


def test_presence_aware_store_without_binding_fails_closed(tmp_path) -> None:
    store = PresenceAwareEventReminderStore(
        tmp_path / "event-reminders.db",
        presence_path=tmp_path / "presence.db",
    )
    device, _ = _presence()
    try:
        result = capture_event_reminder(
            request_id="req-1",
            user_key="u1",
            provider_key="wa-main",
            chat_id="chat-1",
            source_message_id="m1",
            intent=_intent(),
            devices=(device,),
            policy=UserPolicy("u1"),
            store=store,
            now_ts=100,
        )
        assert result.outcome == "clarification"
        assert result.reason == "presence_binding_required"
        assert store.list_enabled() == ()
    finally:
        store.close()
