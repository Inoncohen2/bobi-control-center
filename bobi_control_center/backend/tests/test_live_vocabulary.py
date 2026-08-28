"""The verbs Home Assistant actually declares, and the rules that survive them.

Connecting to the live house exposed a fault that no fixture had: three
families came back from `bobi_cc_*_snapshot` fully described — labels, values,
kinds, limits, `controllable: true` — and entirely read-only, because the verb
each one declared was not a verb this application knew.

| family    | the bridge declares            | this application expected            |
|-----------|--------------------------------|--------------------------------------|
| `users`   | `set`                          | `enable`/`disable`/`set_role`/…       |
| `shabbat` | `set`                          | `set_timing`/`set_membership`/…       |
| `devices` | `power`, `temperature`, …      | `set`                                 |

Home Assistant's model is the simpler one, and it was right: a family is a list
of items each holding a value, and one verb per capability says what may be done
to it. The granular names were this application's idea. Both vocabularies are
accepted now, and the interesting half of that is what did **not** change —
every refusal that used to key off a verb name now reads the payload instead, so
the same change meets the same answer under the name the live bridge uses.

The double speaks the live vocabulary too. A test double that only ever said
`set` is exactly what let this reach a real house undetected.
"""

from __future__ import annotations

import pytest

from app.errors import ValidationError
from app.mock.management import PRIVATE_CANARY, MockManagementBridge
from app.models.manage import (
    CommitRequest,
    ManagedOperation,
    ObservedState,
    PreviewRequest,
)
from app.services.manage import ManagementService
from app.services.resources import DEVICE_OPERATIONS, SPECS
from app.services.roles import Actor, Role

OWNER = Actor(role=Role.OWNER, source="ingress")


def bridge(**kwargs) -> MockManagementBridge:
    kwargs.setdefault("writes_enabled", True)
    return MockManagementBridge(**kwargs)


def service(**kwargs) -> ManagementService:
    return ManagementService(bridge(**kwargs), default_actor=OWNER)


async def preview(svc: ManagementService, resource: str, operation: str, **kwargs):
    return await svc.preview(resource, PreviewRequest(operation=operation, **kwargs))


async def commit(svc: ManagementService, resource: str, response, **kwargs):
    return await svc.commit(
        resource, CommitRequest(preview_id=response.preview_id, confirmed=True, **kwargs)
    )


def codes(response) -> list[str]:
    return [error.code for error in response.errors]


# --- the verb every family understands --------------------------------------
@pytest.mark.parametrize("resource", ["settings", "users", "shabbat", "devices"])
def test_set_is_declared_by_every_family_the_live_house_uses_it_on(resource) -> None:
    """The regression itself, pinned at the vocabulary level.

    Dropping `set` from any of these puts that family back where the live
    contract found it: described, marked controllable, and with no operation
    the application would accept.
    """
    assert "set" in SPECS[resource].operations


async def test_a_user_can_be_switched_off_under_the_bridges_own_verb() -> None:
    response = await preview(
        service(), "users", "set", resource_id="user_2", payload={"value": False}
    )

    assert response.valid is True, codes(response)


async def test_a_shabbat_row_can_be_saved_under_the_bridges_own_verb() -> None:
    response = await preview(
        service(), "shabbat", "set", resource_id="pre_shabbat_offset_minutes",
        payload={"value": 45},
    )

    assert response.valid is True, codes(response)


async def test_the_shabbat_promise_holds_under_the_new_verb() -> None:
    """Still a schedule edit, and the dialog still says so before anyone saves."""
    response = await preview(
        service(), "shabbat", "set", resource_id="pre_shabbat_offset_minutes",
        payload={"value": 45},
    )

    assert response.explanation is not None
    assert "לוח הזמנים" in response.explanation
    assert "שום מכשיר" in response.explanation


async def test_the_published_limits_are_still_enforced_under_set() -> None:
    response = await preview(
        service(), "shabbat", "set", resource_id="pre_shabbat_offset_minutes",
        payload={"value": 200},
    )

    assert codes(response) == ["too_high"]


