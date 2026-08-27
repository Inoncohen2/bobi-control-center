"""The 3.0 families: what they may do, and — mostly — what they may not.

The write flow itself is covered by `test_manage.py` and does not change here.
What changes is that seven more families use it, each described by a bridge
rather than by this application, so these tests hold two lines:

* **Discovery is authoritative.** A family the contract does not name is
  unavailable; an item the bridge did not mark controllable gets no write; a
  capability it did not advertise is refused; a limit it published is enforced.
* **Four rules are ours regardless.** The last admin, the masked phone, the
  Shabbat profile that touches no device, and the system actions no web page may
  start. Each is checked before a preview exists, so a refusal never becomes a
  token something else could commit.
"""

from __future__ import annotations

import json

import pytest

from app.mock.management import DEFAULT_RESOURCE_PAYLOADS, PRIVATE_CANARY, MockManagementBridge
from app.models.manage import CommitRequest, PreviewRequest
from app.services.manage import ManagementService, ManagementUnavailableError, WritesDisabledError
from app.services.resources import SPECS
from app.services.roles import Actor, Role

#: These tests exercise the write flow, not the permission model, so the service
#: is built with an owner as its default actor. The application's own default is
#: a viewer — the weakest role — so a route that ever forgot to say who is
#: asking would be able to read and nothing else.
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


# --- discovery --------------------------------------------------------------
@pytest.mark.parametrize("resource", sorted(set(SPECS) - {"tasks", "features"}))
async def test_every_family_reports_a_snapshot(resource) -> None:
    snapshot = await service().resource_snapshot(resource)

    assert snapshot.resource == resource
    assert snapshot.available is True
    assert snapshot.items, "a family the double holds should report items"


@pytest.mark.parametrize("resource", sorted(set(SPECS) - {"tasks", "features"}))
async def test_a_family_whose_bridge_has_not_shipped_is_unavailable(resource) -> None:
    """The answer is "not in Home Assistant yet", not an error and not a guess."""
    held_back = {name: payload for name, payload in DEFAULT_RESOURCE_PAYLOADS.items()
                 if name != resource}
    snapshot = await service(resources=held_back).resource_snapshot(resource)

    assert snapshot.available is False
    assert snapshot.reason
    assert snapshot.items == []


async def test_without_a_bridge_every_family_fails_closed() -> None:
    svc = ManagementService(None, default_actor=OWNER)

    for resource in sorted(set(SPECS) - {"tasks", "features"}):
        snapshot = await svc.resource_snapshot(resource)
        assert snapshot.available is False
        with pytest.raises(ManagementUnavailableError):
            await preview(svc, resource, "set", resource_id="anything")


async def test_a_family_the_contract_does_not_name_cannot_be_previewed() -> None:
    """Holding the data back is not the only way a family can be missing."""
    svc = service(resources={"settings": DEFAULT_RESOURCE_PAYLOADS["settings"]})

    with pytest.raises(ManagementUnavailableError):
        await preview(svc, "devices", "set", resource_id="kitchen", payload={"value": True})


async def test_writes_off_previews_but_refuses_to_commit() -> None:
    svc = service(writes_enabled=False)
    response = await preview(
        svc, "settings", "set", resource_id="morning_time", payload={"value": "08:00"}
    )

    assert response.valid is True
    with pytest.raises(WritesDisabledError):
        await commit(svc, "settings", response)


# --- previews write nothing -------------------------------------------------
@pytest.mark.parametrize(
    ("resource", "operation", "resource_id", "payload"),
    [
        ("settings", "set", "morning_enabled", {"value": False}),
        ("users", "rename", "user_2", {"name": "הודיה כהן"}),
        ("shabbat", "set_timing", "pre_shabbat_offset_minutes", {"value": 45}),
        ("rules", "disable", "rule_1", {}),
        ("calendar", "edit", "evt_1", {"location": "בית"}),
        ("devices", "set", "kitchen", {"value": True}),
        ("system", "run", "self_check", {}),
    ],
)
async def test_preview_performs_no_write(resource, operation, resource_id, payload) -> None:
    holder = bridge()
    svc = ManagementService(holder, default_actor=OWNER)

    await preview(svc, resource, operation, resource_id=resource_id, payload=payload)

    assert holder.applied == []


