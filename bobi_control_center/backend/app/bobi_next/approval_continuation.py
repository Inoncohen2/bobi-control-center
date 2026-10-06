"""Restart-safe confirmation path for immediate Bobi Next requests."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .authorization import (
    ApprovalStore,
    UserPolicy,
    approval_state_guard,
    authorize_plan,
    state_fingerprint,
)
from .executor import HAControlClient
from .pending_approval import PendingApproval, PendingApprovalStore
from .secure_execution import execute_authorized_plan

PolicyProvider = Callable[[str], Awaitable[UserPolicy]]


@dataclass(slots=True, frozen=True)
class ApprovalContinuationResult:
    outcome: str
    reason: str
    approval_request_id: str = ""
    executed_count: int = 0
    verified_count: int = 0


async def _approve_claimed_pending(
    pending: PendingApproval,
    pending_store: PendingApprovalStore,
    approval_store: ApprovalStore,
    client: HAControlClient,
    *,
    user_key: str,
    policy_for: PolicyProvider,
    owner_token: str,
    now_ts: int,
    verification_attempts: int,
    verification_delay: float,
) -> ApprovalContinuationResult:
    request_id = pending.approval_request_id
    executed_count = 0
    verified_count = 0
    try:
        # Private Bobi plans have their own executor and state guards. Validate
        # the entire batch before even reading one target from Home Assistant.
        if any(
            plan.domain in {"archive", "expenses"}
            or re.fullmatch(r"[a-z0-9_]+\.[a-z0-9_]+", plan.entity_id) is None
            for plan in pending.plans
        ):
            pending_store.fail(
                request_id, owner_token=owner_token, error="non_ha_approval_plan", now_ts=now_ts,
            )
            return ApprovalContinuationResult("rejected", "non_ha_approval_plan", request_id)
        if pending.user_key != user_key:
            pending_store.fail(
                request_id,
                owner_token=owner_token,
                error="approval_user_mismatch",
                now_ts=now_ts,
            )
            return ApprovalContinuationResult(
                "rejected",
                "approval_user_mismatch",
                request_id,
            )

        policy = await policy_for(user_key)
        if policy.user_key != user_key:
            pending_store.fail(
                request_id,
                owner_token=owner_token,
                error="policy_user_mismatch",
                now_ts=now_ts,
            )
            return ApprovalContinuationResult(
                "rejected",
                "policy_user_mismatch",
                request_id,
            )

        for plan, original_guard in zip(
            pending.plans,
            pending.state_guards,
            strict=True,
        ):
            initial = authorize_plan(
                plan,
                policy=policy,
                provenance=pending.provenance,
            )
            if not initial.allowed and not initial.requires_approval:
                pending_store.fail(
                    request_id,
                    owner_token=owner_token,
                    error=initial.reason,
                    now_ts=now_ts,
                )
                return ApprovalContinuationResult(
                    "rejected",
                    initial.reason,
                    request_id,
                    executed_count,
                    verified_count,
                )

            approval_token = ""
            if initial.requires_approval:
                snapshot = await client.get_state(plan.entity_id)
                if snapshot is None or str(snapshot.get("state", "")) in {
                    "unknown",
                    "unavailable",
                }:
                    if executed_count:
                        pending_store.fail(
                            request_id,
                            owner_token=owner_token,
                            error="partial_execution:target_unavailable",
                            now_ts=now_ts,
                        )
                        return ApprovalContinuationResult(
                            "failed",
                            "partial_execution:target_unavailable",
                            request_id,
                            executed_count,
                            verified_count,
                        )
                    pending_store.release(
                        request_id,
                        owner_token=owner_token,
                        error="target_unavailable",
                        now_ts=now_ts,
                    )
                    return ApprovalContinuationResult(
                        "retryable",
                        "target_unavailable",
                        request_id,
                    )

                current_guard = approval_state_guard(plan, snapshot)
                if state_fingerprint(current_guard) != state_fingerprint(original_guard):
                    pending_store.fail(
                        request_id,
                        owner_token=owner_token,
                        error="approval_state_changed",
                        now_ts=now_ts,
                    )
                    return ApprovalContinuationResult(
                        "rejected",
                        "approval_state_changed",
                        request_id,
                        executed_count,
                        verified_count,
                    )

                grant = approval_store.issue(
                    user_key=user_key,
                    plan=plan,
                    state_guard=current_guard,
                    summary=pending.summary,
                    ttl_seconds=60,
                )
                approval_token = grant.token

            secure = await execute_authorized_plan(
                plan,
                client,
                user_key=user_key,
                policy=policy,
                provenance=pending.provenance,
                approval_store=approval_store,
                approval_token=approval_token,
                verification_attempts=verification_attempts,
                verification_delay=verification_delay,
            )
            if secure.executed:
                executed_count += 1
            if secure.verified:
                verified_count += 1
            if not secure.executed or not secure.verified:
                reason = secure.reason
                if executed_count:
                    reason = f"partial_execution:{reason}"
                pending_store.fail(
                    request_id,
                    owner_token=owner_token,
                    error=reason,
                    now_ts=now_ts,
                )
                return ApprovalContinuationResult(
                    "failed",
                    reason,
                    request_id,
                    executed_count,
                    verified_count,
                )

        pending_store.complete(
            request_id,
            owner_token=owner_token,
            now_ts=now_ts,
        )
        return ApprovalContinuationResult(
            "completed",
            "verified",
            request_id,
            executed_count,
            verified_count,
        )
    except Exception as exc:
        reason = f"approval_runtime_error:{type(exc).__name__}"
        if executed_count:
            pending_store.fail(
                request_id,
                owner_token=owner_token,
                error=f"partial_execution:{reason}",
                now_ts=now_ts,
            )
            return ApprovalContinuationResult(
                "failed",
                f"partial_execution:{reason}",
                request_id,
                executed_count,
                verified_count,
            )
        pending_store.release(
            request_id,
            owner_token=owner_token,
            error=reason,
            now_ts=now_ts,
        )
        return ApprovalContinuationResult(
            "retryable",
            reason,
            request_id,
        )


async def approve_latest_pending(
    pending_store: PendingApprovalStore,
    approval_store: ApprovalStore,
    client: HAControlClient,
    *,
    user_key: str,
    policy_for: PolicyProvider,
    owner_token: str,
    now_ts: int,
    lease_seconds: int = 60,
    verification_attempts: int = 3,
    verification_delay: float = 0.35,
) -> ApprovalContinuationResult:
    """Approve exactly one latest request without persisting bearer tokens."""

    pending = pending_store.claim_latest(
        user_key=user_key,
        owner_token=owner_token,
        now_ts=now_ts,
        lease_seconds=lease_seconds,
    )
    if pending is None:
        return ApprovalContinuationResult("no_pending", "no_pending_approval")
    return await _approve_claimed_pending(
        pending,
        pending_store,
        approval_store,
        client,
        user_key=user_key,
        policy_for=policy_for,
        owner_token=owner_token,
        now_ts=now_ts,
        verification_attempts=verification_attempts,
        verification_delay=verification_delay,
    )


async def approve_pending_by_id(
    pending_store: PendingApprovalStore,
    approval_store: ApprovalStore,
    client: HAControlClient,
    *,
    approval_request_id: str,
    user_key: str,
    policy_for: PolicyProvider,
    owner_token: str,
    now_ts: int,
    lease_seconds: int = 60,
    verification_attempts: int = 3,
    verification_delay: float = 0.35,
) -> ApprovalContinuationResult:
    """Approve only the exact request bound to an authenticated interaction."""

    pending = pending_store.claim(
        approval_request_id=approval_request_id,
        user_key=user_key,
        owner_token=owner_token,
        now_ts=now_ts,
        lease_seconds=lease_seconds,
    )
    if pending is None:
        return ApprovalContinuationResult(
            "no_pending",
            "approval_not_available",
            approval_request_id,
        )
    return await _approve_claimed_pending(
        pending,
        pending_store,
        approval_store,
        client,
        user_key=user_key,
        policy_for=policy_for,
        owner_token=owner_token,
        now_ts=now_ts,
        verification_attempts=verification_attempts,
        verification_delay=verification_delay,
    )


def _reject_claimed_pending(
    pending: PendingApproval,
    pending_store: PendingApprovalStore,
    *,
    owner_token: str,
    now_ts: int,
) -> ApprovalContinuationResult:
    pending_store.reject(
        pending.approval_request_id,
        owner_token=owner_token,
        now_ts=now_ts,
    )
    return ApprovalContinuationResult(
        "rejected",
        "rejected_by_user",
        pending.approval_request_id,
    )


def reject_latest_pending(
    pending_store: PendingApprovalStore,
    *,
    user_key: str,
    owner_token: str,
    now_ts: int,
) -> ApprovalContinuationResult:
    """Atomically reject one latest pending approval for an authenticated user."""

    pending = pending_store.claim_latest(
        user_key=user_key,
        owner_token=owner_token,
        now_ts=now_ts,
    )
    if pending is None:
        return ApprovalContinuationResult("no_pending", "no_pending_approval")
    return _reject_claimed_pending(
        pending,
        pending_store,
        owner_token=owner_token,
        now_ts=now_ts,
    )


def reject_pending_by_id(
    pending_store: PendingApprovalStore,
    *,
    approval_request_id: str,
    user_key: str,
    owner_token: str,
    now_ts: int,
    lease_seconds: int = 60,
) -> ApprovalContinuationResult:
    """Reject only the exact request bound to an authenticated interaction."""

    pending = pending_store.claim(
        approval_request_id=approval_request_id,
        user_key=user_key,
        owner_token=owner_token,
        now_ts=now_ts,
        lease_seconds=lease_seconds,
    )
    if pending is None:
        return ApprovalContinuationResult(
            "no_pending",
            "approval_not_available",
            approval_request_id,
        )
    return _reject_claimed_pending(
        pending,
        pending_store,
        owner_token=owner_token,
        now_ts=now_ts,
    )