# --- the last admin, under the name the bridge uses --------------------------
async def test_switching_off_the_last_admin_is_refused_under_set() -> None:
    """The guard used to key off `disable`. Under the live vocabulary that verb
    never arrives, and the identical change would have gone straight through."""
    response = await preview(
        service(), "users", "set", resource_id="user_1", payload={"value": False}
    )

    assert codes(response) == ["last_admin"]


async def test_demoting_the_last_admin_is_refused_under_set() -> None:
    response = await preview(
        service(), "users", "set", resource_id="user_1", payload={"role": "member"}
    )

    assert codes(response) == ["last_admin"]


async def test_set_that_keeps_the_admin_role_is_allowed() -> None:
    """The guard refuses the removal, not the verb."""
    response = await preview(
        service(), "users", "set", resource_id="user_1", payload={"role": "admin"}
    )

    assert response.valid is True, codes(response)


async def test_switching_on_the_last_admin_is_not_a_removal() -> None:
    response = await preview(
        service(), "users", "set", resource_id="user_1", payload={"value": True}
    )

    assert response.valid is True, codes(response)


async def test_an_admin_may_be_switched_off_when_another_one_remains() -> None:
    holder = bridge()
    holder._raw_item("users", "user_2")["role"] = "admin"
    svc = ManagementService(holder, default_actor=OWNER)

    response = await preview(svc, "users", "set", resource_id="user_1", payload={"value": False})

    assert response.valid is True, codes(response)


async def test_a_set_carrying_no_role_and_no_value_is_not_treated_as_a_removal() -> None:
    """A rename is a `set` too. Refusing it would be the guard misfiring."""
    response = await preview(
        service(), "users", "set", resource_id="user_1", payload={"name": "ינון כהן"}
    )

    assert response.valid is True, codes(response)


# --- the phone door, under the name the bridge uses --------------------------
async def test_a_phone_number_still_reaches_the_bridge_under_set() -> None:
    holder = bridge()
    svc = ManagementService(holder, default_actor=OWNER)

    response = await preview(
        svc, "users", "set", resource_id="user_2", payload={"phone": "0000000000"}
    )

    assert response.valid is True, codes(response)
    await commit(svc, "users", response, confirm_word=response.confirm_word)
    assert holder.applied[-1]["payload"]["phone"] == "0000000000"


async def test_a_phone_number_is_still_neither_shown_nor_recorded_under_set() -> None:
    svc = service()
    response = await preview(
        svc, "users", "set", resource_id="user_2", payload={"phone": "0000000000"}
    )

    assert "0000000000" not in response.model_dump_json()
    # Sensitive because of what it carries, not because of what it is called.
    assert response.risk == "high"
    assert response.confirm_word

    await commit(svc, "users", response, confirm_word=response.confirm_word)
    blob = svc.audit(limit=50).model_dump_json()
    assert "0000000000" not in blob
    assert PRIVATE_CANARY not in blob


async def test_no_other_private_field_rides_in_on_set() -> None:
    """One door, one field. `set` does not widen it."""
    holder = bridge()
    svc = ManagementService(holder, default_actor=OWNER)

    response = await preview(
        svc, "users", "set", resource_id="user_2",
        payload={"phone": "0000000000", "lid": PRIVATE_CANARY, "token": "secret"},
    )
    await commit(svc, "users", response, confirm_word=response.confirm_word)

    sent = holder.applied[-1]["payload"]
    assert sent["phone"] == "0000000000"
    assert "lid" not in sent
    assert "token" not in sent


# --- one verb per device capability ------------------------------------------
@pytest.mark.parametrize(
    "operation", ["power", "temperature", "fan_mode", "swing_mode", "brightness"]
)
def test_the_capability_verbs_are_declared(operation) -> None:
    assert operation in DEVICE_OPERATIONS


async def test_a_device_that_names_its_capabilities_is_operable() -> None:
    response = await preview(
        service(), "devices", "power", resource_id="ac_parents", payload={"value": True}
    )

    assert response.valid is True, codes(response)
    assert response.title.startswith("הדלקה או כיבוי")


