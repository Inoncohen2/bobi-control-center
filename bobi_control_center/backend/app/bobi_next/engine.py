"""End-to-end orchestration boundary for the generic Bobi Next device engine.

This module connects a provider-neutral message to deterministic Bobi contracts:
request ownership -> conversation context -> understanding -> routing -> target
resolution -> planning -> policy -> execution/verification or durable schedule.
It contains no household entity ids and does not know about WhatsApp directly.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Protocol

from .authorization import (
    ApprovalStore,
    RequestProvenance,
    UserPolicy,
    approval_state_guard,
    authorize_plan,
)
from .executor import HAControlClient
from .intent import SemanticIntent
from .memory import BobiMemory
from .models import ActionPlan, DeviceRecord, TargetResolution
from .planner import PlanError, build_plan
from .request_ledger import RequestLedger
from .resolver import resolve_target
from .routing import RoutedIntent, RoutingError, route_intent
from .scheduled_actions import capture_scheduled_action
from .scheduler import ScheduleStore
from .secure_execution import execute_authorized_plan


@dataclass(slots=True, frozen=True)
class UnderstandingContext:
    user_key: str
    recent_turns: tuple[dict, ...] = ()
    active_context: dict | None = None


class UnderstandingProvider(Protocol):
    async def understand(
        self,
        text: str,
        *,
        context: UnderstandingContext,
    ) -> SemanticIntent: ...


DeviceProvider = Callable[[], Awaitable[Iterable[DeviceRecord]]]
PolicyProvider = Callable[[str], Awaitable[UserPolicy]]


@dataclass(slots=True, frozen=True)
class EngineRequest:
    request_id: str
    user_key: str
    text: str
    owner_token: str
    message_id: str = ""
    now_ts: int = 0


@dataclass(slots=True, frozen=True)
class EngineResult:
    request_id: str
    outcome: str
    reason: str
    resolution: TargetResolution | None = None
    plans: tuple[ActionPlan, ...] = ()
    executed_count: int = 0
    verified_count: int = 0
    scheduled_job_id: str = ""
    approval_tokens: tuple[str, ...] = ()
    metadata: dict = field(default_factory=dict)


def _provenance(intent: SemanticIntent, resolution: TargetResolution) -> RequestProvenance:
    contextual = resolution.resolution_kind == "context" or intent.contextual
    device_ids = frozenset(device.bobi_id for device in resolution.devices)
    return RequestProvenance(
        source_kind="context" if contextual else "direct",
        same_text=not contextual,
        explicit_target_ids=frozenset() if contextual else device_ids,
        allowed_target_ids=device_ids if contextual else frozenset(),
        negated=intent.negated,
        question=bool(intent.metadata.get("question", False)),
        literal_name=bool(intent.metadata.get("literal_name", False)),
        reference_only=intent.reference_only or contextual,
    )


def _schedule_time(intent: SemanticIntent, now_ts: int) -> tuple[int, int]:
    payload = intent.schedule_payload
    if not isinstance(payload, dict):
        raise ValueError("invalid_schedule_payload")
    run_at_raw = payload.get("run_at_ts")
    delay_raw = payload.get("delay_seconds")
    if run_at_raw is not None:
        run_at = int(run_at_raw)
    elif delay_raw is not None:
        run_at = now_ts + max(1, int(float(delay_raw)))
    else:
        raise ValueError("schedule_time_missing")
    if run_at <= now_ts:
        raise ValueError("schedule_time_not_future")
    recurrence = max(0, int(payload.get("recurrence_seconds", 0) or 0))
    return run_at, recurrence


def _build_plans(
    request_id: str,
    routed: RoutedIntent,
    resolution: TargetResolution,
) -> tuple[ActionPlan, ...]:
    return tuple(
        build_plan(
            request_id=request_id,
            device=device,
            capability=routed.capability,
            operation=routed.operation,
            value=routed.value,
            delta=routed.delta,
            source=("context" if resolution.resolution_kind == "context" else "direct"),
            confidence=resolution.confidence,
        )
        for device in resolution.devices
    )


async def process_request(
    request: EngineRequest,
    *,
    understanding: UnderstandingProvider,
    list_devices: DeviceProvider,
    policy_for: PolicyProvider,
    ha: HAControlClient,
    memory: BobiMemory,
    requests: RequestLedger,
    schedules: ScheduleStore | None = None,
    approvals: ApprovalStore | None = None,
    dry_run: bool = False,
    context_ttl_seconds: int = 300,
    verification_attempts: int = 3,
    verification_delay: float = 0.35,
) -> EngineResult:
    """Process one semantic request with deterministic safety boundaries."""

    now = int(request.now_ts or time.time())
    claim = requests.claim(
        request_id=request.request_id,
        user_key=request.user_key,
        input_text=request.text,
        owner_token=request.owner_token,
        now_ts=now,
    )
    if not claim.claimed:
        return EngineResult(request.request_id, "duplicate", claim.reason)

    try:
        memory.store_turn(
            request.user_key,
            request.text,
            direction="inbound",
            message_id=request.message_id or request.request_id,
            created_ts=now,
        )
        active = memory.get_active_context(request.user_key, now_ts=now)
        context = UnderstandingContext(
            user_key=request.user_key,
            recent_turns=memory.recent_turns(request.user_key),
            active_context=active,
        )
        intent = await understanding.understand(request.text, context=context)
        if intent.negated and intent.mutating:
            requests.ignore(
                request.request_id,
                owner_token=request.owner_token,
                terminal_kind="negated",
                now_ts=now,
            )
            return EngineResult(request.request_id, "ignored", "source_negated")

        try:
            routed = route_intent(intent)
        except RoutingError as exc:
            requests.complete(
                request.request_id,
                owner_token=request.owner_token,
                terminal_kind="unsupported_intent",
                now_ts=now,
            )
            return EngineResult(request.request_id, "unsupported", str(exc))

        devices = tuple(await list_devices())
        memory.sync_devices(devices, now_ts=now)
        active_device_id = str((active or {}).get("bobi_device_id", ""))
        resolution = resolve_target(
            intent.target_text or intent.raw_text or request.text,
            devices,
            domain_hint=routed.domain_hint,
            capability=routed.capability,
            active_device_id=active_device_id,
            learned_aliases=memory.aliases_for,
            allow_group=routed.allow_group,
        )
        if not resolution.ok:
            requests.complete(
                request.request_id,
                owner_token=request.owner_token,
                terminal_kind="clarification",
                now_ts=now,
            )
            return EngineResult(
                request.request_id,
                "clarification",
                resolution.reason,
                resolution=resolution,
            )

        provenance = _provenance(intent, resolution)
        primary = resolution.devices[0]
        memory.set_active_context(
            request.user_key,
            bobi_device_id=primary.bobi_id,
            area_id=primary.area_id,
            object_type=routed.domain_hint,
            payload={
                "capability": routed.capability,
                "operation": routed.operation,
                "request_id": request.request_id,
            },
            ttl_seconds=context_ttl_seconds,
            now_ts=now,
        )

        if routed.defer_execution:
            if routed.defer_reason == "conditional":
                requests.complete(
                    request.request_id,
                    owner_token=request.owner_token,
                    terminal_kind="conditional_pending",
                    now_ts=now,
                )
                return EngineResult(
                    request.request_id,
                    "unsupported",
                    "conditional_engine_not_connected",
                    resolution=resolution,
                )
            if schedules is None:
                raise RuntimeError("scheduler_not_configured")
            run_at, recurrence = _schedule_time(intent, now)
            action = capture_scheduled_action(
                source_text=request.text,
                routed=routed,
                resolution=resolution,
                provenance=provenance,
            )
            job_id = f"req-{request.request_id}"
            schedules.create(
                job_id=job_id,
                user_key=request.user_key,
                run_at_ts=run_at,
                payload=action.to_payload(),
                recurrence_seconds=recurrence,
                now_ts=now,
            )
            requests.complete(
                request.request_id,
                owner_token=request.owner_token,
                terminal_kind="scheduled",
                now_ts=now,
            )
            return EngineResult(
                request.request_id,
                "scheduled",
                "scheduled",
                resolution=resolution,
                scheduled_job_id=job_id,
                metadata={"run_at_ts": run_at, "recurrence_seconds": recurrence},
            )

        plans = _build_plans(request.request_id, routed, resolution)
        policy = await policy_for(request.user_key)
        if policy.user_key != request.user_key:
            requests.fail_terminal(
                request.request_id,
                owner_token=request.owner_token,
                error="policy_user_mismatch",
                now_ts=now,
            )
            return EngineResult(
                request.request_id,
                "blocked",
                "policy_user_mismatch",
                resolution=resolution,
                plans=plans,
            )

        initial_decisions = [
            authorize_plan(plan, policy=policy, provenance=provenance) for plan in plans
        ]
        hard_block = next(
            (
                decision
                for decision in initial_decisions
                if not decision.allowed and not decision.requires_approval
            ),
            None,
        )
        if hard_block is not None:
            requests.complete(
                request.request_id,
                owner_token=request.owner_token,
                terminal_kind="blocked",
                now_ts=now,
            )
            return EngineResult(
                request.request_id,
                "blocked",
                hard_block.reason,
                resolution=resolution,
                plans=plans,
            )

        approval_tokens: list[str] = []
        if any(decision.requires_approval for decision in initial_decisions):
            if approvals is None:
                requests.complete(
                    request.request_id,
                    owner_token=request.owner_token,
                    terminal_kind="approval_required",
                    now_ts=now,
                )
                return EngineResult(
                    request.request_id,
                    "approval_required",
                    "approval_store_not_configured",
                    resolution=resolution,
                    plans=plans,
                )
            for plan, decision in zip(plans, initial_decisions, strict=True):
                if not decision.requires_approval:
                    continue
                snapshot = await ha.get_state(plan.entity_id)
                grant = approvals.issue(
                    user_key=request.user_key,
                    plan=plan,
                    state_guard=approval_state_guard(plan, snapshot),
                    summary=f"{plan.domain}.{plan.action}:{plan.entity_id}",
                )
                approval_tokens.append(grant.token)
            requests.complete(
                request.request_id,
                owner_token=request.owner_token,
                terminal_kind="approval_required",
                now_ts=now,
            )
            return EngineResult(
                request.request_id,
                "approval_required",
                "approval_required",
                resolution=resolution,
                plans=plans,
                approval_tokens=tuple(approval_tokens),
            )

        executed = 0
        verified = 0
        for plan in plans:
            result = await execute_authorized_plan(
                plan,
                ha,
                user_key=request.user_key,
                policy=policy,
                provenance=provenance,
                dry_run=dry_run,
                verification_attempts=verification_attempts,
                verification_delay=verification_delay,
            )
            if result.executed:
                executed += 1
            if result.verified:
                verified += 1
            if dry_run and result.reason == "dry_run":
                continue
            if not result.executed or not result.verified:
                reason = result.reason
                requests.fail_terminal(
                    request.request_id,
                    owner_token=request.owner_token,
                    error=reason,
                    terminal_kind="execution_failed",
                    now_ts=now,
                )
                return EngineResult(
                    request.request_id,
                    "failed",
                    reason,
                    resolution=resolution,
                    plans=plans,
                    executed_count=executed,
                    verified_count=verified,
                )

        terminal = "shadow" if dry_run else "executed"
        requests.complete(
            request.request_id,
            owner_token=request.owner_token,
            terminal_kind=terminal,
            now_ts=now,
        )
        return EngineResult(
            request.request_id,
            terminal,
            "dry_run" if dry_run else "verified",
            resolution=resolution,
            plans=plans,
            executed_count=executed,
            verified_count=verified,
        )
    except (PlanError, TypeError, ValueError) as exc:
        requests.fail_terminal(
            request.request_id,
            owner_token=request.owner_token,
            error=f"invalid_request:{exc}",
            terminal_kind="invalid_request",
            now_ts=now,
        )
        return EngineResult(request.request_id, "failed", f"invalid_request:{exc}")
    except Exception as exc:
        requests.retry(
            request.request_id,
            owner_token=request.owner_token,
            error=f"runtime_error:{type(exc).__name__}",
            now_ts=now,
        )
        return EngineResult(
            request.request_id,
            "retry",
            f"runtime_error:{type(exc).__name__}",
        )
