from __future__ import annotations

import pytest

from app.bobi_next.conditional import StateChangeEvent, TriggerSpec, trigger_ref
from app.bobi_next.event_reminders import EventReminderRuntime, EventReminderStore
from app.bobi_next.models import DeviceRecord, EntityRecord
from app.bobi_next.reminders import ReminderStore


def _entity(
    entity_id: str,
    *,
    domain: str = "person",
    device_id: str = "person-device",
    platform: str = "person",
    unique_id: str = "user-1",
    state: str = "not_home",
) -> EntityRecord:
    return EntityRecord(
        entity_id=entity_id,
        domain=domain,
        name="User",
        state=state,
        device_id=device_id,
        platform=platform,
        unique_id=unique_id,
        capabilities=frozenset(),
    )


def _device(entity: EntityRecord) -> DeviceRecord:
    return DeviceRecord(
        bobi_id="person:user-1",
        stable_key="device:person-device",
        name="User",
        entities=(entity,),
        capabilities=frozenset(),
    )


def _event(
    event_id: str,
    *,
    entity_id: str = "person.user",
    old: str = "not_home",
    new: str = "home",
    occurred_ts: int = 100,
) -> StateChangeEvent:
    return StateChangeEvent(
        event_id=event_id,
        entity_id=entity_id,
        old_state=old,
        new_state=new,
        old_attributes={},
        new_attributes={},
        occurred_ts=occurred_ts,
    )


@pytest.mark.asyncio
async def test_enter_home_event_queues_normal_reminder(tmp_path) -> None:
    definitions = EventReminderStore(tmp_path / "events.db")
    reminders = ReminderStore(tmp_path / "reminders.db")
    entity = _entity("person.user")
    definitions.create(
        trigger_id="arrive-home",
        user_key="u1",
        provider_key="wa-main",
        chat_id="chat-1",
        text="לקחת את החבילה מהרכב",
        trigger=TriggerSpec(kind="state", entity=trigger_ref(entity), to_state="home"),
        source_message_id="m1",
        now_ts=10,
    )

    async def devices():
        return (_device(entity),)

    runtime = EventReminderRuntime(
        definitions=definitions,
        reminders=reminders,
        list_devices=devices,
    )
    try:
        results = await runtime.observe_event(_event("evt-1"))
        assert len(results) == 1
        assert results[0].outcome == "queued"
        queued = reminders.get(results[0].reminder_id)
        assert queued is not None
        assert queued.text == "לקחת את החבילה מהרכב"
        assert queued.run_at_ts == 100
        assert queued.provider_key == "wa-main"
        assert queued.chat_id == "chat-1"
    finally:
        reminders.close()
        definitions.close()


@pytest.mark.asyncio
async def test_same_event_replay_never_creates_second_delivery(tmp_path) -> None:
    definitions = EventReminderStore(tmp_path / "events.db")
    reminders = ReminderStore(tmp_path / "reminders.db")
    entity = _entity("person.user")
    definitions.create(
        trigger_id="repeat-safe",
        user_key="u1",
        provider_key="wa-main",
        chat_id="chat-1",
        text="תזכורת",
        trigger=TriggerSpec(kind="state", entity=trigger_ref(entity), to_state="home"),
        once=False,
        now_ts=10,
    )

    async def devices():
        return (_device(entity),)

    runtime = EventReminderRuntime(
        definitions=definitions,
        reminders=reminders,
        list_devices=devices,
    )
    try:
        first = await runtime.observe_event(_event("same-event"))
        second = await runtime.observe_event(_event("same-event"))
        assert len(first) == 1
        assert second == ()
        assert len(reminders.list_for_user("u1")) == 1
    finally:
        reminders.close()
        definitions.close()


@pytest.mark.asyncio
async def test_once_definition_disables_after_first_match(tmp_path) -> None:
    definitions = EventReminderStore(tmp_path / "events.db")
    reminders = ReminderStore(tmp_path / "reminders.db")
    entity = _entity("person.user")
    definitions.create(
        trigger_id="once-only",
        user_key="u1",
        provider_key="wa-main",
        chat_id="chat-1",
        text="פעם אחת",
        trigger=TriggerSpec(kind="state", entity=trigger_ref(entity), to_state="home"),
        once=True,
        now_ts=10,
    )

    async def devices():
        return (_device(entity),)

    runtime = EventReminderRuntime(
        definitions=definitions,
        reminders=reminders,
        list_devices=devices,
    )
    try:
        await runtime.observe_event(_event("evt-1", occurred_ts=100))
        assert definitions.get("once-only").enabled is False
        assert await runtime.observe_event(_event("evt-2", occurred_ts=200)) == ()
        assert len(reminders.list_for_user("u1")) == 1
    finally:
        reminders.close()
        definitions.close()