async def test_the_capability_verb_reaches_the_bridge_unchanged() -> None:
    holder = bridge()
    svc = ManagementService(holder, default_actor=OWNER)

    response = await preview(
        svc, "devices", "temperature", resource_id="ac_parents", payload={"value": 25}
    )
    await commit(svc, "devices", response)

    assert holder.applied[-1]["operation"] == "temperature"
    assert holder.applied[-1]["payload"]["value"] == 25
    # And the token still travels with it, which is what 2.2.1 exists for.
    assert holder.applied[-1]["preview_token"]


async def test_limits_are_enforced_under_a_capability_verb() -> None:
    response = await preview(
        service(), "devices", "temperature", resource_id="ac_parents", payload={"value": 40}
    )

    assert codes(response) == ["too_high"]


async def test_a_switch_verb_is_not_checked_against_the_items_own_limits() -> None:
    """`ac_parents` publishes a temperature range, because temperature is the
    value it reports. `power: true` is not a temperature, and checking it
    against °C limits produced "the value must be a number" — the check being
    wrong about the request rather than the request being wrong."""
    response = await preview(
        service(), "devices", "power", resource_id="ac_parents", payload={"value": True}
    )

    assert response.valid is True, codes(response)


async def test_a_switch_verb_is_still_checked_against_what_a_switch_can_hold() -> None:
    """Not validating against the wrong thing is not the same as not validating."""
    response = await preview(
        service(), "devices", "power", resource_id="ac_parents", payload={"value": 24}
    )

    assert codes(response) == ["invalid"]


async def test_a_capability_the_bridge_did_not_name_on_this_device_is_refused() -> None:
    """`brightness` is a verb this application knows. That is not the question:
    the question is whether the bridge offered it *on this item*."""
    response = await preview(
        service(), "devices", "brightness", resource_id="ac_parents", payload={"value": 50}
    )

    assert codes(response) == ["not_controllable"]


async def test_a_verb_outside_the_closed_set_is_refused_even_if_the_bridge_offers_it() -> None:
    """The set is closed on this side too. A bridge cannot widen it by declaring
    something — that is the whole reason it is a list rather than a pass-through.

    The refusal lands at the contract gate, before a description exists, so the
    verb never gets as far as having a preview that could hold a token.
    """
    payload = {
        "available": True,
        "items": [
            {
                "id": "odd",
                "label": "משהו",
                "kind": "toggle",
                "value": False,
                "controllable": True,
                "operations": ["detonate"],
            }
        ],
    }
    assert "detonate" not in DEVICE_OPERATIONS

    with pytest.raises(ValidationError):
        await preview(
            service(resources={"devices": payload}),
            "devices",
            "detonate",
            resource_id="odd",
            payload={"value": True},
        )


async def test_an_uncontrollable_device_is_still_refused_under_a_capability_verb() -> None:
    response = await preview(
        service(), "devices", "power", resource_id="cam_lia", payload={"value": True}
    )

    assert codes(response) == ["not_controllable"]


async def test_every_capability_verb_has_a_hebrew_title() -> None:
    """A verb with no title falls back to "שינוי במכשירים", which tells a person
    nothing about what they are confirming."""
    titles = SPECS["devices"].titles
    for operation in DEVICE_OPERATIONS:
        assert titles.get(operation), operation


# --- which verb a screen actually sends --------------------------------------
def normalized(item: dict) -> object:
    from app.services.resource_normalize import normalize_resource

    return normalize_resource("devices", {"available": True, "items": [item]}).items[0]


def test_the_verb_that_sets_the_reported_value_is_the_one_chosen() -> None:
    """The bug this field exists for: an air conditioner reports a temperature
    and accepts four verbs, `power` first. Taking the first name in the list
    would send `power` when someone drags the temperature — the wrong change,
    previewed honestly, confirmed by a person who read a correct dialog."""
    item = normalized(
        {
            "id": "ac",
            "label": "מזגן",
            "kind": "number",
            "value": 23,
            "controllable": True,
            "operations": ["power", "temperature", "fan_mode"],
        }
    )

    assert item.primary_operation == "temperature"


