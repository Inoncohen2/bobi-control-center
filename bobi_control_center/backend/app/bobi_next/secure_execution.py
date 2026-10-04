"""Authorization-aware execution boundary for Bobi Next.

This is the only path intended to connect a semantic ActionPlan to the generic
HA executor. It validates policy/provenance first and, when approval is
required, consumes a single-use approval bound to the exact plan and current
relevant state.
"""

from __future__ import annotations

from dataclasses import dataclass

from .authorization import (
    ApprovalStore,
    AuthorizationDecision,
    RequestProvenance,
    UserPolicy,
    approval_state_guard,
    authorize_plan,
    state_fingerprint,
)
from .executor import ExecutionResult, HAControlClient, execute_plan
from .models import ActionPlan


@dataclass(slots=True)
class SecureExecutionResult:
    authorization: AuthorizationDecision
    execution: ExecutionResult | None
    reason: str

    @property
    def executed(self) -> bool:
        return bool(self.execution and self.execution.executed)

    @property
    def verified(self) -> bool:
        return bool(self.execution and self.execution.verified)


async def execute_authorized_plan(
    plan: ActionPlan,
    client: HAControlClient,
    *,
    user_key: str,
    policy: UserPolicy,
    provenance: RequestProvenance,
    approval_store: ApprovalStore | None = None,
    approval_token: str = "",
    dry_run: bool = False,
    verification_attempts: int = 3,
    verification_delay: float = 0.35,
) -> SecureExecutionResult:
    """Authorize then execute, with a second state check to close the TOCTOU gap."""

    initial = authorize_plan(plan, policy=policy, provenance=provenance)
    if user_key != policy.user_key:
        mismatch = AuthorizationDecision(
            False,
            "policy_user_mismatch",
            initial.risk,
            False,
            False,
            initial.plan_fingerprint,
        )
        return SecureExecutionResult(mismatch, None, mismatch.reason)
    if not initial.requires_approval and not initial.allowed:
        return SecureExecutionResult(initial, None, initial.reason)

    approval_authorized = False
    approved_state_hash = ""
    if initial.requires_approval:
        if approval_store is None or not approval_token:
            return SecureExecutionResult(initial, None, "approval_required")

        before_approval = await client.get_state(plan.entity_id)
        guard = approval_state_guard(plan, before_approval)
        validation = approval_store.consume(
            token=approval_token,
            user_key=user_key,
            plan=plan,
            state_guard=guard,
        )
        if not validation.valid:
            return SecureExecutionResult(initial, None, validation.reason)
        approval_authorized = True
        approved_state_hash = validation.state_fingerprint

    final = authorize_plan(
        plan,
        policy=policy,
        provenance=provenance,
        approval_authorized=approval_authorized,
    )
    if not final.allowed:
        return SecureExecutionResult(final, None, final.reason)

    def precondition(snapshot: dict | None) -> bool:
        if not approved_state_hash:
            return True
        guard = approval_state_guard(plan, snapshot)
        return state_fingerprint(guard) == approved_state_hash

    execution = await execute_plan(
        plan,
        client,
        confirmation_authorized=approval_authorized,
        dry_run=dry_run,
        verification_attempts=verification_attempts,
        verification_delay=verification_delay,
        before_validator=precondition,
    )
    return SecureExecutionResult(final, execution, execution.reason)
