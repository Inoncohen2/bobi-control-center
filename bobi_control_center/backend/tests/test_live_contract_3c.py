"""The contract and the settings snapshot exactly as this house sends them.

Every payload below was captured from a live Home Assistant on 2026-08-26 —
contract `3c`, twenty-eight `bobi_cc_*` scripts, master switch off. Not
paraphrased and not tidied: the point of these tests is that the application
handles what the bridge *does* send rather than what a specification says it
ought to.

Two mismatches were found this way and are fixed here rather than in Home
Assistant, because both are pure synonyms and reconciling vocabulary is the
caller's job:

* the bridge says `kind: "boolean"` and `"select"` where this application says
  `toggle` and `choice` — and an unrecognised kind used to fall through to the
  text editor, so a household member would have been shown a free-text box
  where a switch belongs;
* the bridge says `add` for rules and calendar events where this application
  says `create` — and an unreconciled synonym is dropped by the closed-set
  filter, so the operation would have been announced by one side, quietly not
  offered by the other, and reported as wrong by neither.

Private data is redacted from the fixtures; the structure is untouched.
"""

from __future__ import annotations

import httpx
import pytest

from app.adapters.real_management import CONTRACT
from tests.conftest import json_response

#: `script.bobi_cc_manage_contract`, live. Trimmed to the fields that matter
#: here, with the legacy per-family blocks kept because the real one sends both.
LIVE_CONTRACT = {
    "api_version": "1",
    "contract_version": "3c",
    "bridge_available": True,
    "writes_enabled": False,
    "requires_preview": True,
    "requires_confirmation": True,
    "requires_read_after_write": True,
    "tasks": {
        "supported": True,
        "operations": ["add", "edit", "complete", "reopen", "delete"],
        "users": [{"id": "user_1", "name": "משתמש א"}, {"id": "user_2", "name": "משתמש ב"}],
    },
    "features": {
        "supported": True,
        "operations": ["set"],
        "items": [
            {"id": "morning_auto", "label": "סיכום בוקר אוטומטי", "risk": "low", "enabled": True},
            {"id": "home_status_auto", "label": "מצב הבית האוטומטי", "risk": "low", "enabled": True},
        ],
    },
    "not_supported": [
        "raw_entity_write",
        "raw_service_call",
        "restart",
        "supervisor_update",
        "integration_delete",
        "device_delete",
        "backup_restore",
        "shell",
        "camera_power_from_web",
    ],
    "resources": [
        {
            "id": "settings",
            "label": "הגדרות",
            "available": True,
            "operations": [{"id": "set", "label": "שינוי הגדרה", "destructive": False}],
            "targets": [],
        },
        {
            "id": "rules",
            "label": "כללים חכמים",
            "available": True,
            "operations": [
                {"id": "add", "label": "הוספה", "destructive": False},
                {"id": "edit", "label": "עריכה", "destructive": False},
                {"id": "enable", "label": "הפעלה", "destructive": False},
                {"id": "disable", "label": "השבתה", "destructive": False},
                {"id": "delete", "label": "מחיקה", "destructive": True},
            ],
            "targets": [],
        },
        {
            "id": "calendar",
            "label": "יומן",
            "available": True,
            "operations": [
                {"id": "add", "label": "הוספת אירוע", "destructive": False},
                {"id": "edit", "label": "עריכת אירוע", "destructive": False},
                {"id": "move", "label": "הזזת אירוע", "destructive": False},
                {"id": "delete", "label": "מחיקת אירוע", "destructive": True},
            ],
            "targets": [{"id": "user_1", "label": "משתמש א"}],
        },
        {
            "id": "system",
            "label": "מערכת",
            "available": True,
            "operations": [{"id": "run", "label": "הרצת בדיקה", "destructive": False}],
            "targets": [
                {"id": "self_check", "label": "בדיקה עצמית"},
                {"id": "benchmark", "label": "Benchmark"},
            ],
        },
    ],
}