def test_a_toggle_picks_the_verb_that_reverses_its_current_state() -> None:
    for value, expected in ((True, "disable"), (False, "enable")):
        item = normalized(
            {
                "id": "lamp",
                "label": "מנורה",
                "kind": "toggle",
                "value": value,
                "controllable": True,
                "operations": ["enable", "disable"],
            }
        )
        assert item.primary_operation == expected, value


def test_a_toggle_that_only_knows_power_uses_power() -> None:
    item = normalized(
        {
            "id": "socket",
            "label": "שקע",
            "kind": "toggle",
            "value": False,
            "controllable": True,
            "operations": ["power"],
        }
    )

    assert item.primary_operation == "power"


def test_set_wins_wherever_the_bridge_declares_it() -> None:
    item = normalized(
        {
            "id": "thing",
            "label": "משהו",
            "kind": "number",
            "value": 5,
            "controllable": True,
            "operations": ["power", "set", "temperature"],
        }
    )

    assert item.primary_operation == "set"


def test_an_item_the_bridge_did_not_mark_controllable_has_no_verb() -> None:
    """Fail closed here too: `primary_operation` is what a screen sends, so an
    item that may not be operated must not carry one."""
    item = normalized(
        {
            "id": "cam",
            "label": "מצלמה",
            "kind": "readonly",
            "value": "streaming",
            "operations": ["power"],
        }
    )

    assert item.controllable is False
    assert item.primary_operation is None


def test_a_vacuum_picks_the_verb_that_reverses_what_it_is_doing() -> None:
    """The one device whose on and off are two verbs rather than a verb and a
    value. Cleaning offers `stop`; docked offers `start`."""
    for value, expected in ((True, "stop"), (False, "start")):
        item = normalized(
            {
                "id": "robi",
                "label": "רובי",
                "kind": "toggle",
                "value": value,
                "controllable": True,
                "operations": ["start", "stop", "pause", "return_to_base", "locate"],
            }
        )
        assert item.primary_operation == expected, value


# --- the choices a bridge publishes ------------------------------------------
def test_a_bare_list_of_choices_is_understood() -> None:
    """`hvac_modes`, `fan_modes` and `preset_modes` are plain string lists in
    Home Assistant, so that is what a bridge sends. They used to be dropped
    whole: a choice control with nothing to choose from."""
    item = normalized(
        {
            "id": "ac_hvac_mode",
            "label": "מצב",
            "kind": "choice",
            "value": "cool",
            "controllable": True,
            "operations": ["hvac_mode"],
            "options": ["off", "auto", "cool", "dry", "heat", "fan_only"],
        }
    )

    assert [option.value for option in item.options] == [
        "off", "auto", "cool", "dry", "heat", "fan_only",
    ]
    assert item.options[2].label == "cool"


def test_the_documented_shape_still_works() -> None:
    item = normalized(
        {
            "id": "policy",
            "label": "מדיניות",
            "kind": "choice",
            "value": "always",
            "controllable": True,
            "operations": ["set"],
            "options": [{"value": "always", "label": "תמיד"}],
        }
    )

    assert [(o.value, o.label) for o in item.options] == [("always", "תמיד")]


async def test_a_value_outside_a_bare_list_of_choices_is_refused() -> None:
    """The options are only worth reading if they are then enforced."""
    payload = {
        "available": True,
        "items": [
            {
                "id": "ac_hvac_mode",
                "label": "מצב",
                "kind": "choice",
                "value": "cool",
                "controllable": True,
                "operations": ["hvac_mode"],
                "options": ["off", "cool", "heat"],
            }
        ],
    }
    svc = service(resources={"devices": payload})

    good = await preview(
        svc, "devices", "hvac_mode", resource_id="ac_hvac_mode", payload={"value": "heat"}
    )
    bad = await preview(
        svc, "devices", "hvac_mode", resource_id="ac_hvac_mode", payload={"value": "boil"}
    )

    assert good.valid is True, codes(good)
    assert codes(bad) == ["not_allowed"]


