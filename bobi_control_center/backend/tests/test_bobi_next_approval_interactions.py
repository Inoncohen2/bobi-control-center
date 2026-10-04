from __future__ import annotations

import pytest

from app.bobi_next.approval_interactions import build_approval_interaction_handler
from app.bobi_next.authorization import (
    ApprovalStore,
    RequestProvenance,
    UserPolicy,
    approval_state_guard,
)
from app.bobi_next.interaction_dispatch import InteractionSelection
from app.bobi_next.models import ActionPlan
from app.bobi_next.pending_approval import PendingApprovalStore


class FakeHA:
    def __init__(self, state: str = "locked") -> None:
        self.state = state
        self.calls: list[tuple[str, str, dict]] = []

    async def get_state(self, entity_id: str):
        if entity_id != "lock.front":
            return None
        return {"state": self.state, "attributes": {}}

    async def call_service(self, domain: str, service: str, data: dict):
        self.calls.append((domain, service, dict(data)))
        if domain == "lock" and service == "unlock":
            self.state = "unlocked"


async def _policy(user_key: str) -> UserPolicy:
    return UserPolicy(user_key)


def _create_pending(
    store: PendingApprovalStore,
    *,
    approval_request_id: str,
    source_request_id: str,
    plan_request_id: str,
    now_ts: int,
    user_key: str = "u1",
) -> None:
    plan = ActionPlan(
        request_id=plan_request_id,
        device_id="dev-lock",
        entity_id="lock.front",
        domain="lock",
        action="unlock",
        capability="unlock",
        data={"entity_id": "lock.front"},
        expected={"state": "unlocked"},
    )
    guard = approval_state_guard(plan, {"state": "locked", "attributes": {}})
    store.create(
        approval_request_id=approval_request_id,
        source_request_id=source_request_id,
        user_key=user_key,
        plans=(plan,),
        provenance=RequestProvenance(
            explicit_target_ids=frozenset({"dev-lock"})
        ),
        state_guards=(guard,),
        summary="unlock front door",
        now_ts=now_ts,
    )


def _selection(
    *,
    approval_request_id: str,
    selected_keys: tuple[str, ...] = ("approve",),
    user_key: str = "u1",
) -> InteractionSelection:
    return InteractionSelection(
        dispatch_id=f"dispatch:{approval_request_id}",
        provider="waha:a",
        interaction_id=f"interaction:{approval_request_id}",
        poll_message_id=f"poll:{approval_request_id}",
        chat_id="1@c.us",
        user_key=user_key,
        context_key=f"approval:{approval_request_id}",
        selected_keys=selected_keys,
        source_event_id=f"vote:{approval_request_id}",
        provider_timestamp=101,
    )


@pytest.mark.asyncio
async def test_approval_interaction_executes_only_bound_request(tmp_path) -> None:
    pending = PendingApprovalStore(tmp_path / "pending.db")
    approvals = ApprovalStore(tmp_path / "approvals.db")
    ha = FakeHA()
    try:
        _create_pending(
            pending,
            approval_request_id="approval-a",
            source_request_id="source-a",
            plan_request_id="request-a",
            now_ts=100,
        )
        _create_pending(
            pending,
            approval_request_id="approval-b",
            source_request_id="source-b",
            plan_request_id="request-b",
            now_ts=101,
        )
        handler = build_approval_interaction_handler(
            pending_approvals=pending,
            approval_tokens=approvals,
            ha=ha,
            policy_for=_policy,
            clock=lambda: 102,
            verification_delay=0,
        )

        result = await handler(_selection(approval_request_id="approval-a"))

        assert result.outcome == "completed"
        assert result.response_text == "✅ אושר ובוצע."
        assert pending.get("approval-a").state == "completed"
        assert pending.get("approval-b").state == "pending"
        assert ha.calls == [("lock", "unlock", {"entity_id": "lock.front"})]
    finally:
        approvals.close()
        pending.close()


