"""Normalization of real bridge responses.

The payloads here are the shapes observed in a live Home Assistant install:
`entries`, `registry`, `upcoming`/`profiles`/`drafts`, per-user `users` for
tasks, a nested `result` for the probe, and `checks` as a map.

The property every test defends is the same: **one canonical representation**,
with nothing populated sitting beside an empty legacy field.
"""

from __future__ import annotations

import pytest

from app.services import normalize


# --- status -----------------------------------------------------------------
def test_status_reads_real_fields_instead_of_leaving_nulls() -> None:
    result = normalize.normalize_status(
        {
            "api_version": "1",
            "ok": True,
            "version": "2.4.0",
            "components": [{"id": "whatsapp", "name": "WhatsApp", "status": "WORKING"}],
            "catalog_count": 19,
            "profile": "household",
        }
    )

    assert result.ok is True
    assert result.version == "2.4.0"
    assert len(result.components) == 1
    # A bare integer becomes a headline figure.
    assert result.counts["catalog_count"] == 19
    # A remaining scalar becomes a details row rather than being dropped.
    assert result.details["profile"] == "household"
    # Protocol metadata is not shown to a household member.
    assert "api_version" not in result.details


def test_status_translates_a_machine_status_word() -> None:
    result = normalize.normalize_status(
        {"components": [{"id": "whatsapp", "name": "WhatsApp", "status": "WORKING"}]}
    )
    component = result.components[0]
    assert component.label == "תקין"
    assert component.ok is True
    # The raw word is still available for the technical view.
    assert component.state == "WORKING"


def test_status_never_reports_writes_enabled() -> None:
    assert normalize.normalize_status({"writes_enabled": True}).writes_enabled is False


def test_status_survives_an_empty_payload() -> None:
    result = normalize.normalize_status({})
    assert result.components == []
    assert result.counts == {}
    assert result.whatsapp is None
    assert result.ai is None
    assert result.features == []


# The sections the real bridge sends instead of a `components` array.
REAL_STATUS = {
    "api_version": "1",
    "ok": True,
    "version": "2.4.0",
    "whatsapp": {"connected": True, "status": "WORKING"},
    "ai": {"enabled": True, "fast_paths": ["lighting", "climate", "shabbat"]},
    "users": {"total": 3, "active": 2, "admins": 1},
    "config": {"ok": True, "status": "OK"},
    "features": {"shabbat": True, "vision": False},
    "catalog_count": 19,
}


def test_status_exposes_the_real_sections_rather_than_details_rows() -> None:
    """The observed bug: real Bobi status was reduced mostly to `details` text."""
    result = normalize.normalize_status(REAL_STATUS)

    assert result.whatsapp is not None
    assert result.whatsapp.connected is True
    assert result.whatsapp.status == "WORKING"

    assert result.ai is not None
    assert result.ai.enabled is True
    assert result.ai.fast_paths_count == 3
    assert result.ai.fast_paths == ["lighting", "climate", "shabbat"]

    assert result.users is not None
    assert (result.users.total, result.users.active, result.users.admins) == (3, 2, 1)

    assert result.config is not None and result.config.ok is True

    assert {f.id: f.enabled for f in result.features} == {"shabbat": True, "vision": False}
    assert result.features[0].label == "שעון שבת"

    # None of it is duplicated as a details row.
    assert result.details == {}


# --- overall health ---------------------------------------------------------
def test_health_is_resolved_from_the_bridges_own_healthy_field() -> None:
    """The observed bug: `healthy` fell through to details as "True", ok stayed null."""
    result = normalize.normalize_status({"healthy": True, "whatsapp": {"connected": True}})

    assert result.health.status == "healthy"
    assert result.health.ok is True
    # The canonical `ok` now answers the question instead of returning null.
    assert result.ok is True
    # …and is not also repeated as a details row.
    assert "healthy" not in result.details