@pytest.mark.asyncio
async def test_repeating_definition_honors_cooldown(tmp_path) -> None:
    definitions = EventReminderStore(tmp_path / "events.db")
    reminders = ReminderStore(tmp_path / "reminders.db")
    entity = _entity("person.user")
    definitions.create(
        trigger_id="cooldown",
        user_key="u1",
        provider_key="wa-main",
        chat_id="chat-1",
        text="חזרת הביתה",
        trigger=TriggerSpec(kind="state", entity=trigger_ref(entity), to_state="home"),
        once=False,
        cooldown_seconds=300,
        now_ts=10,
    )

    async def devices():
        return (_device(entity),)

    runtime = EventReminderRuntime(
        definitions=definitions,
        reminders=reminders,
        list_devices=devices,
    )
    try:
        assert len(await runtime.observe_event(_event("evt-1", occurred_ts=100))) == 1
        assert await runtime.observe_event(_event("evt-2", occurred_ts=200)) == ()
        assert len(await runtime.observe_event(_event("evt-3", occurred_ts=401))) == 1
        assert len(reminders.list_for_user("u1")) == 2
    finally:
        reminders.close()
        definitions.close()


@pytest.mark.asyncio
async def test_stable_identity_survives_entity_id_rename(tmp_path) -> None:
    definitions = EventReminderStore(tmp_path / "events.db")
    reminders = ReminderStore(tmp_path / "reminders.db")
    old_entity = _entity("person.old_name")
    renamed = _entity("person.new_name")
    definitions.create(
        trigger_id="rename-safe",
        user_key="u1",
        provider_key="wa-main",
        chat_id="chat-1",
        text="הגעת הביתה",
        trigger=TriggerSpec(kind="state", entity=trigger_ref(old_entity), to_state="home"),
        now_ts=10,
    )

    async def devices():
        return (_device(renamed),)

    runtime = EventReminderRuntime(
        definitions=definitions,
        reminders=reminders,
        list_devices=devices,
    )
    try:
        results = await runtime.observe_event(
            _event("evt-rename", entity_id="person.new_name", occurred_ts=100)
        )
        assert len(results) == 1
        assert reminders.get(results[0].reminder_id) is not None
    finally:
        reminders.close()
        definitions.close()


@pytest.mark.asyncio
async def test_leave_home_is_generic_from_state_transition(tmp_path) -> None:
    definitions = EventReminderStore(tmp_path / "events.db")
    reminders = ReminderStore(tmp_path / "reminders.db")
    entity = _entity("person.user", state="home")
    definitions.create(
        trigger_id="leave-home",
        user_key="u1",
        provider_key="wa-main",
        chat_id="chat-1",
        text="לכבות את המזגן כשתצאי",
        trigger=TriggerSpec(kind="state", entity=trigger_ref(entity), from_state="home"),
        now_ts=10,
    )

    async def devices():
        return (_device(entity),)

    runtime = EventReminderRuntime(
        definitions=definitions,
        reminders=reminders,
        list_devices=devices,
    )
    try:
        results = await runtime.observe_event(
            _event("evt-leave", old="home", new="not_home", occurred_ts=100)
        )
        assert len(results) == 1
    finally:
        reminders.close()
        definitions.close()


def test_duration_event_reminder_fails_closed_until_duration_runtime_is_supported(tmp_path) -> None:
    definitions = EventReminderStore(tmp_path / "events.db")
    entity = _entity("person.user")
    try:
        with pytest.raises(ValueError, match="event_reminder_duration_not_supported"):
            definitions.create(
                trigger_id="duration",
                user_key="u1",
                provider_key="wa-main",
                chat_id="chat-1",
                text="תזכורת",
                trigger=TriggerSpec(
                    kind="state",
                    entity=trigger_ref(entity),
                    to_state="home",
                    for_seconds=30,
                ),
                now_ts=10,
            )
    finally:
        definitions.close()
