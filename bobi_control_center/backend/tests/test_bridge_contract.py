"""The published specification must describe what this build actually does.

A document that says one thing while the adapter does another is worse than no
document: someone writes a Home Assistant script against it, the script is
correct by the document, and the commit fails. So the specification is derived
from the same declarations the calling code uses, and these tests hold that
derivation — every service covered, every declared operation listed, and every
risk rating matching the one the permission check reads.
"""

from __future__ import annotations

import json
import re

import pytest

from app.adapters.real import ALLOWED_SERVICES
from app.mock.management import MockManagementBridge
from app.services.bridge_contract import (
    COMMON_COMMIT_INPUTS,
    NEVER_CALLED,
    all_services,
    risk_to_role,
)
from app.services.bridge_report import build_bridge_contract
from app.services.manage import ManagementService
from app.services.resources import FORBIDDEN_SYSTEM_ACTIONS, SPECS
from app.services.roles import MINIMUM_ROLE


def service(**kwargs) -> ManagementService:
    return ManagementService(MockManagementBridge(**kwargs))


# --- the specification covers what the code calls ---------------------------
def test_every_service_the_adapter_may_call_is_specified() -> None:
    """A bridge the code can reach with nothing written about it is a trap."""
    specified = {entry.name for entry in all_services()}

    assert specified >= ALLOWED_SERVICES, ALLOWED_SERVICES - specified


def test_every_specified_service_is_one_the_adapter_may_call() -> None:
    """And the reverse: a document naming a service nothing calls is fiction."""
    specified = {entry.name for entry in all_services()}

    assert specified <= ALLOWED_SERVICES, specified - ALLOWED_SERVICES


@pytest.mark.parametrize("resource", sorted(set(SPECS) - {"tasks", "features"}))
def test_each_family_has_both_of_its_bridges_specified(resource) -> None:
    spec = SPECS[resource]
    names = {entry.name for entry in all_services()}

    assert spec.snapshot_service in names
    assert spec.commit_service in names


def test_every_write_service_lists_the_operations_it_must_accept() -> None:
    for entry in all_services():
        if entry.kind != "write" or entry.resource in ("tasks", "features"):
            continue
        assert set(entry.operations) == set(SPECS[entry.resource].operations), entry.name


def test_every_write_service_rates_each_of_its_operations() -> None:
    """An unrated operation would leave the two sides guessing separately."""
    for entry in all_services():
        if entry.kind != "write":
            continue
        for operation in entry.operations:
            assert operation in entry.operation_risk, f"{entry.name}.{operation}"
            assert entry.operation_risk[operation] in MINIMUM_ROLE, operation


def test_every_write_service_requires_the_preview_token() -> None:
    """The field 2.2.0 shipped without. It is on every commit or none."""
    required = {name for name, _, _ in COMMON_COMMIT_INPUTS}
    assert "preview_token" in required

    for entry in all_services():
        if entry.kind != "write":
            continue
        fields = {name for name, _, _ in entry.inputs}
        assert required <= fields, entry.name


def test_every_write_service_states_how_it_verifies() -> None:
    for entry in all_services():
        if entry.kind != "write":
            continue
        assert "read" in entry.verification.lower(), entry.name


def test_every_read_service_forbids_entity_ids_and_private_fields() -> None:
    for entry in all_services():
        if entry.kind != "read" or entry.name == "bobi_cc_manage_contract":
            continue
        rules = " ".join(entry.validation).lower()
        assert "entity_id" in rules, entry.name
        assert "phone" in rules, entry.name


def test_every_write_service_forbids_acting_on_a_stale_preview() -> None:
    for entry in all_services():
        if entry.kind != "write":
            continue
        rules = " ".join(entry.validation)
        assert "stale_preview" in rules, entry.name


def test_the_risk_mapping_published_is_the_one_enforced() -> None:
    """Both sides must rate a change the same way or the ratings mean nothing."""
    assert risk_to_role() == {risk: role.value for risk, role in MINIMUM_ROLE.items()}