# --- the token, on every family ---------------------------------------------
@pytest.mark.parametrize(
    ("resource", "operation", "resource_id"),
    [
        ("settings", "set", "morning_enabled"),
        ("users", "rename", "user_2"),
        ("shabbat", "set_timing", "alert_enabled"),
        ("rules", "disable", "rule_1"),
        ("devices", "set", "kitchen"),
    ],
)
async def test_every_family_sends_a_non_empty_preview_token(
    resource, operation, resource_id
) -> None:
    holder = bridge()
    svc = ManagementService(holder, default_actor=OWNER)
    payload = {"name": "שם"} if operation == "rename" else {"value": False}

    response = await preview(svc, resource, operation, resource_id=resource_id, payload=payload)
    assert response.valid, [error.message for error in response.errors]
    await commit(svc, resource, response)

    sent = holder.applied[-1]["preview_token"]
    assert sent
    assert sent.startswith("pt_")


async def test_the_expected_state_travels_with_the_commit() -> None:
    holder = bridge()
    svc = ManagementService(holder, default_actor=OWNER)

    response = await preview(
        svc, "settings", "set", resource_id="ai_monthly_cap", payload={"value": 25}
    )
    await commit(svc, "settings", response)

    # What the preview observed, not what the client sent.
    assert holder.applied[-1]["observed"]["value"] == 20


async def test_a_stale_family_commit_is_reported_and_not_retried() -> None:
    holder = bridge()
    svc = ManagementService(holder, default_actor=OWNER)
    response = await preview(
        svc, "settings", "set", resource_id="morning_time", payload={"value": "08:00"}
    )

    # Someone else changed it between the preview and the commit.
    holder._raw_item("settings", "morning_time")["value"] = "09:00"
    result = await commit(svc, "settings", response)

    assert result.result.status == "failed"
    assert result.result.reason == "stale_preview"
    assert len(holder.applied) == 1, "a stale write must not be retried"


# --- fail closed on what the bridge did not offer ---------------------------
async def test_an_item_the_bridge_did_not_mark_controllable_is_refused() -> None:
    response = await preview(
        service(), "devices", "set", resource_id="cam_lia", payload={"value": True}
    )

    assert response.valid is False
    assert codes(response) == ["not_controllable"]


async def test_a_capability_the_bridge_did_not_advertise_is_refused() -> None:
    response = await preview(
        service(),
        "devices",
        "set",
        resource_id="ac_salon",
        payload={"value": 22, "capability": "colour"},
    )

    assert codes(response) == ["unsupported_capability"]


async def test_an_advertised_capability_is_accepted() -> None:
    response = await preview(
        service(),
        "devices",
        "set",
        resource_id="ac_salon",
        payload={"value": 22, "capability": "temperature"},
    )

    assert response.valid is True


@pytest.mark.parametrize(
    ("value", "code"),
    [(10, "too_low"), (40, "too_high"), (22.5, "bad_step")],
)
async def test_published_limits_are_enforced(value, code) -> None:
    response = await preview(
        service(), "devices", "set", resource_id="ac_salon", payload={"value": value}
    )

    assert codes(response) == [code]


async def test_a_choice_outside_the_published_options_is_refused() -> None:
    response = await preview(
        service(),
        "settings",
        "set",
        resource_id="home_status_policy",
        payload={"value": "whenever"},
    )

    assert codes(response) == ["not_allowed"]


async def test_an_operation_outside_the_family_is_refused() -> None:
    """Refused by the contract check, before a describer is ever reached.

    A 422 rather than an invalid preview: an operation the family does not have
    is a malformed request, not a change someone might fix and retry.
    """
    from app.errors import ValidationError

    holder = bridge()
    svc = ManagementService(holder, default_actor=OWNER)

    with pytest.raises(ValidationError):
        await preview(svc, "settings", "delete", resource_id="morning_enabled", payload={})
    assert holder.applied == []


