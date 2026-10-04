"""Parity comparison between legacy Bobi observations and Bobi Next.

Parity does not mean copying bugs.  The comparator supports an explicit expected
behavior contract: when Next matches that contract and legacy does not, the
verdict is ``improved`` rather than a false regression.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .intent import SemanticIntent, canonical_domain, canonical_operation
from .models import ActionPlan

Verdict = Literal["match", "improved", "regression", "mismatch", "inconclusive"]


@dataclass(slots=True)
class ExpectedBehavior:
    domain: str = ""
    operation: str = ""
    target_ids: tuple[str, ...] = ()
    value: Any = None
    scheduled: bool | None = None
    schedule_kind: str = ""


@dataclass(slots=True)
class LegacyObservation:
    handled: bool | None = None
    skill: str = ""
    family: str = ""
    domain: str = ""
    operation: str = ""
    target_scopes: tuple[str, ...] = ()
    value_kind: str = ""
    scheduled: bool | None = None
    conditional: bool | None = None
    contextual: bool | None = None
    schedule_kind: str = ""
    target_ids: tuple[str, ...] = ()
    plan_valid: bool | None = None
    execution_ready: bool | None = None
    value: Any = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParityReport:
    verdict: Verdict
    matches: dict[str, bool | None]
    legacy: LegacyObservation
    notes: tuple[str, ...] = ()


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _tuple_strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set)):
        return ()
    return tuple(str(item) for item in value if str(item).strip())


def _useful_param(params: dict[str, Any]) -> Any:
    for key in ("temperature", "brightness", "kelvin", "position", "option"):
        value = params.get(key)
        if value in (None, "", -1, -1.0):
            continue
        return value
    return None


def legacy_probe_observation(payload: dict[str, Any]) -> LegacyObservation:
    """Normalize either a service_response envelope or the probe payload itself."""

    root = _mapping(payload.get("service_response")) or payload
    probe = _mapping(root.get("result"))
    understanding = _mapping(probe.get("understanding"))
    return LegacyObservation(
        handled=probe.get("handled") if "handled" in probe else None,
        skill=str(probe.get("skill", "")),
        family=str(understanding.get("family", "")),
        domain=canonical_domain(str(understanding.get("domain", ""))),
        operation=canonical_operation(
            str(understanding.get("operation") or understanding.get("action") or "")
        ),
        target_scopes=_tuple_strings(understanding.get("target_scope")),
        value_kind=str(understanding.get("value_kind", "")),
        scheduled=bool(understanding.get("scheduled")) if understanding else None,
        conditional=bool(understanding.get("conditional")) if understanding else None,
        contextual=bool(understanding.get("contextual")) if understanding else None,
        schedule_kind=str(probe.get("schedule_kind", "")),
        raw=dict(root),
    )


def legacy_plan_observation(payload: dict[str, Any]) -> LegacyObservation:
    root = _mapping(payload.get("service_response")) or payload
    params = _mapping(root.get("params"))
    return LegacyObservation(
        family=str(root.get("family", "")),
        domain=canonical_domain(str(root.get("domain", ""))),
        operation=canonical_operation(str(root.get("action", ""))),
        target_ids=_tuple_strings(root.get("target_ids")),
        plan_valid=bool(root.get("valid")) if "valid" in root else None,
        execution_ready=(
            bool(root.get("execution_ready")) if "execution_ready" in root else None
        ),
        value=_useful_param(params),
        raw=dict(root),
    )


def _next_plan_operation(plan: ActionPlan) -> str:
    aliases = {
        "turn_on": "on",
        "turn_off": "off",
        "set_temperature": "set",
        "set_cover_position": "set_position",
        "open_cover": "open",
        "close_cover": "close",
        "stop_cover": "stop",
        "return_to_base": "return_home",
    }
    return aliases.get(plan.action, canonical_operation(plan.action))


def _next_plan_value(plans: tuple[ActionPlan, ...]) -> Any:
    if len(plans) != 1:
        return None
    data = plans[0].data
    for key in ("temperature", "brightness_pct", "position", "option"):
        if key in data:
            return data[key]
    return None


def _expected_score(
    *,
    domain: str,
    operation: str,
    target_ids: tuple[str, ...],
    value: Any,
    scheduled: bool | None,
    schedule_kind: str,
    expected: ExpectedBehavior,
) -> bool:
    checks: list[bool] = []
    if expected.domain:
        checks.append(canonical_domain(domain) == canonical_domain(expected.domain))
    if expected.operation:
        checks.append(canonical_operation(operation) == canonical_operation(expected.operation))
    if expected.target_ids:
        checks.append(set(target_ids) == set(expected.target_ids))
    if expected.value is not None:
        checks.append(value == expected.value)
    if expected.scheduled is not None:
        checks.append(scheduled is expected.scheduled)
    if expected.schedule_kind:
        checks.append(schedule_kind == expected.schedule_kind)
    return bool(checks) and all(checks)


def compare_semantics(
    legacy: LegacyObservation,
    current: SemanticIntent,
    *,
    expected: ExpectedBehavior | None = None,
) -> ParityReport:
    matches: dict[str, bool | None] = {
        "domain": legacy.domain == current.canonical_domain if legacy.domain else None,
        "operation": (
            legacy.operation == current.canonical_operation if legacy.operation else None
        ),
        "family": legacy.family == current.family if legacy.family else None,
        "scheduled": legacy.scheduled == current.scheduled if legacy.scheduled is not None else None,
        "conditional": (
            legacy.conditional == current.conditional if legacy.conditional is not None else None
        ),
        "target_scopes": (
            set(legacy.target_scopes) == set(current.target_scopes)
            if legacy.target_scopes
            else None
        ),
        "value_kind": legacy.value_kind == current.value_kind if legacy.value_kind else None,
        "schedule_kind": (
            legacy.schedule_kind == current.schedule_kind if legacy.schedule_kind else None
        ),
    }
    known = [value for value in matches.values() if value is not None]
    legacy_matches_next = bool(known) and all(known)

    if expected is not None:
        legacy_expected = _expected_score(
            domain=legacy.domain,
            operation=legacy.operation,
            target_ids=legacy.target_ids,
            value=legacy.value,
            scheduled=legacy.scheduled,
            schedule_kind=legacy.schedule_kind,
            expected=expected,
        )
        next_expected = _expected_score(
            domain=current.canonical_domain,
            operation=current.canonical_operation,
            target_ids=(),
            value=current.value,
            scheduled=current.scheduled,
            schedule_kind=current.schedule_kind,
            expected=expected,
        )
        if next_expected and not legacy_expected:
            return ParityReport("improved", matches, legacy, ("legacy_behavior_differs_from_contract",))
        if legacy_expected and not next_expected:
            return ParityReport("regression", matches, legacy, ("next_behavior_differs_from_contract",))

    if legacy_matches_next:
        return ParityReport("match", matches, legacy)
    if not known:
        return ParityReport("inconclusive", matches, legacy, ("legacy_has_no_comparable_semantics",))
    return ParityReport("mismatch", matches, legacy)


def compare_plans(
    legacy: LegacyObservation,
    plans: tuple[ActionPlan, ...],
    *,
    expected: ExpectedBehavior | None = None,
) -> ParityReport:
    next_domain = canonical_domain(plans[0].domain) if plans else ""
    operations = {_next_plan_operation(plan) for plan in plans}
    next_operation = next(iter(operations)) if len(operations) == 1 else ""
    next_targets = tuple(plan.entity_id for plan in plans)
    next_value = _next_plan_value(plans)

    matches: dict[str, bool | None] = {
        "domain": legacy.domain == next_domain if legacy.domain and next_domain else None,
        "operation": (
            legacy.operation == next_operation if legacy.operation and next_operation else None
        ),
        "targets": (
            set(legacy.target_ids) == set(next_targets) if legacy.target_ids or next_targets else None
        ),
        "value": legacy.value == next_value if legacy.value is not None else None,
    }
    known = [value for value in matches.values() if value is not None]
    legacy_matches_next = bool(known) and all(known)

    if expected is not None:
        legacy_expected = _expected_score(
            domain=legacy.domain,
            operation=legacy.operation,
            target_ids=legacy.target_ids,
            value=legacy.value,
            scheduled=None,
            schedule_kind="",
            expected=expected,
        )
        next_expected = _expected_score(
            domain=next_domain,
            operation=next_operation,
            target_ids=next_targets,
            value=next_value,
            scheduled=None,
            schedule_kind="",
            expected=expected,
        )
        if next_expected and not legacy_expected:
            return ParityReport("improved", matches, legacy, ("legacy_plan_differs_from_contract",))
        if legacy_expected and not next_expected:
            return ParityReport("regression", matches, legacy, ("next_plan_differs_from_contract",))

    if legacy_matches_next:
        return ParityReport("match", matches, legacy)
    if not known:
        return ParityReport("inconclusive", matches, legacy, ("no_comparable_plan_fields",))
    return ParityReport("mismatch", matches, legacy)
