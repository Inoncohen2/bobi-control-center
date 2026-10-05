from __future__ import annotations

from app.bobi_next.authorization import UserPolicy
from app.bobi_next.event_reminder_capture import capture_event_reminder
from app.bobi_next.event_reminders import EventReminderStore
from app.bobi_next.intent import SemanticIntent
from app.bobi_next.models import DeviceRecord, EntityRecord


def _person(entity_id: str = "person.user") -> tuple[DeviceRecord, EntityRecord]:
    entity = EntityRecord(
        entity_id=entity_id,
        domain="person",
        name="User",
        state="not_home",
        device_id="presence-device",
        platform="person",
        unique_id="user-1",
        capabilities=frozenset(),
    )
    device = DeviceRecord(
        bobi_id="presence:user-1",
        stable_key="device:presence-device",
        name="User",
        entities=(entity,),
        capabilities=frozenset(),
    )
    return device, entity


def _intent(target: str = "אני", *, domain: str = "person") -> SemanticIntent:
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
            "trigger_target_text": target,
            "trigger_domain": domain,
            "to_state": "home",
            "once": True,
        },
    )


def test_self_target_requires_explicit_presence_binding(tmp_path) -> None:
    store = EventReminderStore(tmp_path / "events.db")
    device, _ = _person()
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


def test_self_target_uses_bound_presence_entity_and_not_name_resolution(tmp_path) -> None:
    store = EventReminderStore(tmp_path / "events.db")
    device, entity = _person("person.renamed_user")
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
            presence_entity=entity,
            now_ts=100,
        )
        assert result.outcome == "created"
        assert result.resolution is not None
        assert result.resolution.resolution_kind == "presence_binding"
        assert result.definition is not None
        assert result.definition.trigger.entity.entity_id == "person.renamed_user"
        assert result.definition.trigger.to_state == "home"
    finally:
        store.close()


def test_self_target_rejects_non_presence_domain_even_with_binding(tmp_path) -> None:
    store = EventReminderStore(tmp_path / "events.db")
    device, entity = _person()
    try:
        result = capture_event_reminder(
            request_id="req-1",
            user_key="u1",
            provider_key="wa-main",
            chat_id="chat-1",
            source_message_id="m1",
            intent=_intent(domain="binary_sensor"),
            devices=(device,),
            policy=UserPolicy("u1"),
            store=store,
            presence_entity=entity,
            now_ts=100,
        )
        assert result.outcome == "clarification"
        assert result.reason == "presence_trigger_domain_invalid"
        assert store.list_enabled() == ()
    finally:
        store.close()