def test_health_reads_a_string_boolean_safely() -> None:
    """Bobi renders its booleans as Python text, so "True" must not read as unknown."""
    for spelling in ("True", "true", "yes", 1):
        result = normalize.normalize_status({"healthy": spelling})
        assert result.health.ok is True, spelling
        assert result.health.status == "healthy", spelling

    for spelling in ("False", "false", "no", 0):
        result = normalize.normalize_status({"healthy": spelling})
        assert result.health.ok is False, spelling
        assert result.health.status == "unhealthy", spelling


def test_health_is_not_false_just_because_a_component_is_unknown() -> None:
    """`config` arriving with ok: null is an unknown, not a failure."""
    result = normalize.normalize_status(
        {"whatsapp": {"connected": True}, "ai": {"enabled": True}, "config": {"status": "?"}}
    )

    assert result.health.ok is not False
    assert result.health.status == "healthy"
    # The unknown component is still reported honestly as unknown.
    config = next(c for c in result.components if c.id == "config")
    assert config.ok is None


def test_health_is_unknown_when_nothing_authoritative_was_sent() -> None:
    result = normalize.normalize_status({"version": "2.4.0"})

    assert result.health.status == "unknown"
    assert result.health.ok is None
    assert result.ok is None
    assert result.health.reason


def test_health_is_degraded_when_one_component_actually_failed() -> None:
    result = normalize.normalize_status(
        {"whatsapp": {"connected": False}, "ai": {"enabled": True}}
    )

    assert result.health.status == "degraded"
    assert result.health.ok is False
    assert "WhatsApp" in (result.health.reason or "")


def test_health_is_unhealthy_when_every_known_component_failed() -> None:
    result = normalize.normalize_status(
        {"whatsapp": {"connected": False}, "ai": {"enabled": False}}
    )
    assert result.health.status == "unhealthy"
    assert result.health.ok is False


def test_health_never_invents_a_state_from_an_empty_payload() -> None:
    result = normalize.normalize_status({})
    assert result.health.status == "unknown"
    assert result.health.ok is None


def test_status_builds_the_health_row_from_the_sections() -> None:
    """The real bridge sends no `components`, so the dashboard needs derived ones."""
    result = normalize.normalize_status(REAL_STATUS)

    assert [c.id for c in result.components] == ["bobi", "whatsapp", "ai", "config"]
    whatsapp = result.components[1]
    assert whatsapp.ok is True
    assert whatsapp.label == "תקין"


def test_status_prefers_a_component_list_the_bridge_actually_sends() -> None:
    result = normalize.normalize_status(
        {"ok": True, "components": [{"id": "bridge", "name": "גשר", "status": "WORKING"}]}
    )
    assert [c.id for c in result.components] == ["bridge"]


def test_status_accepts_flat_section_fields() -> None:
    """Some fields may arrive prefixed rather than nested."""
    result = normalize.normalize_status(
        {"whatsapp_connected": True, "ai_enabled": False, "fast_paths": 4,
         "active_users": 2}
    )

    assert result.whatsapp is not None and result.whatsapp.connected is True
    assert result.ai is not None and result.ai.enabled is False
    assert result.ai.fast_paths_count == 4
    assert result.users is not None and result.users.active == 2
    # Consumed, so they are not repeated as counts or details.
    assert result.counts == {}
    assert result.details == {}


def test_status_reads_a_bare_section_value() -> None:
    result = normalize.normalize_status({"whatsapp": "WORKING", "config": "OK"})

    assert result.whatsapp is not None and result.whatsapp.connected is True
    assert result.config is not None and result.config.ok is True


def test_status_keeps_an_unmapped_section_field() -> None:
    result = normalize.normalize_status({"whatsapp": {"connected": True, "session": "main"}})

    assert result.whatsapp is not None
    assert result.whatsapp.extra == {"session": "main"}


