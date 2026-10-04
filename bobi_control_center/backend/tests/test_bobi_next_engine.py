from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.bobi_next.authorization import UserPolicy
from app.bobi_next.engine import EngineRequest, UnderstandingContext, process_request
from app.bobi_next.intent import SemanticIntent
from app.bobi_next.memory import BobiMemory
from app.bobi_next.models import DeviceRecord, EntityRecord
from app.bobi_next.pending_approval import PendingApprovalStore
from app.bobi_next.request_ledger import RequestLedger
from app.bobi_next.scheduler import ScheduleStore


class FakeHA:
    def __init__(self, states: dict[str, dict]):
        self.states = {
            entity_id: {
                "state": value["state"],
                "attributes": dict(value.get("attributes", {})),
            }
            for entity_id, value in states.items()
        }
        self.calls: list[tuple[str, str, dict]] = []

    async def get_state(self, entity_id):
        value = self.states.get(entity_id)
        if value is None:
            return None
        return {"state": value["state"], "attributes": dict(value["attributes"])}

    async def call_service(self, domain, service, data):
        self.calls.append((domain, service, dict(data)))
        entity_id = data["entity_id"]
        current = self.states[entity_id]
        if service == "turn_off":
            current["state"] = "off"
        elif service == "turn_on":
            current["state"] = "on"
        elif service == "set_temperature":
            current["attributes"]["temperature"] = data["temperature"]
        elif service == "unlock":
            current["state"] = "unlocked"
        elif service == "lock":
            current["state"] = "locked"


@dataclass
class StaticUnderstanding:
    intents: dict[str, SemanticIntent]

    def __post_init__(self):
        self.contexts: list[UnderstandingContext] = []

    async def understand(self, text: str, *, context: UnderstandingContext) -> SemanticIntent:
        self.contexts.append(context)
        return self.intents[text]


def _device(
    *,
    bobi_id: str,
    entity_id: str,
    domain: str,
    name: str,
    state: str,
    capabilities: set[str],
    attributes: dict | None = None,
    limits: dict | None = None,
    area_id: str = "",
    area_name: str = "",
) -> DeviceRecord:
    entity = EntityRecord(
        entity_id=entity_id,
        domain=domain,
        name=name,
        state=state,
        attributes=attributes or {},
        capabilities=frozenset(capabilities),
        limits=limits or {},
    )
    return DeviceRecord(
        bobi_id=bobi_id,
        stable_key=f"device:{bobi_id}",
        name=name,
        area_id=area_id,
        area_name=area_name,
        entities=(entity,),
        capabilities=entity.capabilities,
    )


def _switch() -> DeviceRecord:
    return _device(
        bobi_id="dev-switch",
        entity_id="switch.room",
        domain="switch",
        name="Room switch",
        state="on",
        capabilities={"power"},
        area_id="room",
        area_name="Room",
    )


def _climate(target: float = 25.0) -> DeviceRecord:
    return _device(
        bobi_id="dev-ac",
        entity_id="climate.bedroom",
        domain="climate",
        name="Bedroom AC",
        state="cool",
        capabilities={"power", "temperature"},
        attributes={
            "temperature": target,
            "min_temp": 16,
            "max_temp": 30,
            "target_temp_step": 0.5,
        },
        limits={"min_temp": 16, "max_temp": 30, "temp_step": 0.5},
        area_id="bedroom",
        area_name="Bedroom",
    )


def _lock() -> DeviceRecord:
    return _device(
        bobi_id="dev-lock",
        entity_id="lock.front",
        domain="lock",
        name="Front door",
        state="locked",
        capabilities={"lock", "unlock"},
    )


def _intent(
    text: str,
    *,
    domain: str,
    operation: str,
    target: str,
    value_kind: str = "none",
    value=None,
    delta: float | None = None,
    scheduled: bool = False,
    contextual: bool = False,
    reference_only: bool = False,
    negated: bool = False,
    schedule_payload: dict | None = None,
) -> SemanticIntent:
    return SemanticIntent(
        raw_text=text,
        family="device_control",
        domain=domain,
        operation=operation,
        target_text=target,
        value_kind=value_kind,
        value=value,
        delta=delta,
        scheduled=scheduled,
        contextual=contextual,
        reference_only=reference_only,
        negated=negated,
        confidence=0.99,
        schedule_payload=schedule_payload or {},
    )


async def _policy(user_key: str) -> UserPolicy:
    return UserPolicy(user_key)


class EngineStores:
    def __init__(self, tmp_path):
        self.path = tmp_path / "bobi.db"
        self.memory = BobiMemory(self.path)
        self.requests = RequestLedger(self.path)

    def close(self):
        self.requests.close()
        self.memory.close()


