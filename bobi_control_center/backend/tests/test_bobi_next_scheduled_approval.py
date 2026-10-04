from __future__ import annotations

import pytest

from app.bobi_next.authorization import ApprovalStore, UserPolicy
from app.bobi_next.models import DeviceRecord, EntityRecord
from app.bobi_next.scheduled_actions import ScheduledDeviceAction
from app.bobi_next.scheduled_approval import approve_and_execute_scheduled_job
from app.bobi_next.scheduled_runner import run_due_jobs
from app.bobi_next.scheduler import ScheduleStore


def _device() -> DeviceRecord:
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


def _action() -> ScheduledDeviceAction:
    return ScheduledDeviceAction(
        schema_version=2,
        source_text="turn it off later",
        device_ids=("dev-switch",),
        domain_hint="switch",
        capability="power",
        operation="off",
        requires_confirmation=True,
        provenance_source_kind="direct",
        provenance_same_text=True,
        provenance_explicit_device_ids=("dev-switch",),
        provenance_reference_only=False,
    )


class FakeHA:
    def __init__(self, *, sequence: list[dict] | None = None):
        self.state = {"state": "on", "attributes": {}}
        self.sequence = list(sequence or [])
        self.calls: list[tuple[str, str, dict]] = []

    async def get_state(self, entity_id):
        if self.sequence:
            state = self.sequence.pop(0)
            self.state = {
                "state": state["state"],
                "attributes": dict(state.get("attributes", {})),
            }
        return {
            "state": self.state["state"],
            "attributes": dict(self.state["attributes"]),
        }

    async def call_service(self, domain, service, data):
        self.calls.append((domain, service, dict(data)))
        if service == "turn_off":
            self.state["state"] = "off"


async def _devices():
    return (_device(),)


async def _policy(user_key: str) -> UserPolicy:
    return UserPolicy(user_key)


async def _hold_job(store: ScheduleStore, ha: FakeHA, job_id: str = "job-approval"):
    store.create(
        job_id=job_id,
        user_key="u1",
        run_at_ts=100,
        payload=_action().to_payload(),
        now_ts=1,
    )
    result = await run_due_jobs(
        store,
        ha,
        list_devices=_devices,
        policy_for=_policy,
        owner_token="scheduler-worker",
        now_ts=100,
        verification_delay=0,
    )
    assert result[0].outcome == "awaiting_approval"
    assert store.get(job_id).state == "awaiting_approval"


@pytest.mark.asyncio
async def test_explicit_approval_executes_held_job_through_secure_path(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.db")
    approvals = ApprovalStore(tmp_path / "approvals.db")
    try:
        ha = FakeHA()
        await _hold_job(store, ha)

        result = await approve_and_execute_scheduled_job(
            store,
            approvals,
            ha,
            job_id="job-approval",
            user_key="u1",
            list_devices=_devices,
            policy_for=_policy,
            owner_token="approval-worker",
            now_ts=101,
            verification_delay=0,
        )

        assert result.outcome == "completed"
        assert result.executed_count == 1
        assert result.verified_count == 1
        assert store.get("job-approval").state == "completed"
        assert ha.calls == [("switch", "turn_off", {"entity_id": "switch.room"})]
    finally:
        approvals.close()
        store.close()


@pytest.mark.asyncio
async def test_wrong_user_cannot_claim_or_execute_held_job(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.db")
    approvals = ApprovalStore(tmp_path / "approvals.db")
    try:
        ha = FakeHA()
        await _hold_job(store, ha)

        result = await approve_and_execute_scheduled_job(
            store,
            approvals,
            ha,
            job_id="job-approval",
            user_key="u2",
            list_devices=_devices,
            policy_for=_policy,
            owner_token="approval-worker",
            now_ts=101,
            verification_delay=0,
        )

        assert result.outcome == "rejected"
        assert result.reason == "approval_wrong_user"
        assert store.get("job-approval").state == "awaiting_approval"
        assert ha.calls == []
    finally:
        approvals.close()
        store.close()


@pytest.mark.asyncio
async def test_state_change_during_approval_returns_job_to_approval_hold(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.db")
    approvals = ApprovalStore(tmp_path / "approvals.db")
    try:
        ha = FakeHA()
        await _hold_job(store, ha)
        ha.sequence = [
            {"state": "on", "attributes": {}},
            {"state": "off", "attributes": {}},
        ]

        result = await approve_and_execute_scheduled_job(
            store,
            approvals,
            ha,
            job_id="job-approval",
            user_key="u1",
            list_devices=_devices,
            policy_for=_policy,
            owner_token="approval-worker",
            now_ts=101,
            verification_delay=0,
        )

        assert result.outcome == "awaiting_approval"
        assert result.reason == "approval_state_changed"
        assert store.get("job-approval").state == "awaiting_approval"
        assert ha.calls == []
    finally:
        approvals.close()
        store.close()


@pytest.mark.asyncio
async def test_user_without_approval_permission_cannot_bypass_policy(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.db")
    approvals = ApprovalStore(tmp_path / "approvals.db")
    try:
        ha = FakeHA()
        await _hold_job(store, ha)

        async def cannot_approve(user_key: str):
            return UserPolicy(user_key, can_approve=False)

        result = await approve_and_execute_scheduled_job(
            store,
            approvals,
            ha,
            job_id="job-approval",
            user_key="u1",
            list_devices=_devices,
            policy_for=cannot_approve,
            owner_token="approval-worker",
            now_ts=101,
            verification_delay=0,
        )

        assert result.outcome == "rejected"
        assert result.reason == "user_cannot_approve"
        assert store.get("job-approval").state == "awaiting_approval"
        assert ha.calls == []
    finally:
        approvals.close()
        store.close()
