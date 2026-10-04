from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.bobi_next.authorization import ApprovalStore, UserPolicy
from app.bobi_next.conversation_handler import build_conversation_handler
from app.bobi_next.intent import SemanticIntent
from app.bobi_next.memory import BobiMemory
from app.bobi_next.messaging import InboundMessage
from app.bobi_next.models import DeviceRecord, EntityRecord
from app.bobi_next.pending_approval import PendingApprovalStore
from app.bobi_next.request_ledger import RequestLedger


class FakeHA:
    def __init__(self):
        self.states = {
            "lock.front": {"state": "locked", "attributes": {}},
            "switch.room": {"state": "on", "attributes": {}},
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
        if domain == "lock" and service == "unlock":
            self.states[entity_id]["state"] = "unlocked"
        elif service == "turn_off":
            self.states[entity_id]["state"] = "off"


@dataclass
class CountingUnderstanding:
    intents: dict[str, SemanticIntent]
    calls: int = 0

    async def understand(self, text, *, context):
        self.calls += 1
        return self.intents[text]


def _entity_device(
    *,
    bobi_id: str,
    entity_id: str,
    domain: str,
    name: str,
    state: str,
    capabilities: set[str],
) -> DeviceRecord:
    entity = EntityRecord(
        entity_id=entity_id,
        domain=domain,
        name=name,
        state=state,
        capabilities=frozenset(capabilities),
    )
    return DeviceRecord(
        bobi_id=bobi_id,
        stable_key=f"device:{bobi_id}",
        name=name,
        entities=(entity,),
        capabilities=entity.capabilities,
    )


def _lock() -> DeviceRecord:
    return _entity_device(
        bobi_id="dev-lock",
        entity_id="lock.front",
        domain="lock",
        name="Front door",
        state="locked",
        capabilities={"lock", "unlock"},
    )


def _switch() -> DeviceRecord:
    return _entity_device(
        bobi_id="dev-switch",
        entity_id="switch.room",
        domain="switch",
        name="Room switch",
        state="on",
        capabilities={"power"},
    )


def _intent(text: str, *, domain: str, operation: str, target: str) -> SemanticIntent:
    return SemanticIntent(
        raw_text=text,
        family="device_control",
        domain=domain,
        operation=operation,
        target_text=target,
        confidence=0.99,
    )


def _message(message_id: str, text: str, *, received_ts: int = 100) -> InboundMessage:
    return InboundMessage(
        row_id=1,
        provider="whatsapp",
        message_id=message_id,
        chat_id="chat-1",
        user_key="u1",
        text=text,
        kind="text",
        received_ts=received_ts,
        state="running",
    )


async def _policy(user_key: str) -> UserPolicy:
    return UserPolicy(user_key)


class RuntimeStores:
    def __init__(self, tmp_path):
        self.memory = BobiMemory(tmp_path / "bobi.db")
        self.requests = RequestLedger(tmp_path / "bobi.db")
        self.pending = PendingApprovalStore(tmp_path / "pending.db")
        self.tokens = ApprovalStore(tmp_path / "tokens.db")

    def close(self):
        self.tokens.close()
        self.pending.close()
        self.requests.close()
        self.memory.close()


@pytest.mark.asyncio
async def test_yes_approval_bypasses_ai_and_executes_exact_pending_plan(tmp_path):
    stores = RuntimeStores(tmp_path)
    ha = FakeHA()
    understanding = CountingUnderstanding(
        {"unlock door": _intent("unlock door", domain="lock", operation="unlock", target="Front door")}
    )

    async def devices():
        return (_lock(), _switch())

    handler = build_conversation_handler(
        understanding=understanding,
        list_devices=devices,
        policy_for=_policy,
        ha=ha,
        memory=stores.memory,
        requests=stores.requests,
        pending_approvals=stores.pending,
        approval_tokens=stores.tokens,
        clock=lambda: 101,
        verification_delay=0,
    )
    try:
        first = await handler(_message("m1", "unlock door", received_ts=100))
        assert "אישור" in first.text
        assert understanding.calls == 1
        assert ha.calls == []

        second = await handler(_message("m2", "כן", received_ts=101))
        assert second.text == "✅ אושר ובוצע."
        assert understanding.calls == 1
        assert ha.calls == [("lock", "unlock", {"entity_id": "lock.front"})]
    finally:
        stores.close()


@pytest.mark.asyncio
async def test_no_rejects_pending_before_ai_and_never_calls_ha(tmp_path):
    stores = RuntimeStores(tmp_path)
    ha = FakeHA()
    understanding = CountingUnderstanding(
        {"unlock door": _intent("unlock door", domain="lock", operation="unlock", target="Front door")}
    )

    async def devices():
        return (_lock(),)

    handler = build_conversation_handler(
        understanding=understanding,
        list_devices=devices,
        policy_for=_policy,
        ha=ha,
        memory=stores.memory,
        requests=stores.requests,
        pending_approvals=stores.pending,
        approval_tokens=stores.tokens,
        clock=lambda: 101,
        verification_delay=0,
    )
    try:
        await handler(_message("m1", "unlock door", received_ts=100))
        response = await handler(_message("m2", "לא", received_ts=101))
        assert response.text == "בוטל. לא בוצעה פעולה."
        assert understanding.calls == 1
        assert ha.calls == []
        assert stores.pending.get("approve-whatsapp:m1").state == "rejected"
    finally:
        stores.close()


@pytest.mark.asyncio
async def test_yes_without_pending_is_normal_conversation_input(tmp_path):
    stores = RuntimeStores(tmp_path)
    ha = FakeHA()
    understanding = CountingUnderstanding(
        {"כן": _intent("כן", domain="switch", operation="off", target="Room switch")}
    )

    async def devices():
        return (_switch(),)

    handler = build_conversation_handler(
        understanding=understanding,
        list_devices=devices,
        policy_for=_policy,
        ha=ha,
        memory=stores.memory,
        requests=stores.requests,
        pending_approvals=stores.pending,
        approval_tokens=stores.tokens,
        clock=lambda: 101,
        verification_delay=0,
    )
    try:
        response = await handler(_message("m1", "כן", received_ts=100))
        assert response.text == "✅ בוצע."
        assert understanding.calls == 1
        assert ha.calls == [("switch", "turn_off", {"entity_id": "switch.room"})]
    finally:
        stores.close()


@pytest.mark.asyncio
async def test_changed_state_rejects_yes_without_reinterpreting_it_with_ai(tmp_path):
    stores = RuntimeStores(tmp_path)
    ha = FakeHA()
    understanding = CountingUnderstanding(
        {"unlock door": _intent("unlock door", domain="lock", operation="unlock", target="Front door")}
    )

    async def devices():
        return (_lock(),)

    handler = build_conversation_handler(
        understanding=understanding,
        list_devices=devices,
        policy_for=_policy,
        ha=ha,
        memory=stores.memory,
        requests=stores.requests,
        pending_approvals=stores.pending,
        approval_tokens=stores.tokens,
        clock=lambda: 101,
        verification_delay=0,
    )
    try:
        await handler(_message("m1", "unlock door", received_ts=100))
        ha.states["lock.front"]["state"] = "unlocked"
        response = await handler(_message("m2", "כן", received_ts=101))
        assert "הבטיחות" in response.text
        assert understanding.calls == 1
        assert ha.calls == []
    finally:
        stores.close()
