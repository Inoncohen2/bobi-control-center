from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.bobi_next.activity import ActivityLedger
from app.bobi_next.activity_runtime import (
    ActivityRecordingHAClient,
    UndoRequestStore,
    undo_once,
)
from app.bobi_next.authorization import ApprovalStore, RiskLevel, UserPolicy
from app.bobi_next.conversation_handler import build_conversation_handler
from app.bobi_next.executor import ExecutionResult, execute_plan
from app.bobi_next.intent import SemanticIntent
from app.bobi_next.memory import BobiMemory
from app.bobi_next.messaging import InboundMessage
from app.bobi_next.models import ActionPlan
from app.bobi_next.pending_approval import PendingApprovalStore
from app.bobi_next.request_ledger import RequestLedger


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
        target = self.states[data["entity_id"]]
        if service == "turn_on":
            target["state"] = "on"
        elif service == "turn_off":
            target["state"] = "off"
        elif service == "lock":
            target["state"] = "locked"
        elif service == "unlock":
            target["state"] = "unlocked"


def _plan(
    request_id: str,
    *,
    entity_id: str = "switch.room",
    domain: str = "switch",
    action: str = "turn_off",
    capability: str = "power",
    expected: dict | None = None,
) -> ActionPlan:
    return ActionPlan(
        request_id=request_id,
        device_id=f"device:{entity_id}",
        entity_id=entity_id,
        domain=domain,
        action=action,
        capability=capability,
        data={"entity_id": entity_id},
        expected=expected or {"state": "off"},
    )


def _message(message_id: str, text: str) -> InboundMessage:
    return InboundMessage(
        row_id=1,
        provider="waha-main",
        message_id=message_id,
        chat_id="chat-1",
        user_key="u1",
        text=text,
        kind="text",
        received_ts=100,
        state="running",
    )


@dataclass
class NeverUnderstanding:
    calls: int = 0

    async def understand(self, text, *, context):
        del text, context
        self.calls += 1
        return SemanticIntent(
            raw_text="unused",
            family="device_control",
            domain="switch",
            operation="off",
            target_text="unused",
            confidence=0.99,
        )


async def _devices():
    return ()


async def _policy(user_key: str) -> UserPolicy:
    return UserPolicy(user_key)


@pytest.mark.asyncio
async def test_verified_executor_records_activity_for_request_owner(tmp_path):
    requests = RequestLedger(tmp_path / "requests.db")
    activity = ActivityLedger(tmp_path / "activity.db")
    raw = FakeHA({"switch.room": {"state": "on", "attributes": {}}})
    client = ActivityRecordingHAClient(raw, activity=activity, requests=requests)
    requests.claim(
        request_id="waha:m1",
        user_key="u1",
        input_text="turn it off",
        owner_token="owner",
        now_ts=100,
    )
    try:
        result = await execute_plan(
            _plan("waha:m1"),
            client,
            verification_delay=0,
        )
        assert result.verified is True
        recorded = activity.latest_undoable("u1")
        assert recorded is not None
        assert recorded.request_id == "waha:m1"
        assert recorded.inverse_plan is not None
        assert recorded.inverse_plan.action == "turn_on"
    finally:
        activity.close()
        requests.close()


@pytest.mark.asyncio
async def test_same_undo_request_cannot_undo_two_actions_after_crash_retry(tmp_path):
    activity = ActivityLedger(tmp_path / "activity.db")
    undo_requests = UndoRequestStore(tmp_path / "undo.db")
    ha = FakeHA({"switch.room": {"state": "off", "attributes": {}}})
    execution = ExecutionResult(
        True,
        True,
        "verified",
        _plan("r1"),
        before={"state": "on", "attributes": {}},
        after={"state": "off", "attributes": {}},
    )
    activity.record_verified(user_key="u1", execution=execution, created_ts=100)
    try:
        first = await undo_once(
            undo_requests,
            activity,
            ha,
            request_id="undo:waha:m1",
            user_key="u1",
            policy=UserPolicy("u1"),
            pending_approvals=None,
            now_ts=110,
            verification_delay=0,
        )
        assert first.outcome == "completed"
        assert len(ha.calls) == 1

        second = await undo_once(
            undo_requests,
            activity,
            ha,
            request_id="undo:waha:m1",
            user_key="u1",
            policy=UserPolicy("u1"),
            pending_approvals=None,
            now_ts=111,
            verification_delay=0,
        )
        assert second == first
        assert len(ha.calls) == 1
    finally:
        undo_requests.close()
        activity.close()


