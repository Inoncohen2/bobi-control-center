"""Provider-neutral conversation handler for Bobi Next messaging workers.

Approval replies are consumed before any AI/understanding provider sees them.
All other messages enter the generic engine.  The handler returns only a safe
user-facing response; durable reaction/typing/outbox delivery remains owned by
``messaging.process_next_message``.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from .approval_continuation import approve_latest_pending, reject_latest_pending
from .authorization import ApprovalStore
from .engine import (
    DeviceProvider,
    EngineRequest,
    EngineResult,
    PolicyProvider,
    UnderstandingProvider,
    process_request,
)
from .executor import HAControlClient
from .memory import BobiMemory
from .messaging import InboundMessage, MessageResponse
from .pending_approval import PendingApprovalStore
from .request_ledger import RequestLedger
from .scheduler import ScheduleStore

Clock = Callable[[], int]

_POSITIVE_APPROVALS = frozenset(
    {
        "כן",
        "כן תבצע",
        "תבצע",
        "מאשר",
        "מאשרת",
        "אישור",
        "yes",
        "approve",
        "confirm",
    }
)
_NEGATIVE_APPROVALS = frozenset(
    {
        "לא",
        "לא תבצע",
        "אל תבצע",
        "בטל",
        "ביטול",
        "no",
        "cancel",
        "reject",
    }
)


def _normalize_confirmation(text: str) -> str:
    value = " ".join(text.casefold().strip().split())
    punctuation = {".", "!", "?", ",", "؛", "،"}
    while value and value[-1] in punctuation:
        value = value[:-1]
    return value


def _approval_prompt(result: EngineResult) -> str:
    if not result.plans:
        return "הפעולה דורשת אישור. להשיב כן או לא."
    if len(result.plans) == 1:
        plan = result.plans[0]
        return (
            "הפעולה דורשת אישור לפני ביצוע. "
            f"{plan.domain}.{plan.action} על {plan.entity_id}. להשיב כן או לא."
        )
    return f"{len(result.plans)} פעולות דורשות אישור לפני ביצוע. להשיב כן או לא."


def _terminal_recovery_message(terminal_kind: str) -> str:
    messages = {
        "executed": "✅ בוצע.",
        "shadow": "הפקודה נבדקה במצב Shadow ולא בוצעה בפועל.",
        "scheduled": "✅ הפעולה כבר תוזמנה.",
        "approval_required": "הפעולה כבר ממתינה לאישור. להשיב כן או לא.",
        "blocked": "הפעולה נחסמה לפי מדיניות הבטיחות.",
        "clarification": "צריך הבהרה לפני שאפשר לבצע את הפעולה.",
        "negated": "לא בוצעה פעולה.",
    }
    return messages.get(terminal_kind, "הבקשה כבר טופלה ולא תבוצע שוב.")


def _engine_response(result: EngineResult, requests: RequestLedger) -> MessageResponse:
    if result.outcome == "executed":
        return MessageResponse("✅ בוצע.")
    if result.outcome == "shadow":
        return MessageResponse("הפקודה נבדקה במצב Shadow ולא בוצעה בפועל.")
    if result.outcome == "scheduled":
        return MessageResponse("✅ הפעולה תוזמנה.")
    if result.outcome == "approval_required":
        return MessageResponse(_approval_prompt(result))
    if result.outcome == "clarification":
        return MessageResponse("לא הצלחתי לזהות יעד חד-משמעי. צריך הבהרה לפני ביצוע.")
    if result.outcome == "blocked":
        return MessageResponse("הפעולה נחסמה לפי מדיניות הבטיחות.")
    if result.outcome == "ignored":
        return MessageResponse("לא בוצעה פעולה.")
    if result.outcome == "unsupported":
        return MessageResponse("הפעולה עדיין לא נתמכת ב-Bobi Next.")
    if result.outcome == "retry":
        raise RuntimeError(result.reason)
    if result.outcome == "duplicate":
        record = requests.get(result.request_id)
        return MessageResponse(
            _terminal_recovery_message(record.terminal_kind if record is not None else "")
        )
    return MessageResponse("הפעולה לא הושלמה בבטחה.")


def build_conversation_handler(
    *,
    understanding: UnderstandingProvider,
    list_devices: DeviceProvider,
    policy_for: PolicyProvider,
    ha: HAControlClient,
    memory: BobiMemory,
    requests: RequestLedger,
    pending_approvals: PendingApprovalStore,
    approval_tokens: ApprovalStore,
    schedules: ScheduleStore | None = None,
    dry_run: bool = False,
    clock: Clock | None = None,
    verification_attempts: int = 3,
    verification_delay: float = 0.35,
):
    """Build a MessageHandler compatible with the durable messaging worker."""

    now_fn = clock or (lambda: int(time.time()))

    async def handler(message: InboundMessage) -> MessageResponse:
        normalized = _normalize_confirmation(message.text)
        now = int(now_fn())
        approval_owner = f"approval:{message.provider}:{message.message_id}"

        if normalized in _POSITIVE_APPROVALS:
            continuation = await approve_latest_pending(
                pending_approvals,
                approval_tokens,
                ha,
                user_key=message.user_key,
                policy_for=policy_for,
                owner_token=approval_owner,
                now_ts=now,
                verification_attempts=verification_attempts,
                verification_delay=verification_delay,
            )
            if continuation.outcome != "no_pending":
                memory.store_turn(
                    message.user_key,
                    message.text,
                    direction="inbound",
                    message_id=message.message_id,
                    created_ts=now,
                )
                if continuation.outcome == "completed":
                    text = "✅ אושר ובוצע."
                elif continuation.outcome == "retryable":
                    raise RuntimeError(continuation.reason)
                else:
                    text = "האישור לא בוצע כי תנאי הבטיחות השתנו או שהפעולה כבר לא תקפה."
                memory.store_turn(
                    message.user_key,
                    text,
                    direction="outbound",
                    message_id=f"reply:{message.message_id}",
                    created_ts=now,
                )
                return MessageResponse(text)

        if normalized in _NEGATIVE_APPROVALS:
            continuation = reject_latest_pending(
                pending_approvals,
                user_key=message.user_key,
                owner_token=approval_owner,
                now_ts=now,
            )
            if continuation.outcome != "no_pending":
                memory.store_turn(
                    message.user_key,
                    message.text,
                    direction="inbound",
                    message_id=message.message_id,
                    created_ts=now,
                )
                text = "בוטל. לא בוצעה פעולה."
                memory.store_turn(
                    message.user_key,
                    text,
                    direction="outbound",
                    message_id=f"reply:{message.message_id}",
                    created_ts=now,
                )
                return MessageResponse(text)

        engine_request_id = f"{message.provider}:{message.message_id}"
        result = await process_request(
            EngineRequest(
                request_id=engine_request_id,
                user_key=message.user_key,
                text=message.text,
                owner_token=f"engine:{message.provider}:{message.message_id}",
                message_id=message.message_id,
                now_ts=message.received_ts,
            ),
            understanding=understanding,
            list_devices=list_devices,
            policy_for=policy_for,
            ha=ha,
            memory=memory,
            requests=requests,
            schedules=schedules,
            pending_approvals=pending_approvals,
            dry_run=dry_run,
            verification_attempts=verification_attempts,
            verification_delay=verification_delay,
        )
        response = _engine_response(result, requests)
        memory.store_turn(
            message.user_key,
            response.text,
            direction="outbound",
            message_id=f"reply:{message.message_id}",
            created_ts=now,
        )
        return response

    return handler
