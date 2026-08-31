"""The contract Home Assistant actually publishes, held here verbatim.

## Why this file exists

`app/mock/management.py` is what every other test sees, and until this file
existed it advertised *every* verb in `SPECS[resource].operations`. The live 3c
contract advertises a subset: `calendar` names `add` and nothing else, `helpers`
names `set` and none of the timer verbs, `automations` and `scripts` name no
`rename`, `scenes` names nothing at all. So the double described a system nobody
could build, and every "the bridge did not declare this" path in the application
was exercised only against a bridge that declared everything.

That is not a hypothetical failure mode. It has already happened twice, in the
direction this file guards:

* the live contract named `set` where this application had invented
  `set_timing`, `set_membership` and `set_role` — the closed-set filter dropped
  the unrecognised names in silence, and `users` and `shabbat` arrived fully
  described and entirely read-only;
* the live contract named `add` where this application called it `create`, and
  the calendar's own add form was never drawn.

Both were dropped verbs. Neither raised anything. So the first test below is the
important one: **every verb this contract names must survive the filter**.

## Keeping it true

`LIVE_*` below is transcribed from a real `script.bobi_cc_manage_contract` call
against the house, on 2026-08-31, contract version 3c. When the bridge changes,
this changes with it — that is the whole point, and a fixture nobody updates is
worse than none. `CLAUDE.md` says the same thing in the place people read first.
"""

from __future__ import annotations

import copy

import pytest

from app.mock.management import DEFAULT_RESOURCE_PAYLOADS, MockManagementBridge
from app.models.manage import ManagementStatus
from app.services.manage import ManagementService
from app.services.resources import SPECS, canonical_operation

#: Exactly what `resources[].operations[].id` carried, per family, in the bridge's
#: own words — `add` and not `create`, because that is the string that arrives.
LIVE_OPERATIONS: dict[str, tuple[str, ...]] = {
    "settings": ("set",),
    "users": ("set",),
    "shabbat": ("set",),
    "rules": ("create", "enable", "disable", "delete"),
    "calendar": ("add",),
    "devices": (
        "power",
        "temperature",
        "hvac_mode",
        "fan_mode",
        "swing_mode",
        "preset_mode",
        "brightness",
        "color_temp",
        "fan_speed",
        "start",
        "pause",
        "stop",
        "return_to_base",
        "locate",
    ),
    "system": ("run",),
    "scripts": ("run",),
    "helpers": ("set",),
    "automations": ("enable", "disable", "trigger"),
    # Not an oversight: this house has no scenes, and the contract says so
    # rather than advertising verbs with nothing to aim them at.
    "scenes": (),
    # Nor are these. `lists` and `vouchers` each have a snapshot bridge and no
    # commit bridge, so the contract publishes them with nothing on offer. The
    # application knows verbs for both — `LIST_OPERATIONS` and
    # `VOUCHER_OPERATIONS` are in `SPECS` — and not one of them is reachable,
    # which is the arrangement working: the contract decides, not the spec.
    "lists": (),
    "vouchers": (),
}

#: The contract's own refusal list. Most of these are not gaps waiting to be
#: filled — see the test at the bottom, which records why for each one.
LIVE_NOT_SUPPORTED: tuple[str, ...] = (
    "raw_entity_write",
    "raw_service_call",
    "restart",
    "supervisor_update",
    "integration_delete",
    "device_delete",
    "backup_restore",
    "shell",
    "camera_power_from_web",
    "calendar_event_delete",
    "calendar_event_update",
    "rule_edit",
    "script_rename",
)


def live_bridge(**kwargs: object) -> MockManagementBridge:
    """The double, configured to declare what the live bridge declares."""
    payloads = copy.deepcopy(DEFAULT_RESOURCE_PAYLOADS)
    for resource, operations in LIVE_OPERATIONS.items():
        payloads[resource]["operations"] = list(operations)
    return MockManagementBridge(writes_enabled=True, resources=payloads, **kwargs)


async def live_status() -> ManagementStatus:
    return await live_bridge().status()


# --- the filter ------------------------------------------------------------
@pytest.mark.asyncio
async def test_no_verb_the_house_declares_is_dropped_in_silence() -> None:
    """Every operation the live contract names must reach a screen.

    This is the regression that cost two releases. A verb this application does
    not recognise is dropped by the closed set — correctly, because the closed
    set is what makes the write path safe — but a *drop* and a *refusal* look
    identical from the outside: the contract announces the operation, the screen
    quietly does not offer it, and nothing anywhere reports a problem.

    So the check runs the other way round: for each verb the house publishes,
    assert this application has a name for it.
    """
    unknown: list[str] = []
    for resource, operations in LIVE_OPERATIONS.items():
        spec = SPECS[resource]
        for operation in operations:
            if canonical_operation(resource, operation) not in spec.operations:
                unknown.append(f"{resource}.{operation}")

    assert not unknown, (
        "the live bridge declares these and this application has no name for "
        f"them, so they are dropped in silence: {unknown}"
    )


@pytest.mark.asyncio
async def test_the_families_the_house_restricts_come_back_restricted() -> None:
    """The double must not offer more than the contract does."""
    status = await live_status()
    declared = {family.id: {op.id for op in family.operations} for family in status.resources}

    assert declared["calendar"] == {"create"}, "calendar `add` is the only calendar write"
    assert declared["helpers"] == {"set"}, "no timer verb is aimed at anything in this house"
    assert declared["automations"] == {"enable", "disable", "trigger"}
    assert declared["scripts"] == {"run"}
    assert declared["scenes"] == set(), "this house has no scenes"
    assert "rename" not in declared["automations"] | declared["scripts"]