def test_the_domains_never_called_include_every_one_the_screens_touch() -> None:
    """Every domain a managed family stands in front of is on the list."""
    for domain in (
        "light", "switch", "climate", "cover", "fan", "media_player", "vacuum",
        "lock", "scene", "script", "automation", "camera", "calendar", "todo",
        "input_boolean", "input_number", "input_select", "input_text",
        "input_datetime", "timer", "counter", "homeassistant", "hassio",
        "shell_command",
    ):
        assert domain in NEVER_CALLED, domain


def test_no_specified_service_is_a_raw_domain_service() -> None:
    for entry in all_services():
        assert "." not in entry.name, entry.name
        assert entry.name.startswith("bobi_cc_"), entry.name


# --- the report against a live contract -------------------------------------
async def test_a_family_the_contract_declares_is_reported_implemented() -> None:
    contract = await build_bridge_contract(service())

    assert "bobi_cc_settings_snapshot" in contract.implemented
    assert "bobi_cc_settings_commit" in contract.implemented


async def test_a_family_the_contract_omits_is_reported_missing() -> None:
    from app.mock.management import DEFAULT_RESOURCE_PAYLOADS

    held_back = {
        name: payload
        for name, payload in DEFAULT_RESOURCE_PAYLOADS.items()
        if name != "scenes"
    }
    contract = await build_bridge_contract(service(resources=held_back))

    assert "bobi_cc_scenes_snapshot" in contract.missing
    assert "bobi_cc_scene_commit" in contract.missing


async def test_a_family_with_no_operations_is_missing_only_its_commit_bridge() -> None:
    """The state a snapshot bridge is in before its commit bridge is written."""

    class NoOperations(MockManagementBridge):
        async def status(self):
            status = await super().status()
            for resource in status.resources:
                if resource.id == "scenes":
                    resource.operations = []
            return status

    contract = await build_bridge_contract(ManagementService(NoOperations()))

    assert "bobi_cc_scenes_snapshot" in contract.implemented
    assert "bobi_cc_scene_commit" in contract.missing


async def test_without_a_bridge_everything_is_missing() -> None:
    contract = await build_bridge_contract(ManagementService(None))

    assert contract.implemented == []
    assert "bobi_cc_manage_contract" in contract.missing


async def test_the_report_carries_no_household_data() -> None:
    """Names, rules and ratings — nothing about this house."""
    contract = await build_bridge_contract(service())
    blob = contract.model_dump_json()

    for leak in ("MUST-NOT-APPEAR", "ינון", "הודיה", "@lid"):
        assert leak not in blob, leak


async def test_the_report_names_the_actions_it_will_never_ask_for() -> None:
    contract = await build_bridge_contract(service())
    text = " ".join(contract.never_requested).lower()

    for word in ("restart", "supervisor", "delet", "backup", "shell"):
        assert word in text, word
    # And the enforcement list is not empty, so the promise has teeth.
    assert FORBIDDEN_SYSTEM_ACTIONS


# --- over HTTP --------------------------------------------------------------
def test_the_endpoint_answers_without_a_bridge(client) -> None:
    response = client.get("/api/bobi/manage/bridge-contract")

    assert response.status_code == 200
    body = response.json()
    assert body["services"], "the specification does not depend on Home Assistant"
    assert body["implemented"] == []


def test_the_endpoint_leaks_no_token(client) -> None:
    body = json.dumps(client.get("/api/bobi/manage/bridge-contract").json())

    for secret in ("SUPERVISOR_TOKEN", "Authorization", "Bearer ", "password"):
        assert secret not in body, secret
    # A minted preview token, rather than the letters `pt_` — which also occur
    # in the middle of `bobi_cc_script_commit`, as this test found out.
    assert not re.search(r"pt_[A-Za-z0-9_-]{20,}", body)