# --- users ------------------------------------------------------------------
async def test_the_last_enabled_admin_cannot_be_disabled() -> None:
    holder = bridge()
    svc = ManagementService(holder, default_actor=OWNER)

    response = await preview(svc, "users", "disable", resource_id="user_1")

    assert codes(response) == ["last_admin"]
    assert holder.applied == []


async def test_the_last_enabled_admin_cannot_be_demoted() -> None:
    response = await preview(
        service(), "users", "set_role", resource_id="user_1", payload={"role": "member"}
    )

    assert codes(response) == ["last_admin"]


async def test_an_admin_can_be_disabled_when_another_one_remains() -> None:
    holder = bridge()
    holder._raw_item("users", "user_2")["role"] = "admin"
    svc = ManagementService(holder, default_actor=OWNER)

    response = await preview(svc, "users", "disable", resource_id="user_1")

    assert response.valid is True


async def test_a_non_admin_is_not_protected_by_the_invariant() -> None:
    response = await preview(service(), "users", "disable", resource_id="user_2")

    assert response.valid is True


async def test_no_phone_number_or_lid_reaches_a_snapshot() -> None:
    snapshot = await service().resource_snapshot("users")

    blob = snapshot.model_dump_json()
    assert PRIVATE_CANARY not in blob
    assert "lid" not in json.loads(blob)["items"][0]["detail"]
    # The masked form is what a screen gets instead.
    assert snapshot.items[0].detail["phone_masked"]


async def test_a_new_phone_number_reaches_the_bridge_but_not_the_preview() -> None:
    """The one field allowed through, and it is still not shown or recorded."""
    holder = bridge()
    svc = ManagementService(holder, default_actor=OWNER)

    response = await preview(
        svc, "users", "set_phone", resource_id="user_2", payload={"phone": "0000000000"}
    )
    assert response.valid is True
    # Shown masked in the dialog, never whole.
    assert "0000000000" not in response.model_dump_json()
    # And it is a sensitive change, so a word has to be typed.
    assert response.confirm_word

    await commit(svc, "users", response, confirm_word=response.confirm_word)
    assert holder.applied[-1]["payload"]["phone"] == "0000000000"


async def test_the_audit_line_for_a_phone_change_carries_no_number() -> None:
    svc = service()
    response = await preview(
        svc, "users", "set_phone", resource_id="user_2", payload={"phone": "0000000000"}
    )
    await commit(svc, "users", response, confirm_word=response.confirm_word)

    assert "0000000000" not in svc.audit(limit=50).model_dump_json()


# --- shabbat ----------------------------------------------------------------
async def test_saving_a_shabbat_profile_says_no_device_is_touched() -> None:
    response = await preview(
        service(),
        "shabbat",
        "set_membership",
        resource_id="pre_on",
        payload={"value": ["kitchen", "salon"]},
    )

    assert response.valid is True
    assert "לוח הזמנים" in (response.explanation or "")
    assert "לא יידלק" in (response.explanation or "")


async def test_a_device_outside_the_profile_list_is_refused() -> None:
    response = await preview(
        service(),
        "shabbat",
        "set_membership",
        resource_id="pre_on",
        payload={"value": ["kitchen", "the_neighbours_boiler"]},
    )

    assert codes(response) == ["not_allowed"]


async def test_shabbat_ac_temperatures_respect_the_published_range() -> None:
    too_hot = await preview(
        service(), "shabbat", "set_temperature", resource_id="ac_salon_temperature",
        payload={"value": 31},
    )
    fine = await preview(
        service(), "shabbat", "set_temperature", resource_id="ac_salon_temperature",
        payload={"value": 25},
    )

    assert codes(too_hot) == ["too_high"]
    assert fine.valid is True


async def test_a_shabbat_commit_does_not_reach_a_device_service() -> None:
    holder = bridge()
    svc = ManagementService(holder, default_actor=OWNER)
    response = await preview(
        svc, "shabbat", "set_timing", resource_id="night_off_time", payload={"value": "23:00"}
    )
    await commit(svc, "shabbat", response)

    assert [entry["resource_type"] for entry in holder.applied] == ["shabbat"]


