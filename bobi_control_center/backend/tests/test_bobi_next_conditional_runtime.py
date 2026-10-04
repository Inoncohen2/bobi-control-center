from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.bobi_next.authorization import UserPolicy
from app.bobi_next.conditional import ConditionalRuleStore, StateChangeEvent
from app.bobi_next.conditional_runner import ConditionalRunResult
from app.bobi_next.conditional_runtime import ConditionalEventRuntime


class FakeStream:
    def __init__(self, event: StateChangeEvent) -> None:
        self.event = event
        self.called = False

    async def run_forever(self, handler, *, stop_event: asyncio.Event) -> None:
        self.called = True
        await handler(self.event)
        stop_event.set()


class FakeClient:
    async def call_service(self, domain: str, service: str, data: dict):
        return None

    async def get_state(self, entity_id: str):
        return {"entity_id": entity_id, "state": "off", "attributes": {}}


@pytest.mark.asyncio
async def test_conditional_runtime_routes_event_and_records_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = StateChangeEvent(
        event_id="evt-1",
        entity_id="binary_sensor.door",
        old_state="off",
        new_state="on",
        old_attributes={},
        new_attributes={},
        occurred_ts=123,
    )
    stream = FakeStream(event)
    store = ConditionalRuleStore(tmp_path / "rules.db")
    seen: list[StateChangeEvent] = []
    delivered: list[tuple[ConditionalRunResult, ...]] = []

    async def fake_runner(store_arg, client_arg, *, event, **kwargs):
        del store_arg, client_arg, kwargs
        seen.append(event)
        return (
            ConditionalRunResult(
                rule_id="rule-1",
                event_id=event.event_id,
                outcome="completed",
                reason="verified",
                executed_count=1,
                verified_count=1,
            ),
        )

    async def list_devices():
        return ()

    async def policy_for(user_key: str) -> UserPolicy:
        return UserPolicy(user_key=user_key)

    async def result_handler(results: tuple[ConditionalRunResult, ...]) -> None:
        delivered.append(results)

    monkeypatch.setattr(
        "app.bobi_next.conditional_runtime.run_conditional_event",
        fake_runner,
    )
    runtime = ConditionalEventRuntime(
        stream=stream,  # type: ignore[arg-type]
        store=store,
        client=FakeClient(),
        list_devices=list_devices,
        policy_for=policy_for,
        result_handler=result_handler,
    )
    stop = asyncio.Event()
    try:
        await runtime.run(stop_event=stop)
    finally:
        store.close()

    assert stream.called is True
    assert stop.is_set()
    assert seen == [event]
    assert delivered and delivered[0][0].outcome == "completed"
    assert runtime.stats.events_seen == 1
    assert runtime.stats.events_with_results == 1
    assert runtime.stats.rules_completed == 1
    assert runtime.stats.approvals_requested == 0
    assert runtime.stats.rules_failed == 0


@pytest.mark.asyncio
async def test_conditional_runtime_tracks_approval_and_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = StateChangeEvent(
        event_id="evt-2",
        entity_id="sensor.temperature",
        old_state="26",
        new_state="28",
        old_attributes={},
        new_attributes={},
        occurred_ts=456,
    )
    store = ConditionalRuleStore(tmp_path / "rules.db")

    async def fake_runner(*args, **kwargs):
        del args, kwargs
        return (
            ConditionalRunResult("r1", "evt-2", "approval_required", "approval_required"),
            ConditionalRunResult("r2", "evt-2", "failed", "blocked"),
        )

    async def list_devices():
        return ()

    async def policy_for(user_key: str) -> UserPolicy:
        return UserPolicy(user_key=user_key)

    monkeypatch.setattr(
        "app.bobi_next.conditional_runtime.run_conditional_event",
        fake_runner,
    )
    runtime = ConditionalEventRuntime(
        stream=FakeStream(event),  # type: ignore[arg-type]
        store=store,
        client=FakeClient(),
        list_devices=list_devices,
        policy_for=policy_for,
    )
    try:
        results = await runtime.handle_event(event)
    finally:
        store.close()

    assert len(results) == 2
    assert runtime.stats.approvals_requested == 1
    assert runtime.stats.rules_failed == 1