@pytest.mark.asyncio
async def test_conversation_undo_bypasses_ai_and_restores_last_verified_action(tmp_path):
    memory = BobiMemory(tmp_path / "memory.db")
    requests = RequestLedger(tmp_path / "requests.db")
    pending = PendingApprovalStore(tmp_path / "pending.db")
    tokens = ApprovalStore(tmp_path / "tokens.db")
    activity = ActivityLedger(tmp_path / "activity.db")
    undo_requests = UndoRequestStore(tmp_path / "undo.db")
    ha = FakeHA({"switch.room": {"state": "off", "attributes": {}}})
    activity.record_verified(
        user_key="u1",
        execution=ExecutionResult(
            True,
            True,
            "verified",
            _plan("previous-request"),
            before={"state": "on", "attributes": {}},
            after={"state": "off", "attributes": {}},
        ),
        created_ts=90,
    )
    understanding = NeverUnderstanding()
    handler = build_conversation_handler(
        understanding=understanding,
        list_devices=_devices,
        policy_for=_policy,
        ha=ha,
        memory=memory,
        requests=requests,
        pending_approvals=pending,
        approval_tokens=tokens,
        activity=activity,
        undo_requests=undo_requests,
        clock=lambda: 100,
        verification_delay=0,
    )
    try:
        response = await handler(_message("m1", "בטל את הפעולה האחרונה"))
        assert response.text == "✅ ביטלתי את הפעולה האחרונה."
        assert understanding.calls == 0
        assert ha.calls == [("switch", "turn_on", {"entity_id": "switch.room"})]
    finally:
        undo_requests.close()
        activity.close()
        tokens.close()
        pending.close()
        requests.close()
        memory.close()


@pytest.mark.asyncio
async def test_sensitive_undo_requires_yes_and_marks_original_activity_undone(tmp_path):
    memory = BobiMemory(tmp_path / "memory.db")
    requests = RequestLedger(tmp_path / "requests.db")
    pending = PendingApprovalStore(tmp_path / "pending.db")
    tokens = ApprovalStore(tmp_path / "tokens.db")
    activity = ActivityLedger(tmp_path / "activity.db")
    undo_requests = UndoRequestStore(tmp_path / "undo.db")
    ha = FakeHA({"lock.front": {"state": "locked", "attributes": {}}})
    lock_plan = _plan(
        "previous-lock",
        entity_id="lock.front",
        domain="lock",
        action="lock",
        capability="lock",
        expected={"state": "locked"},
    )
    activity.record_verified(
        user_key="u1",
        execution=ExecutionResult(
            True,
            True,
            "verified",
            lock_plan,
            before={"state": "unlocked", "attributes": {}},
            after={"state": "locked", "attributes": {}},
        ),
        created_ts=90,
    )
    understanding = NeverUnderstanding()

    async def policy(user_key: str) -> UserPolicy:
        return UserPolicy(
            user_key,
            max_without_approval=RiskLevel.MEDIUM,
            can_approve=True,
        )

    handler = build_conversation_handler(
        understanding=understanding,
        list_devices=_devices,
        policy_for=policy,
        ha=ha,
        memory=memory,
        requests=requests,
        pending_approvals=pending,
        approval_tokens=tokens,
        activity=activity,
        undo_requests=undo_requests,
        clock=lambda: 100,
        verification_delay=0,
    )
    try:
        first = await handler(_message("m1", "בטל את הפעולה האחרונה"))
        assert "דורש אישור" in first.text
        assert ha.calls == []
        assert activity.latest_undoable("u1") is not None

        second = await handler(_message("m2", "כן"))
        assert second.text == "✅ אושר ובוצע."
        assert ha.calls == [("lock", "unlock", {"entity_id": "lock.front"})]
        assert activity.latest_undoable("u1") is None
        assert understanding.calls == 0
    finally:
        undo_requests.close()
        activity.close()
        tokens.close()
        pending.close()
        requests.close()
        memory.close()
