from __future__ import annotations

from app.bobi_next.authorization import UserPolicy
from app.bobi_next.event_reminder_capture import capture_event_reminder
from app.bobi_next.event_reminders import EventReminderStore
from app.bobi_next.intent import SemanticIntent
from app.bobi_next.models import DeviceRecord, EntityRecord


def _device(
    *,
    name: str = "Front door",
    entity_id: str = "binary_sensor.front_door",
    domain: str = "binary_sensor",
    device_id: str = "dev-door",
    platform: str = "zha",
    unique_id: str = "door-1",
) -> DeviceRecord:
    entity = EntityRecord(
        entity_id=entity_id,
        domain=domain,
        name=name,
        state="off",
        device_id=device_id,
        platform=platform,
        unique_id=unique_id,
        capabilities=frozenset(),
    )
    return DeviceRecord(
        bobi_id=f"device:{device_id}",
        stable_key=f"device:{device_id}",
        name=name,
        entities=(entity,),
        capabilities=frozenset(),
    )


def _intent(
    *,
    trigger_target: str = "Front door",
    trigger_domain: str = "binary_sensor",
    kind: str = "state",
    from_state=None,
    to_state="on",
    above=None,
    below=None,
    conditional: bool = True,
    scheduled: bool = False,
    negated: bool = False,
) -> SemanticIntent:
    return SemanticIntent(
        raw_text="remind me when front door opens",
        family="reminder",
        domain="reminder",
        operation="create",
        target_text="check who entered",
        conditional=conditional,
        scheduled=scheduled,
        negated=negated,
        confidence=0.99,
        condition_payload={
            "kind": kind,
            "trigger_target_text": trigger_target,
            "trigger_domain": trigger_domain,
            "from_state": from_state,
            "to_state": to_state,
            "above": above,
            "below": below,
        },
    )


def _policy() -> UserPolicy:
    return UserPolicy("u1")


def test_capture_resolves_semantic_target_and_persists_stable_identity(tmp_path) -> None:
    store = EventReminderStore(tmp_path / "events.db")
    try:
        result = capture_event_reminder(
            request_id="req-1",
            user_key="u1",
            provider_key="wa-main",
            chat_id="chat-1",
            source_message_id="m1",
            intent=_intent(),
            devices=(_device(),),
            policy=_policy(),
            store=store,
            now_ts=100,
        )
        assert result.outcome == "created"
        assert result.definition is not None
        assert result.definition.text == "check who entered"
        assert result.definition.trigger.to_state == "on"
        assert result.definition.trigger.entity.stable_key.startswith("device:dev-door:entity:")
    finally:
        store.close()


def test_capture_never_uses_ai_supplied_entity_id_as_authority(tmp_path) -> None:
    store = EventReminderStore(tmp_path / "events.db")
    intent = _intent(trigger_target="does not exist")
    intent.condition_payload["entity_id"] = "lock.front_door"
    try:
        result = capture_event_reminder(
            request_id="req-1",
            user_key="u1",
            provider_key="wa-main",
            chat_id="chat-1",
            source_message_id="m1",
            intent=intent,
            devices=(_device(),),
            policy=_policy(),
            store=store,
            now_ts=100,
        )
        assert result.outcome == "clarification"
        assert result.reason == "no_target_match"
        assert store.list_enabled() == ()
    finally:
        store.close()


def test_capture_fails_closed_on_ambiguous_trigger_target(tmp_path) -> None:
    store = EventReminderStore(tmp_path / "events.db")
    first = _device(name="Patio door", entity_id="binary_sensor.patio_1", device_id="d1", unique_id="u1")
    second = _device(name="Patio door", entity_id="binary_sensor.patio_2", device_id="d2", unique_id="u2")
    try:
        result = capture_event_reminder(
            request_id="req-1",
            user_key="u1",
            provider_key="wa-main",
            chat_id="chat-1",
            source_message_id="m1",
            intent=_intent(trigger_target="Patio door"),
            devices=(first, second),
            policy=_policy(),
            store=store,
            now_ts=100,
        )
        assert result.outcome == "clarification"
        assert result.resolution is not None and result.resolution.ambiguous
    finally:
        store.close()


