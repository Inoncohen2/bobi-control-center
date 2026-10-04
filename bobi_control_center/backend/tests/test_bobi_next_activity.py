from __future__ import annotations

import pytest

from app.bobi_next.activity import ActivityLedger, undo_latest
from app.bobi_next.authorization import RiskLevel, UserPolicy
from app.bobi_next.executor import ExecutionResult
from app.bobi_next.models import ActionPlan
from app.bobi_next.pending_approval import PendingApprovalStore


class FakeHA:
    def __init__(self, states: dict[str, dict]):
        self.states = states
        self.calls: list[tuple[str, str, dict]] = []

    async def get_state(self, entity_id: str):
        value = self.states.get(entity_id)
        if value is None:
            return None
        return {
            "state": value["state"],
            "attributes": dict(value.get("attributes") or {}),
        }

    async def call_service(self, domain: str, service: str, data: dict):
        self.calls.append((domain, service, dict(data)))
        entity_id = data["entity_id"]
        target = self.states[entity_id]
        if service == "turn_on":
            target["state"] = "on"
            if "brightness_pct" in data:
                target.setdefault("attributes", {})["brightness"] = round(
                    float(data["brightness_pct"]) / 100.0 * 255.0
                )
        elif service == "turn_off":
            target["state"] = "off"
        elif service == "set_temperature":
            target.setdefault("attributes", {})["temperature"] = data["temperature"]
        elif service == "unlock":
            target["state"] = "unlocked"
        elif service == "lock":
            target["state"] = "locked"


def _plan(
    *,
    request_id: str,
    entity_id: str,
    domain: str,
    action: str,
    capability: str,
    data: dict,
    expected: dict,
) -> ActionPlan:
    return ActionPlan(
        request_id=request_id,
        device_id=f"device:{entity_id}",
        entity_id=entity_id,
        domain=domain,
        action=action,
        capability=capability,
        data=data,
        expected=expected,
    )


def test_verified_switch_action_records_inverse_and_is_deduplicated(tmp_path):
    ledger = ActivityLedger(tmp_path / "activity.db")
    plan = _plan(
        request_id="r1",
        entity_id="switch.room",
        domain="switch",
        action="turn_off",
        capability="power",
        data={"entity_id": "switch.room"},
        expected={"state": "off"},
    )
    result = ExecutionResult(
        True,
        True,
        "verified",
        plan,
        before={"state": "on", "attributes": {}},
        after={"state": "off", "attributes": {}},
    )
    try:
        first = ledger.record_verified(user_key="u1", execution=result, created_ts=100)
        second = ledger.record_verified(user_key="u1", execution=result, created_ts=101)
        assert first is not None
        assert second is not None
        assert first.activity_id == second.activity_id
        assert first.inverse_plan is not None
        assert first.inverse_plan.action == "turn_on"
        assert first.inverse_plan.expected == {"state": "on"}
    finally:
        ledger.close()


@pytest.mark.asyncio
async def test_undo_restores_switch_only_if_state_still_matches_after_snapshot(tmp_path):
    ledger = ActivityLedger(tmp_path / "activity.db")
    plan = _plan(
        request_id="r1",
        entity_id="switch.room",
        domain="switch",
        action="turn_off",
        capability="power",
        data={"entity_id": "switch.room"},
        expected={"state": "off"},
    )
    execution = ExecutionResult(
        True,
        True,
        "verified",
        plan,
        before={"state": "on", "attributes": {}},
        after={"state": "off", "attributes": {}},
    )
    ledger.record_verified(user_key="u1", execution=execution, created_ts=100)
    ha = FakeHA({"switch.room": {"state": "off", "attributes": {}}})
    try:
        result = await undo_latest(
            ledger,
            ha,
            user_key="u1",
            policy=UserPolicy("u1"),
            undo_request_id="undo-message-1",
            now_ts=110,
            verification_delay=0,
        )
        assert result.outcome == "completed"
        assert ha.calls == [("switch", "turn_on", {"entity_id": "switch.room"})]
        assert ledger.latest_undoable("u1") is None
    finally:
        ledger.close()


@pytest.mark.asyncio
async def test_undo_fails_closed_if_user_or_automation_changed_device_afterward(tmp_path):
    ledger = ActivityLedger(tmp_path / "activity.db")
    plan = _plan(
        request_id="r1",
        entity_id="climate.room",
        domain="climate",
        action="set_temperature",
        capability="temperature",
        data={"entity_id": "climate.room", "temperature": 24.0},
        expected={"attribute": "temperature", "value": 24.0, "tolerance": 0.25},
    )
    execution = ExecutionResult(
        True,
        True,
        "verified",
        plan,
        before={"state": "cool", "attributes": {"temperature": 23.0}},
        after={"state": "cool", "attributes": {"temperature": 24.0}},
    )
    ledger.record_verified(user_key="u1", execution=execution, created_ts=100)
    ha = FakeHA({"climate.room": {"state": "cool", "attributes": {"temperature": 22.0}}})
    try:
        result = await undo_latest(
            ledger,
            ha,
            user_key="u1",
            policy=UserPolicy("u1"),
            undo_request_id="undo-message-1",
            now_ts=110,
            verification_delay=0,
        )
        assert result.outcome == "blocked"
        assert result.reason == "state_changed_since_action"
        assert ha.calls == []
    finally:
        ledger.close()


@pytest.mark.asyncio
async def test_sensitive_inverse_uses_restart_safe_pending_approval(tmp_path):
    ledger = ActivityLedger(tmp_path / "activity.db")
    pending = PendingApprovalStore(tmp_path / "pending.db")
    plan = _plan(
        request_id="r-lock",
        entity_id="lock.front",
        domain="lock",
        action="lock",
        capability="lock",
        data={"entity_id": "lock.front"},
        expected={"state": "locked"},
    )
    execution = ExecutionResult(
        True,
        True,
        "verified",
        plan,
        before={"state": "unlocked", "attributes": {}},
        after={"state": "locked", "attributes": {}},
    )
    record = ledger.record_verified(user_key="u1", execution=execution, created_ts=100)
    assert record is not None
    ha = FakeHA({"lock.front": {"state": "locked", "attributes": {}}})
    policy = UserPolicy("u1", max_without_approval=RiskLevel.MEDIUM, can_approve=True)
    try:
        result = await undo_latest(
            ledger,
            ha,
            user_key="u1",
            policy=policy,
            undo_request_id="undo-lock-1",
            pending_approvals=pending,
            now_ts=110,
            verification_delay=0,
        )
        assert result.outcome == "approval_required"
        assert ha.calls == []
        queued = pending.get(result.approval_request_id)
        assert queued is not None
        assert queued.plans[0].action == "unlock"
        assert queued.plans[0].entity_id == "lock.front"
    finally:
        pending.close()
        ledger.close()


def test_non_reversible_button_is_audited_but_not_offered_as_undo(tmp_path):
    ledger = ActivityLedger(tmp_path / "activity.db")
    plan = _plan(
        request_id="r-button",
        entity_id="button.scene",
        domain="button",
        action="press",
        capability="press",
        data={"entity_id": "button.scene"},
        expected={},
    )
    execution = ExecutionResult(
        True,
        True,
        "verified",
        plan,
        before={"state": "2026-10-04T00:00:00", "attributes": {}},
        after={"state": "2026-10-04T00:00:01", "attributes": {}},
    )
    try:
        record = ledger.record_verified(user_key="u1", execution=execution, created_ts=100)
        assert record is not None
        assert record.inverse_plan is None
        assert ledger.latest_undoable("u1") is None
    finally:
        ledger.close()