#: `script.bobi_cc_settings_snapshot`, live. One group of each shape it sends.
LIVE_SETTINGS = {
    "resource": "settings",
    "available": True,
    "writes_enabled": False,
    "groups": [
        {
            "id": "morning",
            "label": "בוקר",
            "items": [
                {
                    "id": "morning_master",
                    "label": "סיכום בוקר אוטומטי",
                    "kind": "boolean",
                    "value": True,
                    "risk": "low",
                    "controllable": True,
                    "operations": ["set"],
                },
                {
                    "id": "morning_time",
                    "label": "שעת סיכום הבוקר",
                    "kind": "time",
                    "value": "07:00",
                    "risk": "low",
                    "controllable": True,
                    "operations": ["set"],
                },
            ],
        },
        {
            "id": "home_status",
            "label": "מצב הבית",
            "items": [
                {
                    "id": "home_policy",
                    "label": "מתי לשלוח",
                    "kind": "select",
                    "value": "רק מחוץ לבית",
                    "risk": "low",
                    "controllable": True,
                    "operations": ["set"],
                    "options": [
                        {"value": "רק מחוץ לבית", "label": "רק מחוץ לבית"},
                        {"value": "תמיד", "label": "תמיד"},
                    ],
                }
            ],
        },
        {
            "id": "ai",
            "label": "AI וזיכרון",
            "items": [
                {
                    "id": "ai_monthly_cap",
                    "label": "מכסה חודשית ל-AI",
                    "kind": "number",
                    "value": 20,
                    "risk": "medium",
                    "controllable": True,
                    "operations": ["set"],
                    "constraints": {"minimum": 1, "maximum": 200, "step": 1, "unit": "₪"},
                }
            ],
        },
    ],
    "items": [],
    "detail": {"quiet_hours": "23:00-06:00"},
}


@pytest.fixture
def live_bridge(make_real_adapter, recorded_requests):
    def factory(responses: dict[str, dict]):
        def handler(request: httpx.Request) -> httpx.Response:
            recorded_requests.append(request)
            service = request.url.path.rsplit("/", 1)[-1]
            if service not in responses:
                return json_response({"message": "Service not found."}, 404)
            return json_response({"service_response": responses[service]})

        adapter = make_real_adapter(handler)
        return adapter, adapter.management_bridge()

    return factory


# --- the contract -----------------------------------------------------------
async def test_the_live_contract_is_read_whole(live_bridge) -> None:
    adapter, bridge = live_bridge({CONTRACT: LIVE_CONTRACT})
    status = await bridge.status()
    await adapter.aclose()

    assert status.contract_version == "3c"
    assert status.available is True
    # The kill switch, as this house has it.
    assert status.writes_enabled is False
    assert {resource.id for resource in status.resources} >= {
        "tasks",
        "features",
        "settings",
        "rules",
        "calendar",
        "system",
    }


async def test_add_is_understood_as_create(live_bridge) -> None:
    """The bridge's word for it, translated rather than dropped."""
    adapter, bridge = live_bridge({CONTRACT: LIVE_CONTRACT})
    status = await bridge.status()
    await adapter.aclose()

    rules = next(entry for entry in status.resources if entry.id == "rules")
    calendar = next(entry for entry in status.resources if entry.id == "calendar")

    assert "create" in [op.id for op in rules.operations]
    assert "create" in [op.id for op in calendar.operations]
    # And nothing was lost on the way.
    assert {op.id for op in rules.operations} == {
        "create",
        "edit",
        "enable",
        "disable",
        "delete",
    }


async def test_add_still_means_add_for_tasks(live_bridge) -> None:
    """A synonym translates only where the family declares the other name.

    `tasks` calls it `add` itself, so nothing should be rewritten there — the
    translation must not turn a verb the family has into one it does not.
    """
    adapter, bridge = live_bridge({CONTRACT: LIVE_CONTRACT})
    status = await bridge.status()
    await adapter.aclose()

    tasks = next(entry for entry in status.resources if entry.id == "tasks")
    assert "add" in [op.id for op in tasks.operations]
    assert "create" not in [op.id for op in tasks.operations]