@pytest.mark.asyncio
async def test_immediate_device_command_executes_verifies_and_sets_context(tmp_path):
    stores = EngineStores(tmp_path)
    try:
        understanding = StaticUnderstanding(
            {
                "turn room off": _intent(
                    "turn room off",
                    domain="switch",
                    operation="off",
                    target="Room switch",
                )
            }
        )
        ha = FakeHA({"switch.room": {"state": "on", "attributes": {}}})

        async def devices():
            return (_switch(),)

        result = await process_request(
            EngineRequest("r1", "u1", "turn room off", "worker", message_id="m1", now_ts=100),
            understanding=understanding,
            list_devices=devices,
            policy_for=_policy,
            ha=ha,
            memory=stores.memory,
            requests=stores.requests,
            verification_delay=0,
        )
        assert result.outcome == "executed"
        assert result.executed_count == result.verified_count == 1
        assert ha.calls == [("switch", "turn_off", {"entity_id": "switch.room"})]
        assert stores.requests.get("r1").state == "completed"
        assert stores.memory.get_active_context("u1", now_ts=100)["bobi_device_id"] == "dev-switch"
    finally:
        stores.close()


@pytest.mark.asyncio
async def test_terminal_duplicate_request_never_executes_twice(tmp_path):
    stores = EngineStores(tmp_path)
    try:
        understanding = StaticUnderstanding(
            {"off": _intent("off", domain="switch", operation="off", target="Room switch")}
        )
        ha = FakeHA({"switch.room": {"state": "on", "attributes": {}}})

        async def devices():
            return (_switch(),)

        kwargs = {
            "understanding": understanding,
            "list_devices": devices,
            "policy_for": _policy,
            "ha": ha,
            "memory": stores.memory,
            "requests": stores.requests,
            "verification_delay": 0,
        }
        first = await process_request(
            EngineRequest("same", "u1", "off", "worker-a", now_ts=100), **kwargs
        )
        second = await process_request(
            EngineRequest("same", "u1", "off", "worker-b", now_ts=101), **kwargs
        )
        assert first.outcome == "executed"
        assert second.outcome == "duplicate"
        assert second.reason == "request_terminal"
        assert len(ha.calls) == 1
    finally:
        stores.close()


@pytest.mark.asyncio
async def test_half_degree_delta_uses_live_device_target(tmp_path):
    stores = EngineStores(tmp_path)
    try:
        understanding = StaticUnderstanding(
            {
                "raise half": _intent(
                    "raise half",
                    domain="climate",
                    operation="set",
                    target="Bedroom AC",
                    value_kind="delta_temperature",
                    delta=0.5,
                )
            }
        )
        ha = FakeHA(
            {"climate.bedroom": {"state": "cool", "attributes": {"temperature": 25.0}}}
        )

        async def devices():
            return (_climate(),)

        result = await process_request(
            EngineRequest("temp", "u1", "raise half", "worker", now_ts=100),
            understanding=understanding,
            list_devices=devices,
            policy_for=_policy,
            ha=ha,
            memory=stores.memory,
            requests=stores.requests,
            verification_delay=0,
        )
        assert result.outcome == "executed"
        assert ha.calls == [
            (
                "climate",
                "set_temperature",
                {"entity_id": "climate.bedroom", "temperature": 25.5},
            )
        ]
    finally:
        stores.close()


@pytest.mark.asyncio
async def test_followup_reference_uses_active_device_context(tmp_path):
    stores = EngineStores(tmp_path)
    try:
        understanding = StaticUnderstanding(
            {
                "turn room off": _intent(
                    "turn room off", domain="switch", operation="off", target="Room switch"
                ),
                "turn it on": _intent(
                    "turn it on",
                    domain="switch",
                    operation="on",
                    target="אותו",
                    contextual=True,
                    reference_only=True,
                ),
            }
        )
        ha = FakeHA({"switch.room": {"state": "on", "attributes": {}}})

        async def devices():
            return (_switch(),)

        kwargs = {
            "understanding": understanding,
            "list_devices": devices,
            "policy_for": _policy,
            "ha": ha,
            "memory": stores.memory,
            "requests": stores.requests,
            "verification_delay": 0,
        }
        await process_request(
            EngineRequest("r1", "u1", "turn room off", "worker-a", now_ts=100), **kwargs
        )
        second = await process_request(
            EngineRequest("r2", "u1", "turn it on", "worker-b", now_ts=101), **kwargs
        )
        assert second.outcome == "executed"
        assert second.resolution.resolution_kind == "context"
        assert ha.calls[-1] == ("switch", "turn_on", {"entity_id": "switch.room"})
        assert understanding.contexts[-1].active_context["bobi_device_id"] == "dev-switch"
    finally:
        stores.close()


