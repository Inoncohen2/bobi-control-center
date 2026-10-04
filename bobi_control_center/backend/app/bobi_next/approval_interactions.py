"""Deterministic approval continuations for Bobi Next interactions.

Interactive approval prompts use a context key of
``approval:<approval_request_id>``.  The selected option is a stable internal key
(``approve`` or ``reject``), never AI-generated text.  The handler claims that
exact pending approval for the authenticated Bobi user and reuses the same
policy, state-fingerprint, single-use approval-token and read-after-write
verification path as text confirmations.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from .activity import ActivityLedger
from .approval_continuation import approve_pending_by_id, reject_pending_by_id
from .authorization import ApprovalStore
from .engine import PolicyProvider
from .executor import HAControlClient
from .interaction_dispatch import (
    InteractionHandler,
    InteractionHandlerResult,
    InteractionSelection,
)
from .pending_approval import PendingApprovalStore

Clock = Callable[[], int]


class ApprovalInteractionRetry(RuntimeError):
    """Signal a transient approval continuation failure to the dispatch worker."""


def _approval_request_id(context_key: str) -> str:
    namespace, separator, request_id = context_key.partition(":")
    if namespace != "approval" or not separator:
        return ""
    return request_id.strip()


def build_approval_interaction_handler(
    *,
    pending_approvals: PendingApprovalStore,
    approval_tokens: ApprovalStore,
    ha: HAControlClient,
    policy_for: PolicyProvider,
    activity: ActivityLedger | None = None,
    clock: Clock | None = None,
    verification_attempts: int = 3,
    verification_delay: float = 0.35,
) -> InteractionHandler:
    """Build the reserved ``approval`` interaction namespace handler."""

    now_fn = clock or (lambda: int(time.time()))

    async def handler(selection: InteractionSelection) -> InteractionHandlerResult:
        request_id = _approval_request_id(selection.context_key)
        if not request_id:
            return InteractionHandlerResult(
                outcome="invalid_approval_context",
                response_text="האישור אינו תקף. לא בוצעה פעולה.",
            )
        if len(selection.selected_keys) != 1:
            return InteractionHandlerResult(
                outcome="invalid_approval_selection",
                response_text="יש לבחור אפשרות אישור אחת בלבד. לא בוצעה פעולה.",
            )
        choice = selection.selected_keys[0]
        if choice not in {"approve", "reject"}:
            return InteractionHandlerResult(
                outcome="invalid_approval_selection",
                response_text="הבחירה אינה תקפה. לא בוצעה פעולה.",
            )

        now = int(now_fn())
        owner_token = f"approval-interaction:{selection.dispatch_id}"
        if choice == "reject":
            result = reject_pending_by_id(
                pending_approvals,
                approval_request_id=request_id,
                user_key=selection.user_key,
                owner_token=owner_token,
                now_ts=now,
            )
            if result.outcome == "rejected":
                return InteractionHandlerResult(
                    outcome="rejected",
                    response_text="בוטל. לא בוצעה פעולה.",
                )
            return InteractionHandlerResult(
                outcome="approval_not_available",
                response_text="האישור כבר אינו זמין או שכבר טופל. לא בוצעה פעולה.",
            )

        result = await approve_pending_by_id(
            pending_approvals,
            approval_tokens,
            ha,
            approval_request_id=request_id,
            user_key=selection.user_key,
            policy_for=policy_for,
            owner_token=owner_token,
            now_ts=now,
            verification_attempts=verification_attempts,
            verification_delay=verification_delay,
        )
        if result.outcome == "completed":
            if activity is not None:
                activity.mark_approval_completed(
                    result.approval_request_id,
                    now_ts=now,
                )
            return InteractionHandlerResult(
                outcome="completed",
                response_text="✅ אושר ובוצע.",
            )
        if result.outcome == "retryable":
            raise ApprovalInteractionRetry(result.reason)
        if result.outcome == "no_pending":
            return InteractionHandlerResult(
                outcome="approval_not_available",
                response_text="האישור כבר אינו זמין או שכבר טופל. לא בוצעה פעולה.",
            )
        return InteractionHandlerResult(
            outcome=result.outcome,
            response_text="האישור לא בוצע כי תנאי הבטיחות השתנו או שהפעולה כבר לא תקפה.",
        )

    return handler