# --- devices ----------------------------------------------------------------
REAL_DEVICES = {
    "api_version": "1",
    "entries": [
        {
            "entity_id": "climate.parents",
            "name": "מזגן הורים",
            "canonical": "מזגן הורים",
            "semantic_scopes": ["climate", "temperature"],
            "aliases": ["מזגן הורים"],
            "domain": "climate",
            "group": "מיזוג",
            "area": "חדר הורים",
            "state": "off",
            "controllable": True,
            "logical_controllable": True,
            "handler": "climate_handler",
            "capabilities": ["turn_on", "turn_off"],
            "limits": {"min": 16, "max": 30},
            "last_changed": "2026-08-25T10:00:00+03:00",
            "future_bridge_field": "kept",
        },
        {
            "entity_id": "camera.girls",
            "canonical": "מצלמת ליה",
            "domain": "camera",
            "area": "חדר בנות",
            "state": "unavailable",
        },
    ],
}


def test_devices_reads_the_entries_collection() -> None:
    result = normalize.normalize_devices(REAL_DEVICES)

    assert result.count == 2
    assert [d.name for d in result.devices] == ["מזגן הורים", "מצלמת ליה"]


def test_devices_emits_exactly_one_collection() -> None:
    """The bug this normalizer exists to fix: no empty list beside a full one."""
    payload = normalize.normalize_devices(REAL_DEVICES).model_dump()

    assert "entries" not in payload
    assert "items" not in payload
    assert payload["devices"], "the one collection must be populated"
    assert len(payload["devices"]) == payload["count"]


def test_devices_derive_availability_and_facets() -> None:
    result = normalize.normalize_devices(REAL_DEVICES)

    assert result.devices[0].available is True
    assert result.devices[1].available is False
    assert result.areas == ["חדר בנות", "חדר הורים"]
    assert result.groups == ["מיזוג"]


def test_devices_keep_unknown_bridge_fields_in_extra() -> None:
    device = normalize.normalize_devices(REAL_DEVICES).devices[0]
    assert device.extra["future_bridge_field"] == "kept"
    # …and out of the fields the normal UI reads.
    assert "future_bridge_field" not in device.model_dump(exclude={"extra"})


def test_devices_accept_the_legacy_devices_key() -> None:
    result = normalize.normalize_devices({"devices": [{"entity_id": "light.a", "name": "אור"}]})
    assert result.count == 1


def test_devices_prefer_canonical_over_entity_id_for_display() -> None:
    result = normalize.normalize_devices(
        {"entries": [{"entity_id": "light.kitchen_main", "canonical": "אור מטבח"}]}
    )
    assert result.devices[0].name == "אור מטבח"
    assert result.devices[0].entity_id == "light.kitchen_main"


# --- device limits ----------------------------------------------------------
def _limits_of(limits: dict) -> object:
    device = normalize.normalize_devices({"entries": [{"id": "d", "limits": limits}]}).devices[0]
    assert device.limits is not None
    return device.limits


def test_climate_limits_are_kept_in_full() -> None:
    """The observed bug: rich limits collapsed to min/max/step nulls."""
    limits = _limits_of(
        {
            "min_temp": 16,
            "max_temp": 30,
            "temp_step": 0.5,
            "preset_modes": ["eco", "boost"],
            "fan_modes": ["low", "high"],
            "swing_modes": ["off", "vertical"],
        }
    )

    assert (limits.min_temp, limits.max_temp, limits.temp_step) == (16, 30, 0.5)
    assert limits.preset_modes == ["eco", "boost"]
    assert limits.fan_modes == ["low", "high"]
    assert limits.swing_modes == ["off", "vertical"]
    # The generic view still works for a plain slider.
    assert (limits.min, limits.max, limits.step) == (16, 30, 0.5)


def test_light_and_scent_limits_are_kept_in_full() -> None:
    light = _limits_of({"min_kelvin": 2200, "max_kelvin": 6500})
    assert (light.min_kelvin, light.max_kelvin) == (2200, 6500)

    scent = _limits_of(
        {
            "intensity_min": 1,
            "intensity_max": 10,
            "scent_slots": ["לבנדר", "וניל"],
            "timer_max_seconds": 7200,
        }
    )
    assert (scent.intensity_min, scent.intensity_max) == (1, 10)
    assert scent.scent_slots == ["לבנדר", "וניל"]
    assert scent.timer_max_seconds == 7200
    assert (scent.min, scent.max) == (1, 10)


