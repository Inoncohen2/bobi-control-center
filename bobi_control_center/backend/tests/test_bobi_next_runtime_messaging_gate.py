from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.bobi_next.runtime_service as runtime_service_module
from app.bobi_next.conditional import StateChangeEvent
from app.bobi_next.event_reminders import EventReminderStore
from app.bobi_next.pending_approval import PendingApprovalStore
from app.bobi_next.reminders import ReminderStore
from app.bobi_next.runtime_service import BobiNextRuntimeService
from app.config import Settings


class DummyNative:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class DummyCatalog:
    async def get_devices(self):
        return ()


@pytest.mark.asyncio
async def test_messaging_gate_disabled_does_not_construct_runtime(tmp_path, monkeypatch):
    service = BobiNextRuntimeService(
        Settings(adapter="mock", data_dir=tmp_path, next_messaging_enabled=False)
    )

    class MustNotConstruct:
        def __init__(self, *args, **kwargs):
            del args, kwargs
            raise AssertionError("messaging runtime must stay dormant")

    monkeypatch.setattr(runtime_service_module, "ArchiveMessagingRuntime", MustNotConstruct)
    try:
        await service._start_messaging_if_enabled()
        assert service.messaging is None
        assert service.event_reminder_runtime is None
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_messaging_gate_starts_shadow_runtime_with_shared_dependencies(
    tmp_path,
    monkeypatch,
):
    service = BobiNextRuntimeService(
        Settings(
            adapter="mock",
            data_dir=tmp_path,
            next_messaging_enabled=True,
            next_messaging_dry_run=True,
        )
    )
    native = DummyNative()
    catalog = DummyCatalog()
    pending = PendingApprovalStore(tmp_path / "pending.db")
    service.native = native
    service.catalog = catalog
    service.pending_approvals = pending
    constructed = []

    class FakeMessagingRuntime:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.closed = False
            self.reminders = ReminderStore(tmp_path / "runtime-reminders.db")
            self.event_reminders = EventReminderStore(tmp_path / "runtime-event-reminders.db")
            constructed.append(self)

        async def start(self):
            return SimpleNamespace(ready=True, reason="started", providers=("waha-main",))

        async def aclose(self):
            if not self.closed:
                self.event_reminders.close()
                self.reminders.close()
                self.closed = True

    monkeypatch.setattr(
        runtime_service_module,
        "ArchiveMessagingRuntime",
        FakeMessagingRuntime,
    )
    try:
        await service._start_messaging_if_enabled()
        assert len(constructed) == 1
        runtime = constructed[0]
        assert service.messaging is runtime
        assert runtime.kwargs["ha"] is native
        assert runtime.kwargs["list_devices"].__self__ is catalog
        assert runtime.kwargs["pending_approvals"] is pending
        assert runtime.kwargs["dry_run"] is True
        assert service.event_reminder_runtime is not None
        assert service.event_reminder_runtime.definitions is runtime.event_reminders
        assert service.event_reminder_runtime.reminders is runtime.reminders
        assert service.event_reminder_runtime.list_devices.__self__ is catalog
    finally:
        await service.aclose()

    assert constructed[0].closed is True
    assert native.closed is True


@pytest.mark.asyncio
async def test_event_reminder_observer_is_fail_closed_and_isolated(tmp_path):
    service = BobiNextRuntimeService(Settings(adapter="mock", data_dir=tmp_path))
    seen = []

    class FakeEventReminderRuntime:
        async def observe_event(self, event):
            seen.append(event)
            return (SimpleNamespace(outcome="queued"),)

    service.event_reminder_runtime = FakeEventReminderRuntime()
    event = StateChangeEvent(
        event_id="evt-1",
        entity_id="person.user",
        old_state="not_home",
        new_state="home",
        old_attributes={},
        new_attributes={},
        occurred_ts=100,
    )
    try:
        await service._observe_event_reminders(event)
        assert seen == [event]

        class BrokenRuntime:
            async def observe_event(self, event):
                del event
                raise RuntimeError("boom")

        service.event_reminder_runtime = BrokenRuntime()
        await service._observe_event_reminders(event)
    finally:
        service.event_reminder_runtime = None
        await service.aclose()


@pytest.mark.asyncio
async def test_messaging_not_ready_fails_closed_without_becoming_active(
    tmp_path,
    monkeypatch,
):
    service = BobiNextRuntimeService(
        Settings(adapter="mock", data_dir=tmp_path, next_messaging_enabled=True)
    )
    service.native = DummyNative()
    service.catalog = DummyCatalog()
    service.pending_approvals = PendingApprovalStore(tmp_path / "pending.db")
    instances = []

    class NotReadyRuntime:
        def __init__(self, **kwargs):
            del kwargs
            self.closed = False
            instances.append(self)

        async def start(self):
            return SimpleNamespace(ready=False, reason="ai_provider_missing", providers=())

        async def aclose(self):
            self.closed = True

    monkeypatch.setattr(runtime_service_module, "ArchiveMessagingRuntime", NotReadyRuntime)
    try:
        await service._start_messaging_if_enabled()
        assert service.messaging is None
        assert service.event_reminder_runtime is None
        assert len(instances) == 1
        assert instances[0].closed is True
    finally:
        await service.aclose()