@pytest.mark.asyncio
async def test_approval_interaction_wrong_user_cannot_execute(tmp_path) -> None:
    pending = PendingApprovalStore(tmp_path / "pending.db")
    approvals = ApprovalStore(tmp_path / "approvals.db")
    ha = FakeHA()
    try:
        _create_pending(
            pending,
            approval_request_id="approval-a",
            source_request_id="source-a",
            plan_request_id="request-a",
            now_ts=100,
        )
        handler = build_approval_interaction_handler(
            pending_approvals=pending,
            approval_tokens=approvals,
            ha=ha,
            policy_for=_policy,
            clock=lambda: 101,
            verification_delay=0,
        )

        result = await handler(
            _selection(approval_request_id="approval-a", user_key="u2")
        )

        assert result.outcome == "approval_not_available"
        assert ha.calls == []
        assert pending.get("approval-a").state == "pending"
    finally:
        approvals.close()
        pending.close()


@pytest.mark.asyncio
async def test_approval_interaction_rejects_only_bound_request(tmp_path) -> None:
    pending = PendingApprovalStore(tmp_path / "pending.db")
    approvals = ApprovalStore(tmp_path / "approvals.db")
    ha = FakeHA()
    try:
        _create_pending(
            pending,
            approval_request_id="approval-a",
            source_request_id="source-a",
            plan_request_id="request-a",
            now_ts=100,
        )
        _create_pending(
            pending,
            approval_request_id="approval-b",
            source_request_id="source-b",
            plan_request_id="request-b",
            now_ts=101,
        )
        handler = build_approval_interaction_handler(
            pending_approvals=pending,
            approval_tokens=approvals,
            ha=ha,
            policy_for=_policy,
            clock=lambda: 102,
        )

        result = await handler(
            _selection(
                approval_request_id="approval-a",
                selected_keys=("reject",),
            )
        )

        assert result.outcome == "rejected"
        assert result.response_text == "בוטל. לא בוצעה פעולה."
        assert pending.get("approval-a").state == "rejected"
        assert pending.get("approval-b").state == "pending"
        assert ha.calls == []
    finally:
        approvals.close()
        pending.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "keys",
    [(), ("approve", "reject"), ("something-else",)],
)
async def test_approval_interaction_invalid_selection_fails_closed(
    tmp_path,
    keys: tuple[str, ...],
) -> None:
    pending = PendingApprovalStore(tmp_path / "pending.db")
    approvals = ApprovalStore(tmp_path / "approvals.db")
    ha = FakeHA()
    try:
        _create_pending(
            pending,
            approval_request_id="approval-a",
            source_request_id="source-a",
            plan_request_id="request-a",
            now_ts=100,
        )
        handler = build_approval_interaction_handler(
            pending_approvals=pending,
            approval_tokens=approvals,
            ha=ha,
            policy_for=_policy,
            clock=lambda: 101,
        )

        result = await handler(
            _selection(approval_request_id="approval-a", selected_keys=keys)
        )

        assert result.outcome == "invalid_approval_selection"
        assert ha.calls == []
        assert pending.get("approval-a").state == "pending"
    finally:
        approvals.close()
        pending.close()


@pytest.mark.asyncio
async def test_approval_interaction_keeps_state_fingerprint_guard(tmp_path) -> None:
    pending = PendingApprovalStore(tmp_path / "pending.db")
    approvals = ApprovalStore(tmp_path / "approvals.db")
    ha = FakeHA("unlocked")
    try:
        _create_pending(
            pending,
            approval_request_id="approval-a",
            source_request_id="source-a",
            plan_request_id="request-a",
            now_ts=100,
        )
        handler = build_approval_interaction_handler(
            pending_approvals=pending,
            approval_tokens=approvals,
            ha=ha,
            policy_for=_policy,
            clock=lambda: 101,
            verification_delay=0,
        )

        result = await handler(_selection(approval_request_id="approval-a"))

        assert result.outcome == "rejected"
        assert ha.calls == []
        assert pending.get("approval-a").state == "failed"
    finally:
        approvals.close()
        pending.close()
