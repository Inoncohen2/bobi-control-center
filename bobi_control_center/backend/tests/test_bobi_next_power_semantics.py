from __future__ import annotations

from app.bobi_next.executor import verify_expected
from app.bobi_next.models import DeviceRecord, EntityRecord
from app.bobi_next.planner import build_plan


def _device(domain: str, state: str = "off") -> DeviceRecord:
    entity = EntityRecord(
        entity_id=f"{domain}.test",
        domain=domain,
        state=state,
        capabilities=frozenset({"power"}),
    )
    return DeviceRecord(
        bobi_id=f"dev-{domain}",
        stable_key=f"ha-device:{domain}",
        name=f"Test {domain}",
        entities=(entity,),
        capabilities=entity.capabilities,
    )


def test_climate_turn_on_accepts_real_hvac_state_instead_of_literal_on():
    plan = build_plan(
        request_id="m1",
        device=_device("climate"),
        capability="power",
        operation="on",
    )

    assert plan.action == "turn_on"
    assert plan.expected == {"state_not": ["off", "unavailable", "unknown"]}
    assert verify_expected({"state": "cool", "attributes": {}}, plan.expected)
    assert verify_expected({"state": "heat", "attributes": {}}, plan.expected)
    assert not verify_expected({"state": "off", "attributes": {}}, plan.expected)


def test_switch_power_still_requires_literal_on():
    plan = build_plan(
        request_id="m2",
        device=_device("switch"),
        capability="power",
        operation="on",
    )

    assert plan.expected == {"state": "on"}