def test_unrecognised_limits_are_kept_rather_than_dropped() -> None:
    limits = _limits_of({"min_temp": 16, "humidity_max": 80})
    assert limits.extra == {"humidity_max": 80}


def test_a_limit_list_of_objects_is_not_silently_lost() -> None:
    limits = _limits_of({"scent_slots": [{"slot": 1, "name": "לבנדר"}]})
    assert limits.scent_slots == []
    assert limits.extra["scent_slots"] == [{"slot": 1, "name": "לבנדר"}]


def test_a_device_without_limits_reports_none() -> None:
    device = normalize.normalize_devices({"entries": [{"id": "d"}]}).devices[0]
    assert device.limits is None


# --- capabilities -----------------------------------------------------------
REAL_CAPABILITIES = {
    "api_version": "1",
    "registry": {
        "lighting": {
            "handler": "lighting_handler",
            "local": True,
            "local_after_parse": False,
            "risk": "low",
            "label": "שליטה בתאורה",
            "example": "תדליק את אור הסלון",
        },
        "brand_new": {"handler": "future_handler", "risk": "high", "label": "יכולת חדשה"},
    },
    "toggles": {"master_ai": {"label": "AI fallback", "state": "on"}},
}


def test_capabilities_read_the_registry() -> None:
    result = normalize.normalize_capabilities(REAL_CAPABILITIES)

    assert result.count == 2
    by_id = {c.id: c for c in result.capabilities}
    assert by_id["lighting"].label == "שליטה בתאורה"
    assert by_id["lighting"].handler == "lighting_handler"
    assert by_id["lighting"].risk == "low"


def test_capabilities_emit_exactly_one_collection() -> None:
    payload = normalize.normalize_capabilities(REAL_CAPABILITIES).model_dump()
    assert "registry" not in payload
    assert len(payload["capabilities"]) == 2


def test_capabilities_do_not_discard_an_unknown_entry() -> None:
    result = normalize.normalize_capabilities(REAL_CAPABILITIES)
    assert any(c.id == "brand_new" for c in result.capabilities)


def test_capability_toggles_are_read_as_booleans() -> None:
    result = normalize.normalize_capabilities(REAL_CAPABILITIES)
    assert result.toggles[0].id == "master_ai"
    assert result.toggles[0].enabled is True


def test_capabilities_accept_a_list_registry() -> None:
    result = normalize.normalize_capabilities(
        {"registry": [{"id": "lighting", "label": "תאורה"}]}
    )
    assert result.capabilities[0].id == "lighting"


# --- users ------------------------------------------------------------------
def test_users_are_normalized() -> None:
    result = normalize.normalize_users(
        {"users": [{"id": "u1", "name": "ינון", "role": "admin", "permissions": ["a"]}]}
    )
    assert result.count == 1
    assert result.users[0].name == "ינון"


def test_users_drop_anything_that_looks_like_a_phone_number_or_lid() -> None:
    """Defence in depth: the bridge withholds these, and so does the normalizer."""
    result = normalize.normalize_users(
        {
            "users": [
                {
                    "id": "u1",
                    "name": "ינון",
                    "whatsapp_number": "+972500000000",
                    "lid": "12345@lid",
                    "chat_id": "12345@c.us",
                    "harmless": "kept",
                }
            ]
        }
    )
    serialized = result.model_dump_json()

    assert "972500000000" not in serialized
    assert "@lid" not in serialized
    assert "@c.us" not in serialized
    assert result.users[0].extra["harmless"] == "kept"


