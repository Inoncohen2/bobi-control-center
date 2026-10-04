from __future__ import annotations

import pytest

from app.bobi_next.authorization import UserPolicy
from app.bobi_next.models import DeviceRecord, EntityRecord
from app.bobi_next.scheduled_actions import ScheduledDeviceAction
from app.bobi_next.scheduled_runner import run_due_jobs
from app.bobi_next.scheduler import ScheduleStore


def _switch_device() -> DeviceRecord:
    entity = EntityRecord(
        entity_id="switch.room",
        domain="switch",
        state="on",
        capabilities=frozenset({"power"}),
    )
    return DeviceRecord(
        bobi_id="dev-switch",
        stable_key="ha-device:switch",
        name="Room switch",
        entities=(entity,),
        capabilities=entity.capabilities,
    )


def _climate_device(target: float) -> DeviceRecord:
    entity = EntityRecord(
        entity_id="climate.room",
        domain="climate",
        state="cool",
        attributes={
            "temperature": target,
            "min_temp": 16,
            "max_temp": 30,
            "target_temp_step": 0.5,
        },
        capabilities=frozenset({"power", "temperature"}),
        limits={"min_temp": 16, "max_temp": 30, "temp_step": 0.5},
    )
    return DeviceRecord(
        bobi_id="dev-climate",
        stable_key="ha-device:climate",
        name="Room AC",
        entities=(entity,),
        capabilities=entity.capabilities,
    )


def _switch_action(*, requires_confirmation: bool = False) -> ScheduledDeviceAction:
    return ScheduledDeviceAction(
        schema_version=2,
        source_text="turn it off later",
        device_ids=("dev-switch",),
        domain_hint="switch",
        capability="power",
        operation="off",
        requires_confirmation=requires_confirmation,
        provenance_source_kind="direct",
        provenance_same_text=True,
        provenance_explicit_device_ids=("dev-switch",),
        provenance_reference_only=False,
    )


def _context_switch_action(*, authorized: bool) -> ScheduledDeviceAction:
    return ScheduledDeviceAction(
        schema_version=2,
        source_text="turn it off later",
        device_ids=("dev-switch",),
        domain_hint="switch",
        capability="power",
        operation="off",
        provenance_source_kind="context",
        provenance_same_text=False,
        provenance_allowed_device_ids=("dev-switch",) if authorized else (),
        provenance_reference_only=True,
    )


class FakeHA:
    def __init__(self, state: dict, *, apply_mutations: bool = True):
        self.state = {
            "state": state["state"],
            "attributes": dict(state.get("attributes", {})),
        }
        self.apply_mutations = apply_mutations
        self.calls: list[tuple[str, str, dict]] = []

    async def get_state(self, entity_id):
        return {"state": self.state["state"], "attributes": dict(self.state["attributes"])}

    async def call_service(self, domain, service, data):
        self.calls.append((domain, service, dict(data)))
        if not self.apply_mutations:
            return
        if service == "turn_off":
            self.state["state"] = "off"
        elif service == "turn_on":
            self.state["state"] = "on"
        elif service == "set_temperature":
            self.state["attributes"]["temperature"] = data["temperature"]


async def _policy(user_key: str) -> UserPolicy:
    return UserPolicy(user_key)


async def _switch_devices():
    return (_switch_device(),)