def test_capture_policy_can_block_reminder_creation(tmp_path) -> None:
    store = EventReminderStore(tmp_path / "events.db")
    policy = UserPolicy(
        "u1",
        allowed_capabilities=frozenset({"device.control"}),
        allowed_domains=frozenset({"light"}),
    )
    try:
        result = capture_event_reminder(
            request_id="req-1",
            user_key="u1",
            provider_key="wa-main",
            chat_id="chat-1",
            source_message_id="m1",
            intent=_intent(),
            devices=(_device(),),
            policy=policy,
            store=store,
            now_ts=100,
        )
        assert result.outcome == "blocked"
        assert result.reason == "capability_not_allowed"
    finally:
        store.close()


def test_capture_negation_and_questions_never_persist(tmp_path) -> None:
    store = EventReminderStore(tmp_path / "events.db")
    try:
        negated = capture_event_reminder(
            request_id="neg",
            user_key="u1",
            provider_key="wa-main",
            chat_id="chat-1",
            source_message_id="m1",
            intent=_intent(negated=True),
            devices=(_device(),),
            policy=_policy(),
            store=store,
            now_ts=100,
        )
        question_intent = _intent()
        question_intent.metadata["question"] = True
        question = capture_event_reminder(
            request_id="question",
            user_key="u1",
            provider_key="wa-main",
            chat_id="chat-1",
            source_message_id="m2",
            intent=question_intent,
            devices=(_device(),),
            policy=_policy(),
            store=store,
            now_ts=100,
        )
        assert negated.outcome == "ignored"
        assert question.outcome == "ignored"
        assert store.list_enabled() == ()
    finally:
        store.close()


def test_capture_time_and_event_conflict_requests_clarification(tmp_path) -> None:
    store = EventReminderStore(tmp_path / "events.db")
    try:
        result = capture_event_reminder(
            request_id="req-1",
            user_key="u1",
            provider_key="wa-main",
            chat_id="chat-1",
            source_message_id="m1",
            intent=_intent(scheduled=True),
            devices=(_device(),),
            policy=_policy(),
            store=store,
            now_ts=100,
        )
        assert result.outcome == "clarification"
        assert result.reason == "reminder_time_and_event_conflict"
    finally:
        store.close()


def test_capture_numeric_threshold_requires_real_threshold(tmp_path) -> None:
    store = EventReminderStore(tmp_path / "events.db")
    temperature = _device(
        name="Outdoor temperature",
        entity_id="sensor.outdoor_temperature",
        domain="sensor",
        device_id="weather",
        platform="mqtt",
        unique_id="outdoor-temp",
    )
    try:
        missing = capture_event_reminder(
            request_id="missing",
            user_key="u1",
            provider_key="wa-main",
            chat_id="chat-1",
            source_message_id="m1",
            intent=_intent(
                trigger_target="Outdoor temperature",
                trigger_domain="sensor",
                kind="numeric",
                to_state=None,
            ),
            devices=(temperature,),
            policy=_policy(),
            store=store,
            now_ts=100,
        )
        valid = capture_event_reminder(
            request_id="valid",
            user_key="u1",
            provider_key="wa-main",
            chat_id="chat-1",
            source_message_id="m2",
            intent=_intent(
                trigger_target="Outdoor temperature",
                trigger_domain="sensor",
                kind="numeric",
                to_state=None,
                above=30,
            ),
            devices=(temperature,),
            policy=_policy(),
            store=store,
            now_ts=100,
        )
        assert missing.outcome == "clarification"
        assert missing.reason == "event_reminder_numeric_threshold_required"
        assert valid.outcome == "created"
        assert valid.definition is not None
        assert valid.definition.trigger.above == 30
    finally:
        store.close()


def test_capture_dry_run_has_no_side_effect(tmp_path) -> None:
    store = EventReminderStore(tmp_path / "events.db")
    try:
        result = capture_event_reminder(
            request_id="req-1",
            user_key="u1",
            provider_key="wa-main",
            chat_id="chat-1",
            source_message_id="m1",
            intent=_intent(),
            devices=(_device(),),
            policy=_policy(),
            store=store,
            now_ts=100,
            dry_run=True,
        )
        assert result.outcome == "shadow"
        assert result.metadata is not None
        assert result.metadata["trigger_stable_key"]
        assert store.list_enabled() == ()
    finally:
        store.close()
