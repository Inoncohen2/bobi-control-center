"""Secure runtime for due Bobi Next scheduled device actions.

The scheduler stores semantic intent and source authority only. When a job
becomes due this module rediscovers devices, rebuilds plans from live
capabilities/state, re-evaluates the authenticated user's policy and only then
enters the guarded HA executor. Approval-requiring jobs are held before any
side effect occurs.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from .authorization import RequestProvenance, UserPolicy, authorize_plan
from .executor import HAControlClient
from .models import DeviceRecord
from .scheduled_actions import ScheduledDeviceAction, build_due_plans
from .scheduler import ScheduledJob, ScheduleStore
from .secure_execution import execute_authorized_plan

DeviceProvider = Callable[[], Awaitable[Iterable[DeviceRecord]]]
PolicyProvider = Callable[[str], Awaitable[UserPolicy]]


@dataclass(slots=True, frozen=True)
class ScheduledRunResult:
    job_id: str
    outcome: str
    reason: str
    executed_count: int = 0
    verified_count: int = 0


def _provenance_for(action: ScheduledDeviceAction) -> RequestProvenance:
    """Restore the authority captured when the delayed command was created.

    Development-era schema-v1 jobs intentionally deserialize with legacy,
    fail-closed provenance. They therefore need fresh approval instead of
    receiving invented direct-command authority at execution time.
    """

    if action.schema_version == 1:
        return RequestProvenance(
            source_kind="legacy",
            same_text=False,
            reference_only=True,
        )
    return RequestProvenance(
        source_kind=action.provenance_source_kind,
        same_text=action.provenance_same_text,
        explicit_target_ids=frozenset(action.provenance_explicit_device_ids),
        allowed_target_ids=frozenset(action.provenance_allowed_device_ids),
        negated=action.provenance_negated,
        question=action.provenance_question,
        literal_name=action.provenance_literal_name,
        reference_only=action.provenance_reference_only,
    )


def _finalize_failure(
    store: ScheduleStore,
    job: ScheduledJob,
    *,
    owner_token: str,
    reason: str,
    now_ts: int,
    retry_delay_seconds: int,
    max_attempts: int,
    any_side_effect: bool,
) -> ScheduledRunResult:
    """Retry only when no HA side effect has happened.

    Retrying after an unverified mutation is unsafe for relative commands such
    as "+0.5 degree", because rebuilding from live state could apply the delta
    twice. Those failures are terminal and must be surfaced for inspection.
    """

    may_retry = not any_side_effect and job.attempts < max(1, int(max_attempts))
    if may_retry:
        store.fail(
            job.job_id,
            owner_token=owner_token,
            error=reason,
            retry_at_ts=now_ts + max(1, int(retry_delay_seconds)),
            now_ts=now_ts,
        )
        return ScheduledRunResult(job.job_id, "retry", reason)

    store.fail(
        job.job_id,
        owner_token=owner_token,
        error=reason,
        now_ts=now_ts,
    )
    return ScheduledRunResult(job.job_id, "failed", reason)


async def run_due_jobs(
    store: ScheduleStore,
    client: HAControlClient,
    *,
    list_devices: DeviceProvider,
    policy_for: PolicyProvider,
    owner_token: str,
    now_ts: int,
    lease_seconds: int = 60,
    limit: int = 20,
    retry_delay_seconds: int = 30,
    max_attempts: int = 3,
    verification_attempts: int = 3,
    verification_delay: float = 0.35,
) -> tuple[ScheduledRunResult, ...]:
    """Claim and safely process due jobs owned by this worker."""

    jobs = store.claim_due(
        owner_token=owner_token,
        now_ts=now_ts,
        lease_seconds=lease_seconds,
        limit=limit,
    )
    results: list[ScheduledRunResult] = []

    for job in jobs:
        executed_count = 0
        verified_count = 0
        try:
            action = ScheduledDeviceAction.from_payload(job.payload)
            devices = tuple(await list_devices())
            plans = build_due_plans(action, devices, request_id=f"schedule:{job.job_id}")
            policy = await policy_for(job.user_key)
            if policy.user_key != job.user_key:
                results.append(
                    _finalize_failure(
                        store,
                        job,
                        owner_token=owner_token,
                        reason="policy_user_mismatch",
                        now_ts=now_ts,
                        retry_delay_seconds=retry_delay_seconds,
                        max_attempts=1,
                        any_side_effect=False,
                    )
                )
                continue

            provenance = _provenance_for(action)
            decisions = [
                authorize_plan(plan, policy=policy, provenance=provenance) for plan in plans
            ]
            blocking = next((decision for decision in decisions if not decision.allowed), None)
            if blocking is not None:
                if blocking.requires_approval:
                    store.hold_for_approval(
                        job.job_id,
                        owner_token=owner_token,
                        reason=blocking.reason,
                        now_ts=now_ts,
                    )
                    results.append(
                        ScheduledRunResult(job.job_id, "awaiting_approval", blocking.reason)
                    )
                else:
                    results.append(
                        _finalize_failure(
                            store,
                            job,
                            owner_token=owner_token,
                            reason=blocking.reason,
                            now_ts=now_ts,
                            retry_delay_seconds=retry_delay_seconds,
                            max_attempts=1,
                            any_side_effect=False,
                        )
                    )
                continue

            for plan in plans:
                secure = await execute_authorized_plan(
                    plan,
                    client,
                    user_key=job.user_key,
                    policy=policy,
                    provenance=provenance,
                    verification_attempts=verification_attempts,
                    verification_delay=verification_delay,
                )
                if secure.executed:
                    executed_count += 1
                if secure.verified:
                    verified_count += 1
                if not secure.executed or not secure.verified:
                    reason = secure.reason
                    result = _finalize_failure(
                        store,
                        job,
                        owner_token=owner_token,
                        reason=(
                            f"partial_execution:{reason}"
                            if executed_count or verified_count
                            else reason
                        ),
                        now_ts=now_ts,
                        retry_delay_seconds=retry_delay_seconds,
                        max_attempts=max_attempts,
                        any_side_effect=executed_count > 0,
                    )
                    results.append(
                        ScheduledRunResult(
                            result.job_id,
                            result.outcome,
                            result.reason,
                            executed_count,
                            verified_count,
                        )
                    )
                    break
            else:
                store.complete(job.job_id, owner_token=owner_token, now_ts=now_ts)
                results.append(
                    ScheduledRunResult(
                        job.job_id,
                        "completed",
                        "verified",
                        executed_count,
                        verified_count,
                    )
                )
        except (KeyError, TypeError, ValueError) as exc:
            results.append(
                _finalize_failure(
                    store,
                    job,
                    owner_token=owner_token,
                    reason=f"invalid_scheduled_job:{exc}",
                    now_ts=now_ts,
                    retry_delay_seconds=retry_delay_seconds,
                    max_attempts=1,
                    any_side_effect=executed_count > 0,
                )
            )
        except Exception as exc:
            results.append(
                _finalize_failure(
                    store,
                    job,
                    owner_token=owner_token,
                    reason=f"scheduled_runtime_error:{type(exc).__name__}",
                    now_ts=now_ts,
                    retry_delay_seconds=retry_delay_seconds,
                    max_attempts=max_attempts,
                    any_side_effect=executed_count > 0,
                )
            )

    return tuple(results)
