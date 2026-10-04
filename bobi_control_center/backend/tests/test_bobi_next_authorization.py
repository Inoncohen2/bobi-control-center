from __future__ import annotations

import pytest

from app.bobi_next.authorization import (
    ApprovalStore,
    RequestProvenance,
    RiskLevel,
    UserPolicy,
    approval_state_guard,
    authorize_plan,
)
from app.bobi_next.models import ActionPlan
from app.bobi_next.secure_execution import execute_authorized_plan


def make_plan(
    *,
    domain: str = "switch",
    action: str = "turn_on",
    capability: str = "power",
    entity_id: str = "switch.room",
    device_id: str = "dev_room",
    requires_confirmation: bool = False,
) -> ActionPlan:
    expected = {"state": "on"}
    if domain == "lock" and action == "unlock":
        expected = {"state": "unlocked"}
    return ActionPlan(
        request_id="req-1",
        device_id=device_id,
        entity_id=entity_id,
        domain=domain,
        action=action,
        capability=capability,
        data={"entity_id": entity_id},
        expected=expected,
        requires_confirmation=requires_confirmation,
    )


def test_low_risk_direct_device_action_is_allowed_without_approval():
    plan = make_plan()
    decision = authorize_plan(
        plan,
        policy=UserPolicy("u1"),
        provenance=RequestProvenance(explicit_target_ids=frozenset({"switch.room"})),
    )
    assert decision.allowed is True
    assert decision.requires_approval is False
    assert decision.risk is RiskLevel.LOW


def test_policy_denial_cannot_be_overridden_by_approval():
    plan = make_plan(capability="power")
    policy = UserPolicy("u1", denied_capabilities=frozenset({"power"}))
    decision = authorize_plan(
        plan,
        policy=policy,
        provenance=RequestProvenance(),
        approval_authorized=True,
    )
    assert decision.allowed is False
    assert decision.reason == "capability_denied"


def test_target_rewrite_requires_explicit_approval():
    plan = make_plan(entity_id="switch.other", device_id="dev_other")
    provenance = RequestProvenance(
        same_text=False,
        explicit_target_ids=frozenset({"switch.room"}),
    )
    initial = authorize_plan(plan, policy=UserPolicy("u1"), provenance=provenance)
    approved = authorize_plan(
        plan,
        policy=UserPolicy("u1"),
        provenance=provenance,
        approval_authorized=True,
    )
    assert initial.allowed is False
    assert initial.requires_approval is True
    assert initial.reason == "explicit_target_mismatch"
    assert approved.allowed is True


def test_negated_source_is_a_hard_veto_even_with_approval():
    plan = make_plan()
    decision = authorize_plan(
        plan,
        policy=UserPolicy("u1"),
        provenance=RequestProvenance(negated=True),
        approval_authorized=True,
    )
    assert decision.allowed is False
    assert decision.reason == "source_negated"


def test_unlock_is_critical_and_requires_approval():
    plan = make_plan(
        domain="lock",
        action="unlock",
        capability="lock",
        entity_id="lock.front",
        device_id="dev_front",
    )
    decision = authorize_plan(
        plan,
        policy=UserPolicy("u1"),
        provenance=RequestProvenance(explicit_target_ids=frozenset({"lock.front"})),
    )
    assert decision.risk is RiskLevel.CRITICAL
    assert decision.requires_approval is True
    assert decision.allowed is False


def test_approval_is_single_use_and_bound_to_plan_user_and_state(tmp_path):
    store = ApprovalStore(tmp_path / "approvals.db")
    try:
        plan = make_plan(
            domain="lock",
            action="unlock",
            capability="lock",
            entity_id="lock.front",
            device_id="dev_front",
        )
        snapshot = {"state": "locked", "attributes": {}}
        guard = approval_state_guard(plan, snapshot)
        grant = store.issue(user_key="u1", plan=plan, state_guard=guard, now_ts=1000)

        wrong_user = store.consume(
            token=grant.token,
            user_key="u2",
            plan=plan,
            state_guard=guard,
            now_ts=1001,
        )
        assert wrong_user.valid is False
        assert wrong_user.reason == "approval_wrong_user"

        valid = store.consume(
            token=grant.token,
            user_key="u1",
            plan=plan,
            state_guard=guard,
            now_ts=1001,
        )
        assert valid.valid is True

        reused = store.consume(
            token=grant.token,
            user_key="u1",
            plan=plan,
            state_guard=guard,
            now_ts=1002,
        )
        assert reused.valid is False
        assert reused.reason == "approval_already_used"
    finally:
        store.close()