# --- probe ------------------------------------------------------------------
REAL_PROBE = {
    "api_version": "1",
    "executed": False,
    "result": {
        "handled": True,
        "status": "ok",
        "terminal": True,
        "skill": "local_schedule",
        "understanding": {"action": "turn_off", "target": "מזגן הורים"},
        "schedule_valid": True,
        "schedule_kind": "next_night_clock",
    },
}


def test_probe_flattens_the_nested_result() -> None:
    """The observed bug: top-level fields were null while `result` held them."""
    probe = normalize.normalize_probe(REAL_PROBE, "כבה מזגן הורים ב-1:30 בלילה")

    assert probe.handled is True
    assert probe.status == "ok"
    assert probe.terminal is True
    assert probe.skill == "local_schedule"
    assert probe.schedule_valid is True
    assert probe.schedule_kind == "next_night_clock"
    assert probe.understanding["target"] == "מזגן הורים"


def test_probe_keeps_the_raw_response_for_the_json_view() -> None:
    probe = normalize.normalize_probe(REAL_PROBE, "…")
    assert probe.raw == REAL_PROBE


def test_probe_accepts_a_flat_response_too() -> None:
    probe = normalize.normalize_probe({"handled": True, "skill": "tasks"}, "…")
    assert probe.handled is True
    assert probe.skill == "tasks"


def test_probe_falls_back_to_the_submitted_text() -> None:
    assert normalize.normalize_probe({}, "בדיקה").text == "בדיקה"


@pytest.mark.parametrize(
    "payload",
    [
        REAL_PROBE,
        {"result": {"handled": False}},
        {"executed": True, "result": {"handled": True}},
        {},
    ],
)
def test_probe_never_reports_execution(payload: dict) -> None:
    probe = normalize.normalize_probe(payload, "…")
    assert probe.would_execute is False
    assert probe.probe_only is True


def test_probe_warns_if_the_bridge_ever_claims_it_executed() -> None:
    """Forcing the flag false must not hide a real safety problem."""
    probe = normalize.normalize_probe({"executed": True, "result": {"handled": True}}, "…")
    assert probe.would_execute is False
    assert probe.warnings, "an unexpected execution claim must be visible"


# --- shabbat ----------------------------------------------------------------
REAL_SHABBAT = {
    "api_version": "1",
    "upcoming": {"candle_lighting": "18:52", "havdalah": "19:51", "parasha": "פרשת ראה"},
    "pre_shabbat_offset_minutes": 20,
    "profiles": {
        "pre_off": {"label": "כיבוי לפני שבת", "active": True, "devices": ["kitchen_light"]},
        "night_off": {"active": True, "time": "23:30", "devices": ["living_room_ac"]},
    },
    "drafts": {"user_a": {"has_draft": True}},
    "ac_temperatures": {"living_room_ac": 24},
    "device_labels": {"kitchen_light": "אור מטבח", "living_room_ac": "מזגן סלון"},
}


def test_shabbat_reads_times_from_upcoming() -> None:
    """The observed bug: the legacy time fields were null."""
    result = normalize.normalize_shabbat(REAL_SHABBAT)

    assert result.candle_lighting == "18:52"
    assert result.havdalah == "19:51"
    assert result.parasha == "פרשת ראה"
    assert result.pre_shabbat_offset_minutes == 20


def test_shabbat_flattens_profiles_into_one_list() -> None:
    result = normalize.normalize_shabbat(REAL_SHABBAT)

    kinds = {p.kind for p in result.profiles}
    assert kinds == {"pre_off", "night_off"}

    payload = result.model_dump()
    # No legacy named-profile fields sitting empty beside the list.
    assert "pre_off_profile" not in payload
    assert "upcoming" not in payload


def test_shabbat_labels_an_unknown_profile_kind() -> None:
    result = normalize.normalize_shabbat({"profiles": {"afternoon_dim": {"active": True}}})
    assert result.profiles[0].label == "Afternoon dim"


