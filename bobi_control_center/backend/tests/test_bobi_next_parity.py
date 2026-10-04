from __future__ import annotations

from app.bobi_next.intent import SemanticIntent
from app.bobi_next.models import ActionPlan
from app.bobi_next.parity import (
    ExpectedBehavior,
    compare_plans,
    compare_semantics,
    legacy_plan_observation,
    legacy_probe_observation,
)


def test_legacy_probe_normalizes_domain_and_operation():
    legacy = legacy_probe_observation(
        {
            "result": {
                "handled": True,
                "skill": "canonical_command",
                "understanding": {
                    "family": "control",
                    "domain": "lighting",
                    "operation": "turn_off",
                    "target_scope": ["garden"],
                    "value_kind": "none",
                    "scheduled": False,
                    "conditional": False,
                },
            }
        }
    )

    assert legacy.domain == "light"
    assert legacy.operation == "off"
    assert legacy.target_scopes == ("garden",)


def test_semantic_parity_matches_equivalent_intent():
    legacy = legacy_probe_observation(
        {
            "result": {
                "handled": True,
                "skill": "canonical_command",
                "understanding": {
                    "family": "control",
                    "domain": "lighting",
                    "operation": "turn_off",
                    "target_scope": ["garden"],
                    "value_kind": "none",
                    "scheduled": False,
                    "conditional": False,
                },
            }
        }
    )
    current = SemanticIntent(
        raw_text="turn off garden light",
        family="control",
        domain="light",
        operation="off",
        target_scopes=("garden",),
        value_kind="none",
        confidence=0.99,
    )

    report = compare_semantics(legacy, current)
    assert report.verdict == "match"
    assert all(value is not False for value in report.matches.values())


def test_expected_contract_marks_fixed_legacy_misroute_as_improved():
    legacy = legacy_probe_observation(
        {
            "result": {
                "handled": True,
                "skill": "ac_swing_context",
                "understanding": {
                    "family": "control",
                    "domain": "climate",
                    "operation": "set",
                    "target_scope": ["living_room"],
                    "value_kind": "percentage",
                    "scheduled": False,
                    "conditional": False,
                },
            }
        }
    )
    current = SemanticIntent(
        raw_text="open living room cover to 30 percent",
        family="control",
        domain="cover",
        operation="set_position",
        target_scopes=("living_room",),
        value_kind="percentage",
        value=30,
        confidence=0.99,
    )

    report = compare_semantics(
        legacy,
        current,
        expected=ExpectedBehavior(domain="cover", operation="set_position", value=30),
    )
    assert report.verdict == "improved"


def test_plan_parity_matches_native_service_equivalent():
    legacy = legacy_plan_observation(
        {
            "valid": True,
            "execution_ready": True,
            "domain": "lighting",
            "family": "control",
            "action": "turn_off",
            "target_ids": ["switch.garden_light"],
            "params": {},
        }
    )
    plan = ActionPlan(
        request_id="m1",
        device_id="dev-garden",
        entity_id="switch.garden_light",
        domain="switch",
        action="turn_off",
        capability="power",
        confidence=0.99,
    )

    # Legacy uses the semantic lighting group while native HA correctly uses
    # the concrete switch domain.  Expected behavior is therefore explicit.
    report = compare_plans(
        legacy,
        (plan,),
        expected=ExpectedBehavior(operation="off", target_ids=("switch.garden_light",)),
    )
    assert report.verdict in {"match", "improved"}
    assert report.matches["operation"] is True
    assert report.matches["targets"] is True


def test_half_degree_missing_in_legacy_plan_is_an_improvement_not_regression():
    legacy = legacy_plan_observation(
        {
            "valid": True,
            "execution_ready": True,
            "domain": "climate",
            "action": "set",
            "target_ids": ["climate.bedroom"],
            "params": {"temperature": -1.0},
        }
    )
    plan = ActionPlan(
        request_id="m2",
        device_id="dev-bedroom",
        entity_id="climate.bedroom",
        domain="climate",
        action="set_temperature",
        capability="temperature",
        data={"entity_id": "climate.bedroom", "temperature": 23.5},
        confidence=0.99,
    )

    report = compare_plans(
        legacy,
        (plan,),
        expected=ExpectedBehavior(
            domain="climate",
            operation="set",
            target_ids=("climate.bedroom",),
            value=23.5,
        ),
    )
    assert report.verdict == "improved"
    assert legacy.value is None
