from __future__ import annotations

import pytest

from app.bobi_next.approval_continuation import (
    approve_latest_pending,
    reject_latest_pending,
)
from app.bobi_next.authorization import (
    ApprovalStore,
    RequestProvenance,
    UserPolicy,
    approval_state_guard,
)
from app.bobi_next.models import ActionPlan
from app.bobi_next.pending_approval import PendingApprovalStore


def _unlock_plan(request_id: str = "req-lock") -> ActionPlan:
    return ActionPlan(
        request_id=request_id,
        device_id="dev-lock",
        entity_id="lock.front",
        domain="lock",
        action="unlock",
        capability="unlock",
        data={"entity_id": "lock.front"},
        expected={"state": "unlocked"},
    )


def _provenance() -> RequestProvenance:
    return RequestProvenance(explicit_target_ids=frozenset({"dev-lock"}))


class FakeHA:
    def __init__(self, state: str = "locked"):
        self.state = state
        self.calls: list[tuple[str, str, dict]] = []

    async def get_state(self, entity_id):
        if entity_id != "lock.front":
            return None
        return {"state": self.state, "attributes": {}}

    async def call_service(self, domain, service, data):
        self.calls.append((domain, service, dict(data)))
        if domain == "lock" and service == "unlock":
            self.state = "unlocked"


async def _policy(user_key: str) -> UserPolicy:
    return UserPolicy(user_key)


def _create_pending(store: PendingApprovalStore, *, now_ts: int = 100):
    plan = _unlock_plan()
    guard = approval_state_guard(plan, {"state": "locked", "attributes": {}})
    return store.create(
        approval_request_id="approve-lock",
        source_request_id="source-lock",
        user_key="u1",
        plans=(plan,),
        provenance=_provenance(),
        state_guards=(guard,),
        summary="unlock front door",
        now_ts=now_ts,
    )


def test_pending_approval_round_trips_without_bearer_token(tmp_path):
    path = tmp_path / "pending.db"
    store = PendingApprovalStore(path)
    try:
        created = _create_pending(store)
        assert created.state == "pending"
        assert created.user_key == "u1"
        assert created.plans[0].action == "unlock"
        assert created.state_guards[0]["state"] == "locked"
        row = store._db.execute(
            "SELECT plans_json, provenance_json, state_guards_json FROM pending_approval_requests"
        ).fetchone()
        persisted = " ".join(str(value) for value in row)
        assert "token" not in persisted.lower()
    finally:
        store.close()


def test_pending_approval_survives_store_restart_and_reclaims_expired_lease(tmp_path):
    path = tmp_path / "pending.db"
    first = PendingApprovalStore(path)
    try:
        _create_pending(first, now_ts=100)
        claimed = first.claim_latest(
            user_key="u1",
            owner_token="dead-worker",
            now_ts=101,
            lease_seconds=10,
        )
        assert claimed is not None
        assert claimed.state == "running"
    finally:
        first.close()

    reopened = PendingApprovalStore(path)
    try:
        recovered = reopened.claim_latest(
            user_key="u1",
            owner_token="new-worker",
            now_ts=112,
            lease_seconds=20,
        )
        assert recovered is not None
        assert recovered.owner_token == "new-worker"
        assert recovered.attempts == 2
    finally:
        reopened.close()


@pytest.mark.asyncio
async def test_restart_safe_yes_executes_exact_pending_plan_once(tmp_path):
    pending_path = tmp_path / "pending.db"
    first = PendingApprovalStore(pending_path)
    try:
        _create_pending(first)
    finally:
        first.close()

    pending = PendingApprovalStore(pending_path)
    approvals = ApprovalStore(tmp_path / "ephemeral-approvals.db")
    ha = FakeHA("locked")
    try:
        result = await approve_latest_pending(
            pending,
            approvals,
            ha,
            user_key="u1",
            policy_for=_policy,
            owner_token="worker-a",
            now_ts=101,
            verification_delay=0,
        )
        assert result.outcome == "completed"
        assert result.executed_count == 1
        assert result.verified_count == 1
        assert ha.calls == [("lock", "unlock", {"entity_id": "lock.front"})]
        assert pending.get("approve-lock").state == "completed"

        duplicate = await approve_latest_pending(
            pending,
            approvals,
            ha,
            user_key="u1",
            policy_for=_policy,
            owner_token="worker-b",
            now_ts=102,
            verification_delay=0,
        )
        assert duplicate.outcome == "no_pending"
        assert len(ha.calls) == 1
    finally:
        approvals.close()
        pending.close()


@pytest.mark.asyncio
async def test_yes_is_rejected_if_device_state_changed_since_prompt(tmp_path):
    pending = PendingApprovalStore(tmp_path / "pending.db")
    approvals = ApprovalStore(tmp_path / "ephemeral-approvals.db")
    try:
        _create_pending(pending)
        ha = FakeHA("unlocked")
        result = await approve_latest_pending(
            pending,
            approvals,
            ha,
            user_key="u1",
            policy_for=_policy,
            owner_token="worker",
            now_ts=101,
            verification_delay=0,
        )
        assert result.outcome == "rejected"
        assert result.reason == "approval_state_changed"
        assert ha.calls == []
        assert pending.get("approve-lock").state == "failed"
    finally:
        approvals.close()
        pending.close()


def test_no_rejects_latest_pending_without_side_effect(tmp_path):
    pending = PendingApprovalStore(tmp_path / "pending.db")
    try:
        _create_pending(pending)
        result = reject_latest_pending(
            pending,
            user_key="u1",
            owner_token="worker",
            now_ts=101,
        )
        assert result.outcome == "rejected"
        assert result.reason == "rejected_by_user"
        assert pending.get("approve-lock").state == "rejected"
        again = reject_latest_pending(
            pending,
            user_key="u1",
            owner_token="worker-2",
            now_ts=102,
        )
        assert again.outcome == "no_pending"
    finally:
        pending.close()


def test_other_user_cannot_claim_someone_elses_pending_approval(tmp_path):
    pending = PendingApprovalStore(tmp_path / "pending.db")
    try:
        _create_pending(pending)
        result = pending.claim_latest(
            user_key="u2",
            owner_token="worker",
            now_ts=101,
        )
        assert result is None
        assert pending.get("approve-lock").state == "pending"
    finally:
        pending.close()