def test_shabbat_resolves_device_tokens_to_friendly_names() -> None:
    result = normalize.normalize_shabbat(REAL_SHABBAT)

    profile = next(p for p in result.profiles if p.kind == "pre_off")
    assert [d.label for d in profile.devices] == ["אור מטבח"]
    # The bridge's own token travels with the label: it is what Phase 3 will
    # have to send back to change the profile.
    assert [d.id for d in profile.devices] == ["kitchen_light"]


def test_shabbat_reads_device_tokens_the_bridge_calls_tokens() -> None:
    """The observed bug: real profiles carry `tokens`, so `devices` came back empty."""
    result = normalize.normalize_shabbat(
        {
            "profiles": {
                "pre_off": {
                    "active": True,
                    "tokens": ["dining", "kitchen", "led_salon", "ac_salon"],
                }
            },
            "device_labels": {
                "dining": "פינת אוכל",
                "kitchen": "מטבח",
                "led_salon": "LED סלון",
                "ac_salon": "מזגן סלון",
            },
        }
    )

    profile = result.profiles[0]
    assert [d.model_dump() for d in profile.devices] == [
        {"id": "dining", "label": "פינת אוכל"},
        {"id": "kitchen", "label": "מטבח"},
        {"id": "led_salon", "label": "LED סלון"},
        {"id": "ac_salon", "label": "מזגן סלון"},
    ]
    # And the raw tokens no longer sit in the Advanced panel as the only copy.
    assert "tokens" not in profile.extra


def test_shabbat_reads_the_pre_offset_from_upcoming() -> None:
    """The observed bug: the offset lives in `upcoming.pre_offset_minutes`."""
    result = normalize.normalize_shabbat(
        {"upcoming": {"candle_lighting": "18:52", "pre_offset_minutes": 30}}
    )
    assert result.pre_shabbat_offset_minutes == 30


def test_shabbat_keeps_each_temperature_tied_to_its_air_conditioner() -> None:
    result = normalize.normalize_shabbat(REAL_SHABBAT)

    assert [t.model_dump() for t in result.ac_temperatures] == [
        {
            "id": "living_room_ac",
            "label": "מזגן סלון",
            "temperature": 24.0,
            "text": "24",
        }
    ]


def test_shabbat_collects_temperatures_from_the_profiles() -> None:
    """The observed bug: the bridge keeps them per profile, so the list was empty."""
    result = normalize.normalize_shabbat(
        {
            "profiles": {
                "pre_off": {"ac_temperatures": {"ac_salon": 24.0, "ac_parents": 23.0}},
                "night_off": {"ac_temperatures": {"ac_lia": 25.5}},
            },
            "device_labels": {
                "ac_salon": "מזגן סלון",
                "ac_parents": "מזגן הורים",
                "ac_lia": "מזגן בנות",
            },
        }
    )

    assert [
        {"id": t.id, "label": t.label, "temperature": t.temperature}
        for t in result.ac_temperatures
    ] == [
        {"id": "ac_salon", "label": "מזגן סלון", "temperature": 24.0},
        {"id": "ac_parents", "label": "מזגן הורים", "temperature": 23.0},
        {"id": "ac_lia", "label": "מזגן בנות", "temperature": 25.5},
    ]


def test_shabbat_de_duplicates_a_temperature_shared_by_two_profiles() -> None:
    """One air conditioner named by several profiles is still one entry."""
    result = normalize.normalize_shabbat(
        {
            "profiles": {
                "pre_off": {"ac_temperatures": {"ac_salon": 24.0}},
                "night_off": {"ac_temperatures": {"ac_salon": 24.0, "ac_lia": 25.5}},
                "morning_on": {"ac_temperatures": {"ac_salon": 24.0}},
            }
        }
    )

    assert [t.id for t in result.ac_temperatures] == ["ac_salon", "ac_lia"]


