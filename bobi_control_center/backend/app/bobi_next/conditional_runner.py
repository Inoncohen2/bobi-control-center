"""Secure execution of Bobi Next conditional rules.

A state/event match never calls Home Assistant directly.  The runner claims an
idempotent rule/event receipt, rediscovers devices, rebuilds fresh plans, checks
policy and either executes through the secure verifier or persists a normal
pending approval request for sensitive actions.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from .authorization import UserPolicy, approval_state_guard, authorize_plan
from .conditional import ConditionalRule, ConditionalRuleStore, StateChangeEvent, event_matches
from .executor import HAControlClient
from .models import DeviceRecord
from .pending_approval import PendingApprovalStore
from .scheduled_actions import ScheduledDeviceAction, build_due_plans
from .scheduled_runner import _provenance_for
from .secure_execution import execute_authorized_plan

DeviceProvider = Callable[[], Awaitable[Iterable[DeviceRecord]]]
PolicyProvider = Callable[[str], Awaitable[UserPolicy]]


@dataclass(slots=True, frozen=True)
class ConditionalRunResult:
    rule_id: str
    event_id: str
    outcome: str
    reason: str
    executed_count: int = 0
    verified_count: int = 0
    approval_request_id: str = ""


async def run_conditional_event(
    store: ConditionalRuleStore,
    client: HAControlClient,
    *,
    event: StateChangeEvent,
    list_devices: DeviceProvider,
    policy_for: PolicyProvider,
    pending_approvals: PendingApprovalStore | None = None,
    verification_attempts: int = 3,
    verification_delay: float = 0.35,
) -> tuple[ConditionalRunResult, ...]:
    """Evaluate one normalized HA event against all enabled Bobi rules."""

    devices = tuple(await list_devices())
    results: list[ConditionalRunResult] = []
    for rule in store.enabled_rules():
        if not event_matches(rule.trigger, event, devices):
            continue
        result = await _run_matched_rule(
            store,
            rule,
            event,
            devices=devices,
            client=client,
            policy_for=policy_for,
            pending_approvals=pending_approvals,
            verification_attempts=verification_attempts,
            verification_delay=verification_delay,
        )
        results.append(result)
    return tuple(results)


async def _run_matched_rule(
    store: ConditionalRuleStore,
    rule: ConditionalRule,
    event: StateChangeEvent,
    *,
    devices: tuple[DeviceRecord, ...],
    client: HAControlClient,
    policy_for: PolicyProvider,
    pending_approvals: PendingApprovalStore | None,
    verification_attempts: int,
    verification_delay: float,
) -> ConditionalRunResult:
    if not store.claim_fire(
        rule_id=rule.rule_id,
        event_id=event.event_id,
        now_ts=event.occurred_ts,
    ):
        return ConditionalRunResult(
            rule.rule_id,
            event.event_id,
            "duplicate_or_cooldown",
            "fire_not_claimed",
        )

    executed = 0
    verified = 0
    try:
        action = ScheduledDeviceAction.from_payload(rule.action_payload)
        plans = build_due_plans(
            action,
            devices,
            request_id=f"conditional:{rule.rule_id}:{event.event_id}",
        )
        provenance = _provenance_for(action)
        policy = await policy_for(rule.user_key)
        if policy.user_key != rule.user_key:
            return _fail(
                store,
                rule,
                event,
                "policy_user_mismatch",
                executed,
                verified,
            )

        decisions = [
            authorize_plan(plan, policy=policy, provenance=provenance) for plan in plans
        ]
        hard_block = next(
            (
                decision
                for decision in decisions
                if not decision.allowed and not decision.requires_approval
            ),
            None,
        )
        if hard_block is not None:
            return _fail(
                store,
                rule,
                event,
                hard_block.reason,
                executed,
                verified,
            )

        if any(decision.requires_approval for decision in decisions):
            if pending_approvals is None:
                return _fail(
                    store,
                    rule,
                    event,
                    "pending_approval_store_not_configured",
                    executed,
                    verified,
                )
            state_guards: list[dict] = []
            for plan, decision in zip(plans, decisions, strict=True):
                if not decision.requires_approval:
                    state_guards.append({})
                    continue
                snapshot = await client.get_state(plan.entity_id)
                if snapshot is None or str(snapshot.get("state", "")) in {
                    "unknown",
                    "unavailable",
                }:
                    return _fail(
                        store,
                        rule,
                        event,
                        "target_unavailable",
                        executed,
                        verified,
                    )
                state_guards.append(approval_state_guard(plan, snapshot))

            approval_request_id = f"cond-{rule.rule_id}-{event.event_id}"
            pending_approvals.create(
                approval_request_id=approval_request_id,
                source_request_id=f"conditional:{rule.rule_id}:{event.event_id}",
                user_key=rule.user_key,
                plans=plans,
                provenance=provenance,
                state_guards=tuple(state_guards),
                summary=rule.source_text,
                now_ts=event.occurred_ts,
            )
            store.finish_fire(
                rule_id=rule.rule_id,
                event_id=event.event_id,
                success=True,
                now_ts=event.occurred_ts,
            )
            return ConditionalRunResult(
                rule.rule_id,
                event.event_id,
                "approval_required",
                "approval_required",
                approval_request_id=approval_request_id,
            )

        for plan in plans:
            result = await execute_authorized_plan(
                plan,
                client,
                user_key=rule.user_key,
                policy=policy,
                provenance=provenance,
                verification_attempts=verification_attempts,
                verification_delay=verification_delay,
            )
            if result.executed:
                executed += 1
            if result.verified:
                verified += 1
            if not result.executed or not result.verified:
                reason = result.reason
                if executed:
                    reason = f"partial_execution:{reason}"
                return _fail(
                    store,
                    rule,
                    event,
                    reason,
                    executed,
                    verified,
                )

        store.finish_fire(
            rule_id=rule.rule_id,
            event_id=event.event_id,
            success=True,
            now_ts=event.occurred_ts,
        )
        return ConditionalRunResult(
            rule.rule_id,
            event.event_id,
            "completed",
            "verified",
            executed,
            verified,
        )
    except (KeyError, TypeError, ValueError) as exc:
        return _fail(
            store,
            rule,
            event,
            f"invalid_rule:{exc}",
            executed,
            verified,
        )
    except Exception as exc:
        return _fail(
            store,
            rule,
            event,
            f"conditional_runtime_error:{type(exc).__name__}",
            executed,
            verified,
        )


def _fail(
    store: ConditionalRuleStore,
    rule: ConditionalRule,
    event: StateChangeEvent,
    reason: str,
    executed: int,
    verified: int,
) -> ConditionalRunResult:
    store.finish_fire(
        rule_id=rule.rule_id,
        event_id=event.event_id,
        success=False,
        now_ts=event.occurred_ts,
        error=reason,
    )
    return ConditionalRunResult(
        rule.rule_id,
        event.event_id,
        "failed",
        reason,
        executed,
        verified,
    )