# --- rules ------------------------------------------------------------------
async def test_a_blocking_conflict_refuses_the_change() -> None:
    holder = bridge()
    holder._raw_item("rules", "rule_1")["conflicts"] = [
        {"blocking": True, "message": "כבר יש כלל שמדליק את הדוד באותה שעה"}
    ]
    svc = ManagementService(holder, default_actor=OWNER)

    response = await preview(svc, "rules", "disable", resource_id="rule_1")

    assert codes(response) == ["conflict"]
    assert holder.applied == []


async def test_a_non_blocking_conflict_is_shown_and_allowed() -> None:
    holder = bridge()
    holder._raw_item("rules", "rule_1")["conflicts"] = [
        {"blocking": False, "message": "יש כלל דומה ביום אחר"}
    ]
    svc = ManagementService(holder, default_actor=OWNER)

    response = await preview(svc, "rules", "disable", resource_id="rule_1")

    assert response.valid is True
    assert "חפיפה" in (response.explanation or "")


async def test_deleting_a_rule_asks_for_the_word() -> None:
    response = await preview(service(), "rules", "delete", resource_id="rule_1")

    assert response.destructive is True
    assert response.confirm_word == "מחק"


# --- calendar ---------------------------------------------------------------
async def test_a_calendar_event_carries_a_user_id_and_no_entity_id() -> None:
    snapshot = await service().resource_snapshot("calendar")
    event = snapshot.items[0]

    assert event.detail["user_id"] == "user_1"
    assert "entity_id" not in event.detail
    assert "calendar." not in snapshot.model_dump_json()


async def test_an_existing_event_carries_no_verb_at_all() -> None:
    """Home Assistant publishes no service that changes a calendar event.

    Creating one is a service call; editing, moving and deleting are websocket
    operations a bridge script cannot reach. So the bridge advertises nothing
    on an event, and asking anyway is refused before a preview exists rather
    than previewed into a dialog nothing could carry out.
    """
    snapshot = await service().resource_snapshot("calendar")
    assert snapshot.items[0].operations == []

    response = await preview(service(), "calendar", "delete", resource_id="evt_1")

    assert response.would_execute is False
    assert codes(response) == ["not_controllable"]


# --- system -----------------------------------------------------------------
@pytest.mark.parametrize(
    "action",
    [
        "ha_restart",
        "core_restart",
        "host_reboot",
        "supervisor_update",
        "integration_delete",
        "device_remove",
        "backup_restore",
        "factory_reset",
        "run_shell_command",
    ],
)
async def test_an_unsafe_system_action_is_refused(action) -> None:
    """Refused for being what it is — before the question of whether it exists."""
    holder = bridge()
    svc = ManagementService(holder, default_actor=OWNER)

    response = await preview(svc, "system", "run", resource_id=action)

    assert codes(response) == ["forbidden_action"]
    assert holder.applied == []


async def test_an_unsafe_action_the_bridge_advertises_is_still_refused() -> None:
    """A bridge that started offering one would meet the same answer."""
    holder = bridge()
    holder.resources["system"]["items"].append(
        {
            "id": "ha_restart",
            "label": "הפעלה מחדש",
            "kind": "readonly",
            "value": "ready",
            "controllable": True,
            "operations": ["run"],
            "risk": "low",
        }
    )
    svc = ManagementService(holder, default_actor=OWNER)

    response = await preview(svc, "system", "run", resource_id="ha_restart")

    assert codes(response) == ["forbidden_action"]
    assert holder.applied == []


async def test_a_high_risk_system_action_asks_for_a_word() -> None:
    response = await preview(service(), "system", "run", resource_id="undo_last_action")

    assert response.valid is True
    assert response.destructive is False
    # Sensitive, not destructive — so the word is not "מחק".
    assert response.confirm_word == "אישור"


async def test_a_read_only_system_action_needs_no_word() -> None:
    response = await preview(service(), "system", "run", resource_id="self_check")

    assert response.valid is True
    assert response.confirm_word is None