def test_shabbat_keeps_the_first_reading_when_profiles_contradict() -> None:
    """A contradiction cannot be resolved here, so it is not reported twice."""
    result = normalize.normalize_shabbat(
        {
            "profiles": [
                {"kind": "pre_off", "ac_temperatures": {"ac_salon": 24.0}},
                {"kind": "night_off", "ac_temperatures": {"ac_salon": 21.0}},
            ]
        }
    )

    assert len(result.ac_temperatures) == 1
    assert result.ac_temperatures[0].temperature == 24.0


def test_shabbat_never_fabricates_a_missing_temperature() -> None:
    result = normalize.normalize_shabbat(
        {
            "profiles": {
                "pre_off": {"ac_temperatures": {"ac_salon": None, "ac_lia": ""}},
                "night_off": {"tokens": ["kitchen"]},
            }
        }
    )
    assert result.ac_temperatures == []


def test_shabbat_keeps_a_non_numeric_temperature_as_text() -> None:
    """A setting the bridge does not express as a number is shown, not dropped."""
    result = normalize.normalize_shabbat(
        {"profiles": {"pre_off": {"ac_temperatures": {"ac_salon": "auto"}}}}
    )

    entry = result.ac_temperatures[0]
    assert entry.temperature is None
    assert entry.text == "auto"


def test_shabbat_still_reads_a_top_level_temperature_map() -> None:
    result = normalize.normalize_shabbat({"ac_temperatures": {"ac_salon": 24}})
    assert result.ac_temperatures[0].temperature == 24.0


def test_shabbat_leaves_unprovided_profile_fields_null() -> None:
    """The bridge has no authoritative value for these yet — do not invent one."""
    result = normalize.normalize_shabbat({"profiles": {"pre_off": {"tokens": ["kitchen"]}}})

    profile = result.profiles[0]
    assert profile.active is None
    assert profile.time is None
    assert profile.offset_minutes is None


def test_shabbat_reports_who_has_a_draft() -> None:
    result = normalize.normalize_shabbat(REAL_SHABBAT)
    assert result.has_draft is True
    assert result.draft_owners == ["user_a"]


def test_shabbat_is_always_read_only() -> None:
    assert normalize.normalize_shabbat({"writes_enabled": True}).writes_enabled is False


# --- tasks ------------------------------------------------------------------
REAL_TASKS = {
    "api_version": "1",
    "users": [
        {
            "user": "ינון",
            "list_name": "משימות ינון",
            "tasks": [
                {"uid": "t1", "summary": "לקבוע תור לרופא", "status": "needs_action"},
                {"uid": "t2", "summary": "לחדש ביטוח", "status": "completed"},
            ],
        },
        {"user": "הודיה", "tasks": [{"uid": "t3", "summary": "לקנות חלב"}]},
    ],
}


def test_tasks_flatten_per_user_groups() -> None:
    """The observed bug: `tasks` was empty while `users` held the real items."""
    result = normalize.normalize_tasks(REAL_TASKS)

    assert result.count == 3
    assert [t.title for t in result.tasks] == ["לקבוע תור לרופא", "לחדש ביטוח", "לקנות חלב"]
    assert result.owners == ["ינון", "הודיה"]


def test_tasks_emit_exactly_one_collection() -> None:
    payload = normalize.normalize_tasks(REAL_TASKS).model_dump()
    assert "users" not in payload
    assert len(payload["tasks"]) == payload["count"]


def test_tasks_inherit_owner_and_list_from_their_group() -> None:
    result = normalize.normalize_tasks(REAL_TASKS)
    assert result.tasks[0].owner == "ינון"
    assert result.tasks[0].list_name == "משימות ינון"


def test_task_completion_is_derived_from_status() -> None:
    result = normalize.normalize_tasks(REAL_TASKS)
    assert result.tasks[0].completed is False
    assert result.tasks[1].completed is True


def test_tasks_accept_a_flat_list_too() -> None:
    result = normalize.normalize_tasks({"tasks": [{"uid": "a", "title": "משהו"}]})
    assert result.count == 1