def test_approval_rejects_changed_plan_without_consuming_token(tmp_path):
    store = ApprovalStore(tmp_path / "approvals.db")
    try:
        plan = make_plan()
        guard = approval_state_guard(plan, {"state": "off", "attributes": {}})
        grant = store.issue(user_key="u1", plan=plan, state_guard=guard, now_ts=1000)
        changed = make_plan(action="turn_off")
        rejected = store.consume(
            token=grant.token,
            user_key="u1",
            plan=changed,
            state_guard=guard,
            now_ts=1001,
        )
        assert rejected.valid is False
        assert rejected.reason == "approval_plan_changed"

        original = store.consume(
            token=grant.token,
            user_key="u1",
            plan=plan,
            state_guard=guard,
            now_ts=1001,
        )
        assert original.valid is True
    finally:
        store.close()


class SequenceHA:
    def __init__(self, states):
        self.states = list(states)
        self.calls = []

    async def get_state(self, entity_id):
        if not self.states:
            raise AssertionError("unexpected HA state read")
        return self.states.pop(0)

    async def call_service(self, domain, service, data):
        self.calls.append((domain, service, data))


@pytest.mark.asyncio
async def test_secure_executor_requires_approval_before_critical_side_effect(tmp_path):
    store = ApprovalStore(tmp_path / "approvals.db")
    try:
        plan = make_plan(
            domain="lock",
            action="unlock",
            capability="lock",
            entity_id="lock.front",
            device_id="dev_front",
        )
        ha = SequenceHA([])
        result = await execute_authorized_plan(
            plan,
            ha,
            user_key="u1",
            policy=UserPolicy("u1"),
            provenance=RequestProvenance(explicit_target_ids=frozenset({"lock.front"})),
            approval_store=store,
            verification_delay=0,
        )
        assert result.executed is False
        assert result.reason == "approval_required"
        assert ha.calls == []
    finally:
        store.close()


@pytest.mark.asyncio
async def test_secure_executor_consumes_valid_approval_then_verifies(tmp_path):
    store = ApprovalStore(tmp_path / "approvals.db")
    try:
        plan = make_plan(
            domain="lock",
            action="unlock",
            capability="lock",
            entity_id="lock.front",
            device_id="dev_front",
        )
        locked = {"state": "locked", "attributes": {}}
        grant = store.issue(
            user_key="u1",
            plan=plan,
            state_guard=approval_state_guard(plan, locked),
        )
        ha = SequenceHA([locked, locked, {"state": "unlocked", "attributes": {}}])
        result = await execute_authorized_plan(
            plan,
            ha,
            user_key="u1",
            policy=UserPolicy("u1"),
            provenance=RequestProvenance(explicit_target_ids=frozenset({"lock.front"})),
            approval_store=store,
            approval_token=grant.token,
            verification_delay=0,
        )
        assert result.executed is True
        assert result.verified is True
        assert ha.calls == [("lock", "unlock", {"entity_id": "lock.front"})]
    finally:
        store.close()


@pytest.mark.asyncio
async def test_secure_executor_blocks_if_state_changes_after_approval_consumption(tmp_path):
    store = ApprovalStore(tmp_path / "approvals.db")
    try:
        plan = make_plan(
            domain="lock",
            action="unlock",
            capability="lock",
            entity_id="lock.front",
            device_id="dev_front",
        )
        locked = {"state": "locked", "attributes": {}}
        grant = store.issue(
            user_key="u1",
            plan=plan,
            state_guard=approval_state_guard(plan, locked),
        )
        ha = SequenceHA([locked, {"state": "jammed", "attributes": {}}])
        result = await execute_authorized_plan(
            plan,
            ha,
            user_key="u1",
            policy=UserPolicy("u1"),
            provenance=RequestProvenance(explicit_target_ids=frozenset({"lock.front"})),
            approval_store=store,
            approval_token=grant.token,
            verification_delay=0,
        )
        assert result.executed is False
        assert result.reason == "precondition_changed"
        assert ha.calls == []
    finally:
        store.close()


@pytest.mark.asyncio
async def test_secure_executor_rejects_policy_for_different_authenticated_user():
    plan = make_plan()
    ha = SequenceHA([])
    result = await execute_authorized_plan(
        plan,
        ha,
        user_key="u2",
        policy=UserPolicy("u1"),
        provenance=RequestProvenance(),
        verification_delay=0,
    )
    assert result.executed is False
    assert result.reason == "policy_user_mismatch"
    assert ha.calls == []