@pytest.mark.asyncio
async def test_due_low_risk_job_executes_verifies_and_completes(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.db")
    try:
        store.create(
            job_id="job-1",
            user_key="u1",
            run_at_ts=100,
            payload=_switch_action().to_payload(),
            now_ts=1,
        )
        ha = FakeHA({"state": "on", "attributes": {}})

        results = await run_due_jobs(
            store,
            ha,
            list_devices=_switch_devices,
            policy_for=_policy,
            owner_token="worker-1",
            now_ts=100,
            verification_delay=0,
        )

        assert results[0].outcome == "completed"
        assert results[0].executed_count == 1
        assert results[0].verified_count == 1
        assert store.get("job-1").state == "completed"
        assert ha.calls == [("switch", "turn_off", {"entity_id": "switch.room"})]
    finally:
        store.close()


@pytest.mark.asyncio
async def test_context_schedule_preserves_authority_and_executes(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.db")
    try:
        store.create(
            job_id="job-context",
            user_key="u1",
            run_at_ts=100,
            payload=_context_switch_action(authorized=True).to_payload(),
            now_ts=1,
        )
        ha = FakeHA({"state": "on", "attributes": {}})

        results = await run_due_jobs(
            store,
            ha,
            list_devices=_switch_devices,
            policy_for=_policy,
            owner_token="worker-1",
            now_ts=100,
            verification_delay=0,
        )

        assert results[0].outcome == "completed"
        assert ha.calls == [("switch", "turn_off", {"entity_id": "switch.room"})]
    finally:
        store.close()


@pytest.mark.asyncio
async def test_context_schedule_without_saved_authority_is_held_for_approval(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.db")
    try:
        store.create(
            job_id="job-context-unsafe",
            user_key="u1",
            run_at_ts=100,
            payload=_context_switch_action(authorized=False).to_payload(),
            now_ts=1,
        )
        ha = FakeHA({"state": "on", "attributes": {}})

        results = await run_due_jobs(
            store,
            ha,
            list_devices=_switch_devices,
            policy_for=_policy,
            owner_token="worker-1",
            now_ts=100,
            verification_delay=0,
        )

        assert results[0].outcome == "awaiting_approval"
        assert results[0].reason == "context_target_not_authorized"
        assert store.get("job-context-unsafe").state == "awaiting_approval"
        assert ha.calls == []
    finally:
        store.close()


@pytest.mark.asyncio
async def test_schema_v1_job_cannot_gain_invented_direct_authority(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.db")
    try:
        legacy = ScheduledDeviceAction(
            schema_version=1,
            source_text="legacy later",
            device_ids=("dev-switch",),
            domain_hint="switch",
            capability="power",
            operation="off",
        )
        store.create(
            job_id="job-v1",
            user_key="u1",
            run_at_ts=100,
            payload=legacy.to_payload(),
            now_ts=1,
        )
        ha = FakeHA({"state": "on", "attributes": {}})

        results = await run_due_jobs(
            store,
            ha,
            list_devices=_switch_devices,
            policy_for=_policy,
            owner_token="worker-1",
            now_ts=100,
            verification_delay=0,
        )

        assert results[0].outcome == "awaiting_approval"
        assert results[0].reason == "reference_without_context_provenance"
        assert ha.calls == []
    finally:
        store.close()


@pytest.mark.asyncio
async def test_due_job_rebuilds_relative_temperature_from_live_snapshot(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.db")
    try:
        action = ScheduledDeviceAction(
            schema_version=2,
            source_text="raise half a degree later",
            device_ids=("dev-climate",),
            domain_hint="climate",
            capability="temperature",
            operation="set",
            delta=0.5,
            provenance_source_kind="direct",
            provenance_same_text=True,
            provenance_explicit_device_ids=("dev-climate",),
            provenance_reference_only=False,
        )
        store.create(
            job_id="job-temp",
            user_key="u1",
            run_at_ts=100,
            payload=action.to_payload(),
            now_ts=1,
        )
        ha = FakeHA({"state": "cool", "attributes": {"temperature": 25.0}})

        async def devices():
            return (_climate_device(25.0),)

        results = await run_due_jobs(
            store,
            ha,
            list_devices=devices,
            policy_for=_policy,
            owner_token="worker-1",
            now_ts=100,
            verification_delay=0,
        )

        assert results[0].outcome == "completed"
        assert ha.calls == [
            (
                "climate",
                "set_temperature",
                {"entity_id": "climate.room", "temperature": 25.5},
            )
        ]
    finally:
        store.close()


@pytest.mark.asyncio
async def test_confirmation_required_job_is_held_before_any_side_effect(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.db")
    try:
        store.create(
            job_id="job-sensitive",
            user_key="u1",
            run_at_ts=100,
            payload=_switch_action(requires_confirmation=True).to_payload(),
            now_ts=1,
        )
        ha = FakeHA({"state": "on", "attributes": {}})

        results = await run_due_jobs(
            store,
            ha,
            list_devices=_switch_devices,
            policy_for=_policy,
            owner_token="worker-1",
            now_ts=100,
            verification_delay=0,
        )

        assert results[0].outcome == "awaiting_approval"
        assert store.get("job-sensitive").state == "awaiting_approval"
        assert ha.calls == []
    finally:
        store.close()


@pytest.mark.asyncio
async def test_policy_denial_is_terminal_and_never_calls_home_assistant(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.db")
    try:
        store.create(
            job_id="job-denied",
            user_key="u1",
            run_at_ts=100,
            payload=_switch_action().to_payload(),
            now_ts=1,
        )
        ha = FakeHA({"state": "on", "attributes": {}})

        async def denied_policy(user_key: str):
            return UserPolicy(user_key, denied_capabilities=frozenset({"power"}))

        results = await run_due_jobs(
            store,
            ha,
            list_devices=_switch_devices,
            policy_for=denied_policy,
            owner_token="worker-1",
            now_ts=100,
            verification_delay=0,
        )

        assert results[0].outcome == "failed"
        assert results[0].reason == "capability_denied"
        assert store.get("job-denied").state == "failed"
        assert ha.calls == []
    finally:
        store.close()


@pytest.mark.asyncio
async def test_unverified_side_effect_is_not_automatically_retried(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.db")
    try:
        store.create(
            job_id="job-unverified",
            user_key="u1",
            run_at_ts=100,
            payload=_switch_action().to_payload(),
            now_ts=1,
        )
        ha = FakeHA({"state": "on", "attributes": {}}, apply_mutations=False)

        results = await run_due_jobs(
            store,
            ha,
            list_devices=_switch_devices,
            policy_for=_policy,
            owner_token="worker-1",
            now_ts=100,
            verification_attempts=1,
            verification_delay=0,
        )

        assert results[0].outcome == "failed"
        assert results[0].reason == "partial_execution:verification_failed"
        job = store.get("job-unverified")
        assert job.state == "failed"
        assert job.attempts == 1
        assert len(ha.calls) == 1
    finally:
        store.close()
