"""Explicit approval path for Bobi Next scheduled actions.

A due job that needs approval is held before any Home Assistant side effect.
When an authenticated user explicitly approves it, this module rebuilds the
plans from live discovery, rechecks policy, atomically claims that exact held
job and executes through the same single-use approval + verification boundary
used by immediate commands.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from .authorization import (
    ApprovalStore,
    UserPolicy,
    approval_state_guard,
    authorize_plan,
)
from .executor import HAControlClient
from .models import DeviceRecord
from .scheduled_actions import ScheduledDeviceAction, build_due_plans
from .scheduled_runner import _provenance_for
from .scheduler import ScheduleStore
from .secure_execution import execute_authorized_plan

DeviceProvider = Callable[[], Awaitable[Iterable[DeviceRecord]]]
PolicyProvider = Callable[[str], Awaitable[UserPolicy]]


@dataclass(slots=True, frozen=True)
class ScheduledApprovalResult:
    job_id: str
    outcome: str
    reason: str
    executed_count: int = 0
    verified_count: int = 0


def _fail_claimed(
    store: ScheduleStore,
    *,
    job_id: str,
    owner_token: str,
    reason: str,
    now_ts: int,
    any_side_effect: bool,
) -> ScheduledApprovalResult:
    if not any_side_effect and reason in {
        "approval_state_changed",
        "precondition_changed",
        "target_unavailable",
    }:
        store.hold_for_approval(
            job_id,
            owner_token=owner_token,
            reason=reason,
            now_ts=now_ts,
        )
        return ScheduledApprovalResult(job_id, "awaiting_approval", reason)

    store.fail(
        job_id,
        owner_token=owner_token,
        error=reason,
        now_ts=now_ts,
    )
    return ScheduledApprovalResult(job_id, "failed", reason)


async def approve_and_execute_scheduled_job(
    store: ScheduleStore,
    approval_store: ApprovalStore,
    client: HAControlClient,
    *,
    job_id: str,
    user_key: str,
    list_devices: DeviceProvider,
    policy_for: PolicyProvider,
    owner_token: str,
    now_ts: int,
    lease_seconds: int = 60,
    verification_attempts: int = 3,
    verification_delay: float = 0.35,
) -> ScheduledApprovalResult:
    """Execute one held job after an authenticated, explicit user approval."""

    existing = store.get(job_id)
    if existing is None:
        return ScheduledApprovalResult(job_id, "rejected", "job_not_found")
    if existing.user_key != user_key:
        return ScheduledApprovalResult(job_id, "rejected", "approval_wrong_user")
    if existing.state != "awaiting_approval":
        return ScheduledApprovalResult(job_id, "rejected", "job_not_awaiting_approval")

    try:
        action = ScheduledDeviceAction.from_payload(existing.payload)
        devices = tuple(await list_devices())
        plans = build_due_plans(action, devices, request_id=f"schedule-approval:{job_id}")
        policy = await policy_for(user_key)
    except (KeyError, TypeError, ValueError) as exc:
        return ScheduledApprovalResult(job_id, "rejected", f"invalid_scheduled_job:{exc}")
    except Exception as exc:
        return ScheduledApprovalResult(
            job_id,
            "rejected",
            f"scheduled_approval_prepare_error:{type(exc).__name__}",
        )

    if policy.user_key != user_key:
        return ScheduledApprovalResult(job_id, "rejected", "policy_user_mismatch")

    provenance = _provenance_for(action)
    for plan in plans:
        initial = authorize_plan(plan, policy=policy, provenance=provenance)
        if not initial.allowed and not initial.requires_approval:
            return ScheduledApprovalResult(job_id, "rejected", initial.reason)
        approved = authorize_plan(
            plan,
            policy=policy,
            provenance=provenance,
            approval_authorized=True,
        )
        if not approved.allowed:
            return ScheduledApprovalResult(job_id, "rejected", approved.reason)

    try:
        store.claim_awaiting_approval(
            job_id,
            owner_token=owner_token,
            now_ts=now_ts,
            lease_seconds=lease_seconds,
        )
    except RuntimeError:
        return ScheduledApprovalResult(job_id, "rejected", "approval_race_lost")

    executed_count = 0
    verified_count = 0
    try:
        for plan in plans:
            initial = authorize_plan(plan, policy=policy, provenance=provenance)
            approval_token = ""
            if initial.requires_approval:
                snapshot = await client.get_state(plan.entity_id)
                if snapshot is None or str(snapshot.get("state", "")) in {
                    "unknown",
                    "unavailable",
                }:
                    failed = _fail_claimed(
                        store,
                        job_id=job_id,
                        owner_token=owner_token,
                        reason="target_unavailable",
                        now_ts=now_ts,
                        any_side_effect=executed_count > 0,
                    )
                    return ScheduledApprovalResult(
                        failed.job_id,
                        failed.outcome,
                        failed.reason,
                        executed_count,
                        verified_count,
                    )
                grant = approval_store.issue(
                    user_key=user_key,
                    plan=plan,
                    state_guard=approval_state_guard(plan, snapshot),
                    summary=action.source_text,
                )
                approval_token = grant.token

            secure = await execute_authorized_plan(
                plan,
                client,
                user_key=user_key,
                policy=policy,
                provenance=provenance,
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
                failed = _fail_claimed(
                    store,
                    job_id=job_id,
                    owner_token=owner_token,
                    reason=(
                        f"partial_execution:{reason}" if executed_count else reason
                    ),
                    now_ts=now_ts,
                    any_side_effect=executed_count > 0,
                )
                return ScheduledApprovalResult(
                    failed.job_id,
                    failed.outcome,
                    failed.reason,
                    executed_count,
                    verified_count,
                )

        store.complete(job_id, owner_token=owner_token, now_ts=now_ts)
        return ScheduledApprovalResult(
            job_id,
            "completed",
            "verified",
            executed_count,
            verified_count,
        )
    except Exception as exc:
        reason = f"scheduled_approval_runtime_error:{type(exc).__name__}"
        failed = _fail_claimed(
            store,
            job_id=job_id,
            owner_token=owner_token,
            reason=reason,
            now_ts=now_ts,
            any_side_effect=executed_count > 0,
        )
        return ScheduledApprovalResult(
            failed.job_id,
            failed.outcome,
            failed.reason,
            executed_count,
            verified_count,
        )