# --- diagnostics ------------------------------------------------------------
REAL_DIAGNOSTICS = {
    "api_version": "1",
    "ok": False,
    "issue_count": 1,
    "issues": [
        {
            "severity": "warning",
            "code": "device_unavailable",
            "title": "מכשיר אינו זמין",
            "component": "device",
            "entity_id": "camera.girls",
        }
    ],
    "checks": {
        "whatsapp": "WORKING",
        "config": "OK",
        "catalog_count": 19,
        "catalog_controllable": 15,
    },
}


def test_diagnostics_accepts_the_real_response() -> None:
    """This exact shape returned HTTP 502 before the normalizer existed."""
    result = normalize.normalize_diagnostics(REAL_DIAGNOSTICS)

    assert result.ok is False
    assert result.issue_count == 1
    assert len(result.issues) == 1
    assert len(result.checks) == 4


def test_diagnostics_turns_a_checks_map_into_a_list() -> None:
    """`checks` arriving as a map was the cause of the validation failure."""
    result = normalize.normalize_diagnostics(REAL_DIAGNOSTICS)
    by_id = {c.id: c for c in result.checks}

    assert by_id["whatsapp"].ok is True
    assert by_id["whatsapp"].value == "WORKING"
    assert by_id["whatsapp"].label == "WhatsApp"


def test_a_numeric_check_is_informational_not_a_pass() -> None:
    result = normalize.normalize_diagnostics(REAL_DIAGNOSTICS)
    by_id = {c.id: c for c in result.checks}

    # 19 is a measurement; colouring it green would be a lie.
    assert by_id["catalog_count"].ok is None
    assert by_id["catalog_count"].value == "19"


def test_diagnostics_accepts_checks_as_a_list_too() -> None:
    result = normalize.normalize_diagnostics(
        {"checks": [{"id": "bridge", "label": "גשר", "ok": True}]}
    )
    assert result.checks[0].ok is True


def test_issue_entity_ids_are_collected() -> None:
    result = normalize.normalize_diagnostics(REAL_DIAGNOSTICS)
    assert result.issues[0].entity_ids == ["camera.girls"]
    assert result.issues[0].code == "device_unavailable"


def test_issue_ids_are_unique_even_when_the_code_repeats() -> None:
    """Two devices sharing a failure code must not collide as React keys."""
    result = normalize.normalize_diagnostics(
        {
            "issues": [
                {"code": "device_unavailable", "title": "א", "entity_id": "camera.a"},
                {"code": "device_unavailable", "title": "ב", "entity_id": "camera.b"},
                {"code": "device_unavailable", "title": "ג"},
            ]
        }
    )
    ids = [issue.id for issue in result.issues]
    assert len(ids) == len(set(ids)), ids


def test_diagnostics_counts_issues_when_the_bridge_omits_the_total() -> None:
    result = normalize.normalize_diagnostics({"issues": [{"title": "א"}, {"title": "ב"}]})
    assert result.issue_count == 2


# --- shared behaviour -------------------------------------------------------
@pytest.mark.parametrize(
    "normalizer",
    [
        normalize.normalize_status,
        normalize.normalize_devices,
        normalize.normalize_capabilities,
        normalize.normalize_users,
        normalize.normalize_shabbat,
        normalize.normalize_rules,
        normalize.normalize_tasks,
        normalize.normalize_diagnostics,
    ],
)
def test_every_normalizer_survives_an_empty_payload(normalizer) -> None:
    """A partial bridge response must produce an empty screen, not a 502."""
    assert normalizer({}) is not None


@pytest.mark.parametrize(
    "normalizer",
    [
        normalize.normalize_devices,
        normalize.normalize_capabilities,
        normalize.normalize_users,
        normalize.normalize_rules,
        normalize.normalize_tasks,
        normalize.normalize_diagnostics,
    ],
)
def test_every_normalizer_survives_a_junk_collection(normalizer) -> None:
    payload = dict.fromkeys(("entries", "devices", "registry", "users", "rules", "tasks", "issues", "checks", "profiles"), "not a collection")
    assert normalizer(payload) is not None