async def test_delete_is_still_marked_destructive(live_bridge) -> None:
    adapter, bridge = live_bridge({CONTRACT: LIVE_CONTRACT})
    status = await bridge.status()
    await adapter.aclose()

    for name in ("rules", "calendar"):
        resource = next(entry for entry in status.resources if entry.id == name)
        delete = next(op for op in resource.operations if op.id == "delete")
        assert delete.destructive is True, name


async def test_the_families_this_house_has_not_declared_stay_absent(live_bridge) -> None:
    """Their snapshot scripts exist; the contract does not name them yet."""
    adapter, bridge = live_bridge({CONTRACT: LIVE_CONTRACT})
    status = await bridge.status()
    await adapter.aclose()

    declared = {entry.id for entry in status.resources if entry.available}
    for absent in ("helpers", "automations", "scripts", "scenes"):
        assert absent not in declared, absent


# --- the settings snapshot --------------------------------------------------
async def test_the_live_settings_snapshot_normalizes(live_bridge) -> None:
    adapter, bridge = live_bridge({"bobi_cc_settings_snapshot": LIVE_SETTINGS})
    snapshot = await bridge.resource_snapshot("settings")
    await adapter.aclose()

    assert snapshot.available is True
    assert [group.id for group in snapshot.groups] == ["morning", "home_status", "ai"]
    assert {item.id for item in snapshot.items} == {
        "morning_master",
        "morning_time",
        "home_policy",
        "ai_monthly_cap",
    }


async def test_the_bridges_word_for_a_control_is_understood(live_bridge) -> None:
    """`boolean` is a toggle and `select` is a choice — not free text."""
    adapter, bridge = live_bridge({"bobi_cc_settings_snapshot": LIVE_SETTINGS})
    snapshot = await bridge.resource_snapshot("settings")
    await adapter.aclose()

    kinds = {item.id: item.kind for item in snapshot.items}
    assert kinds["morning_master"] == "toggle"
    assert kinds["home_policy"] == "choice"
    assert kinds["morning_time"] == "time"
    assert kinds["ai_monthly_cap"] == "number"


async def test_an_unrecognised_kind_is_shown_as_a_reading(live_bridge) -> None:
    """Never as a text box: that would invite a value the bridge never offered."""
    payload = {
        "available": True,
        "items": [
            {
                "id": "odd",
                "label": "משהו",
                "kind": "quantum",
                "value": "x",
                "controllable": True,
                "operations": ["set"],
            }
        ],
    }
    adapter, bridge = live_bridge({"bobi_cc_settings_snapshot": payload})
    snapshot = await bridge.resource_snapshot("settings")
    await adapter.aclose()

    assert snapshot.items[0].kind == "readonly"


async def test_the_published_limits_survive(live_bridge) -> None:
    adapter, bridge = live_bridge({"bobi_cc_settings_snapshot": LIVE_SETTINGS})
    snapshot = await bridge.resource_snapshot("settings")
    await adapter.aclose()

    cap = next(item for item in snapshot.items if item.id == "ai_monthly_cap")
    assert cap.constraints is not None
    assert (cap.constraints.minimum, cap.constraints.maximum) == (1.0, 200.0)
    assert cap.constraints.unit == "₪"


async def test_the_choices_are_the_ones_the_bridge_offered(live_bridge) -> None:
    adapter, bridge = live_bridge({"bobi_cc_settings_snapshot": LIVE_SETTINGS})
    snapshot = await bridge.resource_snapshot("settings")
    await adapter.aclose()

    policy = next(item for item in snapshot.items if item.id == "home_policy")
    assert [option.value for option in policy.options] == ["רק מחוץ לבית", "תמיד"]