# --- what the Home Assistant side is told ------------------------------------
def test_the_published_contract_carries_the_live_vocabulary() -> None:
    from app.services.bridge_contract import all_services

    devices = next(
        service for service in all_services()
        if service.name == "bobi_cc_device_commit"
    )
    assert "power" in devices.operations
    assert "temperature" in devices.operations

    users = next(
        service for service in all_services() if service.name == "bobi_cc_users_commit"
    )
    # Rated as the most sensitive thing it can turn out to be, so the other
    # side mirrors this judgement rather than inventing a milder one.
    assert users.operation_risk["set"] == "high"


# --- the name the target arrives under ---------------------------------------
@pytest.mark.parametrize(
    ("resource", "operation", "item", "wanted"),
    [
        ("users", "set", "user_2", False),
        ("shabbat", "set", "pre_shabbat_offset_minutes", 45),
        ("devices", "set", "kitchen", True),
        ("settings", "set", "morning_enabled", False),
    ],
)
async def test_the_target_is_sent_under_both_names(resource, operation, item, wanted) -> None:
    """Every commit carries its target twice: once under the family's own field
    name and once as `resource_id`.

    This side names the field per family — `user_id`, `profile_id`, `helper_id`
    — and five of the six live bridges read `resource_id`. The field each one
    reads arrived undefined, so the commit was refused as
    `invalid_commit_request`: nothing written, and nothing to distinguish it
    from a bridge legitimately declining the change.
    """
    from app.adapters.real_management import RealManagementBridge
    from app.services.resources import SPECS

    sent: dict[str, object] = {}

    class Recorder(RealManagementBridge):
        async def _payload(self, service, data=None):  # type: ignore[override]
            sent.update(data or {})
            return {"executed": True, "verified": True, "reason": "ok"}

    holder = bridge()
    svc = ManagementService(holder, default_actor=OWNER)
    response = await preview(
        svc, resource, operation, resource_id=item, payload={"value": wanted}
    )
    assert response.valid is True, codes(response)

    recorder = Recorder.__new__(Recorder)
    await recorder._apply_resource(
        resource,
        operation,
        item,
        {"value": wanted},
        ObservedState(resource_id=item, label=item, values={"value": wanted}),
        "req_1",
        "pt_test_token_value",
    )

    assert sent["resource_id"] == item
    assert sent[SPECS[resource].id_field] == item


# --- a thing you run, not a value you set ------------------------------------
def test_action_is_a_kind_of_its_own() -> None:
    """The live system bridge sends `kind: "action"` with no value, and every
    other kind in the contract assumes an item *is* a value. Without this the
    kind fell through to `readonly` and both safe checks became readings."""
    from app.services.resource_normalize import canonical_kind

    assert canonical_kind("action", None, []) == "action"


def test_an_action_is_never_inferred() -> None:
    """Only a bridge saying `action` produces one. A value this application
    cannot recognise is still a reading, not a button that does something."""
    from app.services.resource_normalize import canonical_kind

    assert canonical_kind(None, None, []) == "readonly"
    assert canonical_kind(None, "ready", []) == "readonly"


async def test_a_valueless_action_is_still_operable() -> None:
    """Everywhere else a missing value means the bridge could not read the item
    and it must not be written. An action has no value to miss."""
    snapshot = await service().resource_snapshot("system")
    check = next(item for item in snapshot.items if item.id == "self_check")

    assert check.kind == "action"
    assert check.value is None
    assert check.controllable is True
    assert check.primary_operation == "run"


async def test_running_a_safe_check_previews() -> None:
    response = await preview(service(), "system", "run", resource_id="self_check")

    assert response.valid is True, codes(response)


async def test_a_forbidden_system_action_is_still_refused() -> None:
    """The kind is new; the refusal it must not weaken is not. Checked before a
    preview exists, so a forbidden action never gets as far as holding a token.
    """
    from app.services.resources import is_forbidden_system_action

    for action in ("restart", "core_restart", "supervisor_update", "backup_restore", "shell"):
        assert is_forbidden_system_action(action), action