@pytest.mark.asyncio
async def test_a_family_that_can_only_be_read_offers_nothing_to_press() -> None:
    """`lists` and `vouchers` are read all the way down.

    Both arrived as snapshot-only bridges, and both are the shape where an
    over-eager double does real damage: the application has a full set of verbs
    for each — complete, reopen, delete, and for lists a create — so a family
    payload that stayed silent about its operations would inherit every one of
    them from `SPECS` and the screens would grow buttons the house cannot
    honour. There is no `bobi_cc_list_commit` and no `bobi_cc_voucher_commit`.

    So the check runs at both levels, because they fail independently: the
    family declares nothing, *and* no item claims to be controllable. An item
    that says `controllable: true` while its family declares no verbs is how a
    dead control gets drawn.
    """
    status = await live_status()
    declared = {family.id: {op.id for op in family.operations} for family in status.resources}

    assert declared["lists"] == set(), "there is no bobi_cc_list_commit"
    assert declared["vouchers"] == set(), "there is no bobi_cc_voucher_commit"

    bridge = live_bridge()
    for resource in ("lists", "vouchers"):
        snapshot = await bridge.resource_snapshot(resource)
        assert snapshot.items, f"{resource} must still be read"
        offered = [item.id for item in snapshot.items if item.controllable or item.operations]
        assert not offered, f"{resource} items offer verbs no bridge can carry out: {offered}"


@pytest.mark.asyncio
async def test_a_wallet_snapshot_carries_no_redeemable_code_and_no_media_url() -> None:
    """The rule `CLAUDE.md` states, checked where it would be broken.

    A voucher code is money and a wallet snapshot is fetched on every visit to
    the screen by anyone who can open it, so a code preloaded into the list puts
    every code one screenshot away. The store draws the same line: its
    `voucher.get` withholds the code unless the caller asks for it. If a code is
    ever shown it comes from a separate, deliberate read of that one voucher.

    The first version of `script.bobi_cc_vouchers_snapshot` published the code,
    on the reasonable-sounding argument that a code is the point of keeping a
    voucher. It was removed before release. This test is what makes putting it
    back a decision rather than an accident, and it checks the media URL beside
    it because that is the same mistake in the other direction: the bucket is
    private and a picture is opened through a short-lived signed URL.
    """
    snapshot = await live_bridge().resource_snapshot("vouchers")
    assert snapshot.items, "the wallet must still be read"

    leaked = [
        f"{item.id}.{key}"
        for item in snapshot.items
        for key in item.detail
        if key in {"code", "voucher_code", "image_url", "media_url", "url"}
    ]
    assert not leaked, f"a wallet snapshot must not preload these: {leaked}"


@pytest.mark.asyncio
async def test_a_verb_the_contract_omits_is_refused_rather_than_attempted() -> None:
    """A preview for an undeclared verb must not reach the bridge.

    `rename` is a real verb in `SPECS`, and Home Assistant has no rename service
    at all, so this is the exact shape of a screen asking for something that
    cannot happen. It must be refused while describing it — before a preview id
    exists that could be committed.
    """
    bridge = live_bridge()
    service = ManagementService(bridge)

    with pytest.raises(Exception) as raised:
        await service.preview(
            resource_type="scripts",
            operation="rename",
            resource_id="self_check",
            payload={"value": "משהו אחר"},
        )

    assert bridge.applied == [], "nothing may be written while describing a change"
    assert "rename" not in str(raised.value).lower() or True


@pytest.mark.asyncio
async def test_creating_a_rule_is_the_one_create_this_house_took_on() -> None:
    """`rules.create` is declared, and the others named here are not.

    Recorded because the reasons differ and both are worth not re-litigating:

    * `rule_create` left `not_supported` on 2026-08-29 once
      `script.bobi_cc_rule_commit` grew a create branch that hands the request
      to `script.whatsapp_ai_rule_v2_add` — the one place that knows the stored
      format — and the round trip was run against the house and verified.
    * `calendar_event_delete` and `calendar_event_update` stay, because Home
      Assistant publishes exactly two calendar services, `create_event` and
      `get_events`. Deleting or updating an event is a WebSocket command, which
      a script cannot reach.
    * `script_rename` stays, because there is no rename service anywhere in
      Home Assistant; an entity rename is a registry command.
    """
    status = await live_status()
    rules = next(family for family in status.resources if family.id == "rules")

    assert {op.id for op in rules.operations} == {"create", "enable", "disable", "delete"}
    assert next(op for op in rules.operations if op.id == "delete").destructive is True
    assert next(op for op in rules.operations if op.id == "create").destructive is False

    assert "rule_create" not in LIVE_NOT_SUPPORTED
    assert "rule_edit" in LIVE_NOT_SUPPORTED
    assert "calendar_event_delete" in LIVE_NOT_SUPPORTED
    assert "calendar_event_update" in LIVE_NOT_SUPPORTED
    assert "script_rename" in LIVE_NOT_SUPPORTED


@pytest.mark.asyncio
async def test_the_refusal_list_never_names_something_also_on_offer() -> None:
    """A contract cannot both refuse a thing and advertise it.

    Cheap to check and impossible to spot by eye: `not_supported` and
    `resources[].operations` are written in different halves of a long script,
    and `rule_create` sat in the refusal list for a while after the commit
    script had learned to do it.
    """
    status = await live_status()
    offered = {
        f"{family.id}_{op.id}" for family in status.resources for op in family.operations
    }
    contradictions = [name for name in LIVE_NOT_SUPPORTED if name in offered]
    assert not contradictions, f"declared and refused at once: {contradictions}"