async def test_a_missing_commit_script_answers_unavailable(live_bridge) -> None:
    """Six commit bridges do not exist yet. Asking for one is not an error page."""
    adapter, bridge = live_bridge({CONTRACT: LIVE_CONTRACT})
    snapshot = await bridge.resource_snapshot("scenes")
    await adapter.aclose()

    assert snapshot.available is False
    assert snapshot.reason
    assert snapshot.items == []


async def test_what_this_house_says_it_will_not_do_matches_what_we_refuse(
    live_bridge,
) -> None:
    """The bridge publishes its own refusals. They agree with ours."""
    from app.services.bridge_contract import NEVER_REQUESTED
    from app.services.resources import is_forbidden_system_action

    for action in LIVE_CONTRACT["not_supported"]:
        if action in ("raw_entity_write", "raw_service_call", "camera_power_from_web"):
            # Structural refusals: there is no route that could express these.
            continue
        assert is_forbidden_system_action(action), action

    published = " ".join(NEVER_REQUESTED).lower()
    for word in ("restart", "supervisor", "delet", "backup", "shell"):
        assert word in published, word


# --- contract 3c after the vocabulary was reconciled -------------------------
#: The `resources` block this house publishes now, captured after both sides
#: were brought into line: `devices` names one verb per capability, and the four
#: families whose snapshot bridges shipped ahead of their commit bridges are
#: declared with an empty `operations` list rather than left out.
LIVE_RESOURCES_AFTER = [
    {
        "id": "devices",
        "label": "מכשירים",
        "available": True,
        "operations": [
            {"id": name, "label": name, "destructive": False}
            for name in (
                "power", "temperature", "hvac_mode", "fan_mode", "swing_mode",
                "preset_mode", "brightness", "color_temp", "fan_speed", "start",
                "pause", "stop", "return_to_base", "locate",
            )
        ],
        "targets": [],
    },
    {"id": "helpers", "label": "עזרים", "available": True, "operations": [], "targets": []},
    {
        "id": "automations",
        "label": "אוטומציות Home Assistant",
        "available": True,
        "operations": [],
        "targets": [],
    },
    {"id": "scripts", "label": "סקריפטים", "available": True, "operations": [], "targets": []},
    {"id": "scenes", "label": "סצנות", "available": True, "operations": [], "targets": []},
]


async def test_every_device_verb_this_house_declares_survives(live_bridge) -> None:
    """Fourteen verbs, none dropped.

    The closed set on this side is what makes the write path safe, and it is
    also what silently discarded every device verb this house had — the family
    came back described and inoperable. If Home Assistant declares a verb and
    this list does not, that is the same failure returning.
    """
    from app.services.resources import DEVICE_OPERATIONS

    contract = dict(LIVE_CONTRACT, resources=LIVE_RESOURCES_AFTER)
    adapter, bridge = live_bridge({CONTRACT: contract})
    status = await bridge.status()
    await adapter.aclose()

    devices = next(entry for entry in status.resources if entry.id == "devices")
    declared = {op.id for op in devices.operations}

    assert len(declared) == 14
    assert declared <= set(DEVICE_OPERATIONS), declared - set(DEVICE_OPERATIONS)


async def test_a_family_with_no_commit_bridge_is_readable_not_absent(live_bridge) -> None:
    """An empty `operations` list is the contract's way of saying "snapshot
    only". It must read as available-and-read-only, never as missing: the
    difference is a screen full of values against a screen saying nothing."""
    contract = dict(LIVE_CONTRACT, resources=LIVE_RESOURCES_AFTER)
    adapter, bridge = live_bridge({CONTRACT: contract})
    status = await bridge.status()
    await adapter.aclose()

    for name in ("helpers", "automations", "scripts", "scenes"):
        family = next(entry for entry in status.resources if entry.id == name)
        assert family.available is True, name
        assert family.operations == [], name