@pytest.mark.asyncio
async def test_scheduled_command_persists_semantic_job_without_calling_ha(tmp_path):
    stores = EngineStores(tmp_path)
    schedules = ScheduleStore(tmp_path / "schedule.db")
    try:
        understanding = StaticUnderstanding(
            {
                "off later": _intent(
                    "off later",
                    domain="switch",
                    operation="off",
                    target="Room switch",
                    scheduled=True,
                    schedule_payload={"delay_seconds": 120},
                )
            }
        )
        ha = FakeHA({"switch.room": {"state": "on", "attributes": {}}})

        async def devices():
            return (_switch(),)

        result = await process_request(
            EngineRequest("sched", "u1", "off later", "worker", now_ts=100),
            understanding=understanding,
            list_devices=devices,
            policy_for=_policy,
            ha=ha,
            memory=stores.memory,
            requests=stores.requests,
            schedules=schedules,
        )
        job = schedules.get("req-sched")
        assert result.outcome == "scheduled"
        assert result.scheduled_job_id == "req-sched"
        assert job.run_at_ts == 220
        assert job.payload["device_ids"] == ["dev-switch"]
        assert ha.calls == []
    finally:
        schedules.close()
        stores.close()


@pytest.mark.asyncio
async def test_negated_mutation_is_ignored_before_discovery_or_execution(tmp_path):
    stores = EngineStores(tmp_path)
    try:
        understanding = StaticUnderstanding(
            {
                "do not turn it off": _intent(
                    "do not turn it off",
                    domain="switch",
                    operation="off",
                    target="Room switch",
                    negated=True,
                )
            }
        )
        ha = FakeHA({"switch.room": {"state": "on", "attributes": {}}})
        calls = 0

        async def devices():
            nonlocal calls
            calls += 1
            return (_switch(),)

        result = await process_request(
            EngineRequest("neg", "u1", "do not turn it off", "worker", now_ts=100),
            understanding=understanding,
            list_devices=devices,
            policy_for=_policy,
            ha=ha,
            memory=stores.memory,
            requests=stores.requests,
        )
        assert result.outcome == "ignored"
        assert result.reason == "source_negated"
        assert calls == 0
        assert ha.calls == []
    finally:
        stores.close()


@pytest.mark.asyncio
async def test_unresolved_target_returns_clarification_without_side_effect(tmp_path):
    stores = EngineStores(tmp_path)
    try:
        understanding = StaticUnderstanding(
            {
                "unknown off": _intent(
                    "unknown off",
                    domain="switch",
                    operation="off",
                    target="Unknown thing",
                )
            }
        )
        ha = FakeHA({"switch.room": {"state": "on", "attributes": {}}})

        async def devices():
            return (_switch(),)

        result = await process_request(
            EngineRequest("unknown", "u1", "unknown off", "worker", now_ts=100),
            understanding=understanding,
            list_devices=devices,
            policy_for=_policy,
            ha=ha,
            memory=stores.memory,
            requests=stores.requests,
        )
        assert result.outcome == "clarification"
        assert result.reason == "no_target_match"
        assert ha.calls == []
    finally:
        stores.close()


@pytest.mark.asyncio
async def test_critical_unlock_persists_restart_safe_approval_without_secret(tmp_path):
    stores = EngineStores(tmp_path)
    pending = PendingApprovalStore(tmp_path / "pending.db")
    try:
        understanding = StaticUnderstanding(
            {"unlock": _intent("unlock", domain="lock", operation="unlock", target="Front door")}
        )
        ha = FakeHA({"lock.front": {"state": "locked", "attributes": {}}})

        async def devices():
            return (_lock(),)

        result = await process_request(
            EngineRequest("unlock", "u1", "unlock", "worker", now_ts=100),
            understanding=understanding,
            list_devices=devices,
            policy_for=_policy,
            ha=ha,
            memory=stores.memory,
            requests=stores.requests,
            pending_approvals=pending,
        )
        saved = pending.get("approve-unlock")
        assert result.outcome == "approval_required"
        assert result.approval_request_id == "approve-unlock"
        assert saved is not None
        assert saved.state == "pending"
        assert saved.user_key == "u1"
        assert saved.plans[0].domain == "lock"
        assert saved.plans[0].action == "unlock"
        assert saved.state_guards[0]["state"] == "locked"
        assert ha.calls == []
    finally:
        pending.close()
        stores.close()


@pytest.mark.asyncio
async def test_shadow_mode_builds_and_validates_plan_without_mutation(tmp_path):
    stores = EngineStores(tmp_path)
    try:
        understanding = StaticUnderstanding(
            {"off": _intent("off", domain="switch", operation="off", target="Room switch")}
        )
        ha = FakeHA({"switch.room": {"state": "on", "attributes": {}}})

        async def devices():
            return (_switch(),)

        result = await process_request(
            EngineRequest("shadow", "u1", "off", "worker", now_ts=100),
            understanding=understanding,
            list_devices=devices,
            policy_for=_policy,
            ha=ha,
            memory=stores.memory,
            requests=stores.requests,
            dry_run=True,
            verification_delay=0,
        )
        assert result.outcome == "shadow"
        assert result.plans[0].action == "turn_off"
        assert ha.calls == []
    finally:
        stores.close()
