"""Guarded Home Assistant execution with read-after-write verification.

This module has no transport-specific knowledge. Production wiring must supply
an HA client that can call a native service and read one entity state. The
executor fails closed on unavailable targets, low-confidence plans and missing
confirmation, and never treats an accepted service call as success until HA's
live state confirms the expected result.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from .models import ActionPlan


class HAControlClient(Protocol):
    async def call_service(self, domain: str, service: str, data: dict[str, Any]) -> Any: ...

    async def get_state(self, entity_id: str) -> dict[str, Any] | None: ...


@dataclass(slots=True)
class ExecutionResult:
    executed: bool
    verified: bool
    reason: str
    plan: ActionPlan
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None


def verify_expected(snapshot: dict[str, Any] | None, expected: dict[str, Any]) -> bool:
    if snapshot is None:
        return False
    state = str(snapshot.get("state", ""))
    attributes = snapshot.get("attributes")
    attrs = attributes if isinstance(attributes, dict) else {}

    if "state" in expected and state != str(expected["state"]):
        return False
    if "state_any" in expected and state not in {str(v) for v in expected["state_any"]}:
        return False
    if "state_not" in expected and state in {str(v) for v in expected["state_not"]}:
        return False
    if "attribute" not in expected:
        return True

    attribute = str(expected["attribute"])
    wanted = expected.get("value")
    tolerance = float(expected.get("tolerance", 0.0))
    if attribute == "brightness_pct":
        raw = attrs.get("brightness")
        if raw is None:
            return False
        try:
            actual = float(raw) / 255.0 * 100.0
            target = float(wanted)
        except (TypeError, ValueError):
            return False
        return abs(actual - target) <= tolerance

    raw = attrs.get(attribute)
    if raw is None:
        return False
    try:
        actual_number = float(raw)
        wanted_number = float(wanted)
    except (TypeError, ValueError):
        return str(raw) == str(wanted)
    return abs(actual_number - wanted_number) <= tolerance


async def execute_plan(
    plan: ActionPlan,
    client: HAControlClient,
    *,
    confirmation_authorized: bool = False,
    dry_run: bool = False,
    verification_attempts: int = 3,
    verification_delay: float = 0.35,
    before_validator: Callable[[dict[str, Any] | None], bool] | None = None,
) -> ExecutionResult:
    if plan.confidence < 0.90:
        return ExecutionResult(False, False, "low_confidence", plan)
    if plan.requires_confirmation and not confirmation_authorized:
        return ExecutionResult(False, False, "confirmation_required", plan)

    before = await client.get_state(plan.entity_id)
    if before is None or str(before.get("state", "")) in {"unknown", "unavailable"}:
        return ExecutionResult(False, False, "target_unavailable", plan, before=before)
    if before_validator is not None and not before_validator(before):
        return ExecutionResult(False, False, "precondition_changed", plan, before=before)
    if dry_run:
        return ExecutionResult(False, False, "dry_run", plan, before=before)

    await client.call_service(plan.domain, plan.action, dict(plan.data))

    after: dict[str, Any] | None = None
    attempts = max(1, int(verification_attempts))
    for attempt in range(attempts):
        after = await client.get_state(plan.entity_id)
        if verify_expected(after, plan.expected):
            return ExecutionResult(True, True, "verified", plan, before=before, after=after)
        if attempt + 1 < attempts:
            await asyncio.sleep(max(0.0, verification_delay))

    # A service call occurred, but Bobi must not claim verified success.
    return ExecutionResult(True, False, "verification_failed", plan, before=before, after=after)