# --- which verbs a screen may put on a button -------------------------------
async def test_the_contract_says_which_verbs_take_no_payload() -> None:
    """A screen cannot tell `activate` from `rename` by looking at them.

    Both arrive as an id and a Hebrew label, and only this side knows that one
    of them is a complete request on its own. Publishing the arity is what lets
    the scenes screen draw an "הפעלת סצנה" button without knowing what a scene
    is — and what stopped it drawing a "שינוי שם" button that would send a
    rename with no name in it.
    """
    status = await MockManagementBridge(writes_enabled=True).status()
    verbs = {
        resource.id: {operation.id: operation.valueless for operation in resource.operations}
        for resource in status.resources
    }

    assert verbs["scenes"] == {"activate": True, "rename": False}
    assert verbs["scripts"] == {"run": True, "rename": False}
    assert verbs["automations"]["trigger"] is True
    assert verbs["automations"]["rename"] is False
    assert verbs["helpers"]["start"] is True
    assert verbs["helpers"]["set"] is False
    assert verbs["rules"]["edit"] is False


def test_a_verb_nobody_classified_is_assumed_to_need_a_value() -> None:
    """Fail closed: an unclassified verb gets no one-tap button."""
    assert ManagedOperation(id="frobnicate", label="פ").valueless is False


# --- what the control for a kind does not already send -----------------------
async def test_a_vacuum_keeps_the_verbs_its_switch_cannot_express() -> None:
    """The busiest row the live vocabulary produces.

    A vacuum publishes a switch and five verbs that take no payload. Four of
    those — power, start, stop, and whichever of them the switch picked — are
    the switch. Pause, return-to-base and locate are not, and they are the ones
    a screen has to offer or lose.
    """
    snapshot = await service().resource_snapshot("devices")
    vacuum = next(item for item in snapshot.items if item.id == "vacuum")

    assert vacuum.kind == "toggle"
    assert vacuum.primary_operation == "power"
    assert vacuum.run_operations == ["pause", "return_to_base", "locate"]


async def test_a_switch_leaves_no_button_that_would_repeat_it() -> None:
    """Both halves of a switch, not just the half it happens to be showing.

    `primary_operation` picks `disable` for an enabled automation and `enable`
    for a disabled one. Excluding only what it picked would leave the other
    half beside it as a button: a switch that is on, and an "enable" button.
    """
    snapshot = await service().resource_snapshot("automations")
    enabled = next(item for item in snapshot.items if item.value is True)
    disabled = next(item for item in snapshot.items if item.value is False)

    assert enabled.primary_operation == "disable"
    assert enabled.run_operations == ["trigger"]
    assert disabled.primary_operation == "enable"
    assert disabled.run_operations == ["trigger"]


async def test_a_reading_keeps_every_verb_because_nothing_else_sends_one() -> None:
    scenes = await service().resource_snapshot("scenes")
    scene = scenes.items[0]

    assert scene.kind == "readonly"
    assert scene.run_operations == ["activate"]


async def test_an_item_the_bridge_locked_gets_no_run_verbs() -> None:
    """Fail closed here too: `controllable: false` empties the list."""
    cameras = await service().resource_snapshot("devices")
    camera = next(item for item in cameras.items if item.id == "cam_lia")

    assert camera.controllable is False
    assert camera.run_operations == []


async def test_a_status_reading_is_never_guessed_into_a_switch() -> None:
    """The live system snapshot publishes `kind: "status"` for its health rows.

    `status` is not a kind this application has, so it fell through to being
    inferred from the value — and `bobi_health: true` inferred as a *toggle*.
    Every one of those rows is `controllable: false` today, so nothing was
    drawn; but a health readout guessed to be a switch is one `controllable`
    away from a control that reports the house's health and pretends to set it.
    """
    from app.services.resource_normalize import canonical_kind

    assert canonical_kind("status", True, []) == "readonly"
    assert canonical_kind("status", "WORKING", []) == "readonly"
    # And the guess is still made where the bridge genuinely said nothing.
    assert canonical_kind(None, True, []) == "toggle"
