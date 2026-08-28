"""Mock bridge payloads, in the shape the **real** bridge sends.

These deliberately mirror the raw Home Assistant response — `entries`,
`registry`, `upcoming`/`profiles`/`drafts`, per-user `users` for tasks, a nested
`result` for the probe, and `checks` as a map. That way the mock adapter runs
through exactly the same normalizer as the real one, and mock mode is a faithful
rehearsal rather than a parallel universe.

Everything here is invented. No real entity id, phone number, or household
detail appears in this file.
"""

from __future__ import annotations

from typing import Any

from app.timeutil import days_ahead, hours_ago, minutes_ago


def _iso(value) -> str:
    return value.isoformat()


def status_payload() -> dict[str, Any]:
    """Sections rather than a health list, as the real bridge sends it.

    The real `bobi_cc_status` sends no `components` array: it reports WhatsApp,
    the AI fallback and its fast paths, the household, feature toggles and the
    health of its own configuration as separate sections, and the normalizer
    builds the dashboard's health row out of those.
    """
    return {
        "api_version": "1",
        # The real bridge reports `healthy`, not `ok` — the normalizer resolves
        # both into one canonical health answer.
        "healthy": True,
        "version": "bobi-demo-2.0",
        "uptime": "4 ימים",
        "whatsapp": {"connected": True, "status": "WORKING",
                     "detail": "החיבור יציב מאז אתמול"},
        "ai": {
            "enabled": True,
            "fast_paths": ["lighting", "climate", "state_query", "shabbat"],
        },
        "users": {"total": 2, "active": 2, "admins": 1},
        "config": {"ok": True, "status": "OK"},
        "features": {
            "shabbat": True,
            "tasks": True,
            "calendar": True,
            "notifications": True,
            "vision": False,
        },
        # Bare integers alongside the documented fields become count cards.
        "catalog_count": 18,
        "catalog_controllable": 13,
        "rules_count": 6,
        "open_tasks": 4,
        "issue_count": 3,
        # A remaining scalar becomes a details row rather than being dropped.
        "profile": "household",
    }


def _entry(
    entity_id: str,
    canonical: str,
    domain: str,
    area: str,
    state: str,
    *,
    group: str,
    scopes: list[str],
    aliases: list[str],
    capabilities: list[str],
    handler: str,
    controllable: bool = True,
    limits: dict[str, Any] | None = None,
    minutes: int = 30,
) -> dict[str, Any]:
    return {
        "entity_id": entity_id,
        "name": canonical,
        "canonical": canonical,
        "semantic_scopes": scopes,
        "aliases": aliases,
        "domain": domain,
        "group": group,
        "area": area,
        "state": state,
        "controllable": controllable,
        "logical_controllable": controllable,
        "handler": handler,
        "capabilities": capabilities,
        "limits": limits,
        "last_changed": _iso(minutes_ago(minutes)),
    }


_ENTRIES: list[dict[str, Any]] = [
    _entry("light.demo_living_room", "אור סלון", "light", "סלון", "on",
           group="תאורה", scopes=["lighting"], aliases=["אור סלון", "האור בסלון"],
           capabilities=["turn_on", "turn_off", "set_brightness"], handler="lighting_handler",
           limits={"min_brightness": 1, "max_brightness": 255,
                   "min_kelvin": 2200, "max_kelvin": 6500}),
    _entry("light.demo_kitchen", "אור מטבח", "light", "מטבח", "off",
           group="תאורה", scopes=["lighting"], aliases=["אור מטבח", "האור במטבח"],
           capabilities=["turn_on", "turn_off"], handler="lighting_handler", minutes=95),
    _entry("light.demo_garden", "אור חצר", "light", "חוץ", "off",
           group="תאורה", scopes=["lighting"], aliases=["אור חצר", "התאורה בחצר"],
           capabilities=["turn_on", "turn_off"], handler="lighting_handler", minutes=300),
    _entry("climate.demo_living_room", "מזגן סלון", "climate", "סלון", "off",
           group="מיזוג", scopes=["climate", "temperature"],
           aliases=["מזגן סלון", "המזגן בסלון"],
           capabilities=["turn_on", "turn_off", "set_temperature"], handler="climate_handler",
           limits={"min_temp": 16, "max_temp": 30, "temp_step": 1,
                   "hvac_modes": ["off", "cool", "heat", "fan_only"],
                   "preset_modes": ["eco", "boost"],
                   "fan_modes": ["low", "medium", "high", "auto"],
                   "swing_modes": ["off", "vertical"]}, minutes=140),
    _entry("climate.demo_parents", "מזגן הורים", "climate", "חדר הורים", "off",
           group="מיזוג", scopes=["climate", "temperature"],
           aliases=["מזגן הורים", "המזגן בחדר הורים"],
           capabilities=["turn_on", "turn_off", "set_temperature"], handler="climate_handler",
           limits={"min_temp": 16, "max_temp": 30, "temp_step": 1,
                   "hvac_modes": ["off", "cool", "heat", "fan_only"],
                   "preset_modes": ["eco", "boost"],
                   "fan_modes": ["low", "medium", "high", "auto"],
                   "swing_modes": ["off", "vertical"]}, minutes=620),
    _entry("climate.demo_girls", "מזגן חדר בנות", "climate", "חדר בנות", "cool",
           group="מיזוג", scopes=["climate", "temperature"],
           aliases=["מזגן בנות", "המזגן בחדר בנות"],
           capabilities=["turn_on", "turn_off", "set_temperature"], handler="climate_handler",
           limits={"min_temp": 16, "max_temp": 30, "temp_step": 1,
                   "hvac_modes": ["off", "cool", "heat", "fan_only"],
                   "preset_modes": ["eco", "boost"],
                   "fan_modes": ["low", "medium", "high", "auto"],
                   "swing_modes": ["off", "vertical"]}, minutes=300),
    _entry("camera.demo_entrance", "מצלמת כניסה", "camera", "חוץ", "recording",
           group="מצלמות", scopes=["cameras"], aliases=["מצלמת כניסה"],
           capabilities=["snapshot"], handler="camera_handler", controllable=False, minutes=5),
    _entry("camera.demo_girls_a", "מצלמת ליה", "camera", "חדר בנות", "unavailable",
           group="מצלמות", scopes=["cameras"], aliases=["מצלמת ליה"],
           capabilities=["snapshot"], handler="camera_handler", controllable=False, minutes=125),
    _entry("camera.demo_girls_b", "מצלמת שיה", "camera", "חדר בנות", "unavailable",
           group="מצלמות", scopes=["cameras"], aliases=["מצלמת שיה"],
           capabilities=["snapshot"], handler="camera_handler", controllable=False, minutes=540),
    _entry("switch.demo_boiler", "דוד", "switch", "מטבח", "off",
           group="חשמל", scopes=["switches"], aliases=["דוד", "המים החמים"],
           capabilities=["turn_on", "turn_off", "run_for"], handler="boiler_handler", minutes=240),
    _entry("switch.demo_kettle", "קומקום", "switch", "מטבח", "off",
           group="חשמל", scopes=["switches"], aliases=["קומקום"],
           capabilities=["turn_on", "turn_off"], handler="switch_handler", minutes=180),
    _entry("switch.demo_scent", "מפיץ ריח", "switch", "סלון", "off",
           group="ריח", scopes=["scent", "switches"], aliases=["מפיץ ריח", "הריח"],
           capabilities=["turn_on", "turn_off", "set_intensity"], handler="scent_handler",
           limits={"intensity_min": 1, "intensity_max": 10,
                   "scent_slots": ["לבנדר", "וניל", "הדרים"],
                   "timer_max_seconds": 7200},
           minutes=400),
    _entry("vacuum.demo_robot", "רובי", "vacuum", "מטבח", "docked",
           group="ניקיון", scopes=["vacuum"], aliases=["רובי", "השואב"],
           capabilities=["start", "stop", "return_to_base"], handler="vacuum_handler",
           minutes=1500),
    _entry("sensor.demo_outdoor_temp", "טמפרטורה בחוץ", "sensor", "חוץ", "31.2",
           group="חיישנים", scopes=["temperature"], aliases=["טמפרטורה בחוץ"],
           capabilities=["read"], handler="sensor_handler", controllable=False, minutes=6),
    _entry("sensor.demo_living_room_humidity", "לחות בסלון", "sensor", "סלון", "48",
           group="חיישנים", scopes=["humidity"], aliases=["לחות בסלון"],
           capabilities=["read"], handler="sensor_handler", controllable=False, minutes=9),
    _entry("sensor.demo_remote_battery", "סוללת שלט", "sensor", "סלון", "12",
           group="חיישנים", scopes=["battery"], aliases=["סוללת שלט"],
           capabilities=["read"], handler="sensor_handler", controllable=False, minutes=60),
    _entry("person.demo_a", "ינון", "person", "בית", "home",
           group="אנשים", scopes=["people"], aliases=["ינון"],
           capabilities=["read"], handler="presence_handler", controllable=False, minutes=45),
    _entry("person.demo_b", "הודיה", "person", "בית", "not_home",
           group="אנשים", scopes=["people"], aliases=["הודיה"],
           capabilities=["read"], handler="presence_handler", controllable=False, minutes=200),
]


def devices_payload(scope: str = "all", include_unavailable: bool = True) -> dict[str, Any]:
    """The catalog under `entries`, filtered the way the bridge does."""
    entries = _ENTRIES
    if scope != "all":
        entries = [e for e in entries if scope in e["semantic_scopes"]]
    if not include_unavailable:
        entries = [e for e in entries if e["state"] not in {"unavailable", "unknown"}]
    return {
        "api_version": "1",
        "scope": scope,
        "include_unavailable": include_unavailable,
        "count": len(entries),
        "entries": entries,
    }


def capabilities_payload() -> dict[str, Any]:
    """The registry as a map keyed by capability id."""
    registry = {
        "lighting": {"handler": "lighting_handler", "local": True, "local_after_parse": False,
                     "risk": "low", "label": "שליטה בתאורה", "example": "תדליק את אור הסלון",
                     "group": "שליטה בבית"},
        "climate": {"handler": "climate_handler", "local": True, "local_after_parse": False,
                    "risk": "low", "label": "שליטה במזגנים", "example": "תכבה את המזגן בסלון",
                    "group": "שליטה בבית"},
        "boiler": {"handler": "boiler_handler", "local": True, "local_after_parse": False,
                   "risk": "medium", "label": "הפעלת דוד", "example": "תדליק את הדוד לחצי שעה",
                   "group": "שליטה בבית"},
        "scent": {"handler": "scent_handler", "local": True, "local_after_parse": False,
                  "risk": "low", "label": "מפיץ ריח", "example": "תפעיל את מפיץ הריח",
                  "group": "שליטה בבית"},
        "vacuum": {"handler": "vacuum_handler", "local": True, "local_after_parse": False,
                   "risk": "medium", "label": "הפעלת רובי",
                   "example": "תשלח את רובי לנקות את המטבח", "group": "שליטה בבית"},
        "cameras": {"handler": "camera_handler", "local": True, "local_after_parse": False,
                    "risk": "high", "label": "צילום ממצלמה",
                    "example": "תצלם את מצלמת הכניסה", "group": "שליטה בבית"},
        "covers": {"handler": "cover_handler", "local": True, "local_after_parse": False,
                   "risk": "medium", "label": "תריסים", "example": "תסגור את תריס הסלון",
                   "group": "שליטה בבית"},
        "local_schedule": {"handler": "schedule_handler", "local": True,
                           "local_after_parse": True, "risk": "medium", "label": "תזמונים",
                           "example": "כבה את המזגן ב-1:30 בלילה", "group": "זמן ותזמון"},
        "shabbat": {"handler": "shabbat_handler", "local": True, "local_after_parse": False,
                    "risk": "low", "label": "שעון שבת", "example": "מתי כניסת שבת",
                    "group": "זמן ותזמון"},
        "calendar": {"handler": "calendar_handler", "local": True, "local_after_parse": False,
                     "risk": "low", "label": "יומן", "example": "מה יש לי מחר ביומן",
                     "group": "זמן ותזמון"},
        "tasks": {"handler": "tasks_handler", "local": True, "local_after_parse": False,
                  "risk": "low", "label": "משימות", "example": "תוסיף משימה לקנות חלב",
                  "group": "זמן ותזמון"},
        "state_query": {"handler": "query_handler", "local": True, "local_after_parse": False,
                        "risk": "low", "label": "שאלות על הבית",
                        "example": "מה הטמפרטורה בסלון", "group": "מידע"},
        "presence": {"handler": "presence_handler", "local": True, "local_after_parse": False,
                     "risk": "low", "label": "מי בבית", "example": "מי נמצא בבית עכשיו",
                     "group": "מידע"},
        "notifications": {"handler": "notify_handler", "local": True,
                          "local_after_parse": False, "risk": "low", "label": "התראות יזומות",
                          "example": "תודיע לי כשהכביסה נגמרת", "group": "תקשורת"},
        "ai_fallback": {"handler": "ai_handler", "local": False, "local_after_parse": True,
                        "risk": "medium", "label": "בינה מלאכותית חופשית",
                        "example": "שאלה חופשית שבובי לא מזהה", "group": "בינה מלאכותית"},
        "vision": {"handler": "vision_handler", "local": False, "local_after_parse": False,
                   "risk": "high", "label": "עיבוד תמונות", "example": "מה רואים בתמונה הזו",
                   "group": "בינה מלאכותית"},
    }
    toggles = {
        "master_notifications": {"label": "התראות יזומות", "state": "on",
                                 "entity_id": "input_boolean.demo_notifications"},
        "master_ai": {"label": "בינה מלאכותית חופשית", "state": "on",
                      "entity_id": "input_boolean.demo_ai"},
        "master_vision": {"label": "עיבוד תמונות", "state": "off",
                          "entity_id": "input_boolean.demo_vision"},
        "master_shabbat": {"label": "שעון שבת", "state": "on",
                           "entity_id": "input_boolean.demo_shabbat"},
    }
    return {"api_version": "1", "count": len(registry), "registry": registry, "toggles": toggles}


def users_payload() -> dict[str, Any]:
    """No phone numbers, no LIDs — matching what the bridge withholds."""
    return {
        "api_version": "1",
        "count": 2,
        "users": [
            {
                "id": "user_a", "name": "ינון", "role": "admin", "enabled": True,
                "whatsapp_connected": True, "calendar": "יומן ינון",
                "task_list": "משימות ינון",
                "permissions": ["control_devices", "manage_automations", "manage_shabbat",
                                "manage_tasks", "manage_calendar", "view_cameras", "manage_bobi"],
                "areas": ["סלון", "מטבח", "חדר הורים", "חוץ"],
            },
            {
                "id": "user_b", "name": "הודיה", "role": "member", "enabled": True,
                "whatsapp_connected": True, "calendar": "יומן משפחה",
                "task_list": "משימות הודיה",
                "permissions": ["control_devices", "manage_shabbat", "manage_tasks",
                                "manage_calendar", "view_cameras"],
                "areas": ["סלון", "מטבח", "חדר בנות"],
            },
        ],
    }


def shabbat_payload() -> dict[str, Any]:
    """Grouped under `upcoming`, `profiles` and `drafts`, as the bridge sends it.

    Two details mirror the real bridge exactly: the pre-Shabbat offset lives
    inside `upcoming` under a shorter name, and a profile lists its devices as
    `tokens` that only `device_labels` can translate.
    """
    return {
        "api_version": "1",
        "upcoming": {
            # The live bridge's shape: a local time of day for reading, the
            # full local instant beside it for computing, and the week's
            # portion and Hebrew date from the same integration.
            "parasha": "ראה",
            "hebrew_date": "ט\"ו אלול ה' תשפ\"ו",
            "holiday": "",
            "candle_lighting": "18:52",
            "havdalah": "19:51",
            "candle_lighting_at": "2026-08-28T18:52:00+03:00",
            "havdalah_at": "2026-08-29T19:51:00+03:00",
            "pre_offset_minutes": 20,
        },
        # Each profile carries its own temperatures, as the real bridge does.
        # The same air conditioner appearing in two of them must be reported
        # once, not twice.
        "profiles": {
            "pre_off": {"label": "כיבוי לפני שבת", "active": True, "offset_minutes": 20,
                        "tokens": ["kitchen_light", "living_room_ac"],
                        "ac_temperatures": {"living_room_ac": 24.0, "parents_ac": 23.0}},
            "pre_on": {"label": "הדלקה לפני שבת", "active": True, "offset_minutes": 10,
                       "tokens": ["living_room_light", "garden_light"]},
            "night_off": {"label": "כיבוי לילה", "active": True, "time": "23:30",
                          "tokens": ["living_room_light", "living_room_ac"],
                          "ac_temperatures": {"living_room_ac": 24.0, "girls_ac": 25.5}},
            "morning_on": {"label": "הדלקת בוקר", "active": True, "time": "06:30",
                           "tokens": ["kitchen_light", "boiler"]},
        },
        "drafts": {"user_a": {"has_draft": False}, "user_b": {"has_draft": False}},
        "device_labels": {
            "kitchen_light": "אור מטבח",
            "living_room_light": "אור סלון",
            "garden_light": "אור חצר",
            "living_room_ac": "מזגן סלון",
            "parents_ac": "מזגן הורים",
            "girls_ac": "מזגן חדר בנות",
            "boiler": "דוד",
        },
    }


def rules_payload() -> dict[str, Any]:
    return {
        "api_version": "1",
        "count": 6,
        "rules": [
            {"id": "rule_evening_light", "name": "אור מטבח בערב",
             "description": "מדליק את אור המטבח בשעה 18:00 בימי חול.",
             "enabled": True, "kind": "schedule", "schedule": "18:00 · ראשון–חמישי",
             "targets": ["אור מטבח"], "last_triggered": _iso(hours_ago(14))},
            {"id": "rule_ac_night", "name": "מזגן סלון בלילה",
             "description": "מדליק את מזגן הסלון בערב ומכבה אחרי חצות.",
             "enabled": True, "kind": "schedule", "schedule": "22:00 → 01:00",
             "targets": ["מזגן סלון"], "last_triggered": _iso(hours_ago(11))},
            {"id": "rule_left_on", "name": "מכשיר נשאר דולק",
             "description": "מודיע כשמזגן או אור נשארו דולקים והבית ריק.",
             "enabled": True, "kind": "notification", "trigger": "דולק מעל 4 שעות",
             "targets": ["מזגן סלון", "אור סלון"], "last_triggered": _iso(hours_ago(7))},
            {"id": "rule_meeting", "name": "תזכורת לפני פגישה",
             "description": "שולח תזכורת 30 דקות לפני אירוע ביומן.",
             "enabled": True, "kind": "notification", "trigger": "30 דקות לפני אירוע",
             "targets": ["ינון"], "last_triggered": _iso(hours_ago(2))},
            {"id": "rule_camera", "name": "מצלמה לא משדרת",
             "description": "מודיע כשמצלמה מפסיקה לשדר יותר מ-10 דקות.",
             "enabled": True, "kind": "notification", "trigger": "מצלמה לא זמינה",
             "targets": ["מצלמת ליה", "מצלמת שיה"], "last_triggered": _iso(minutes_ago(120))},
            {"id": "rule_vacuum", "name": "רובי בימי שני",
             "description": "מפעיל את רובי בבוקר יום שני.",
             "enabled": False, "kind": "schedule", "schedule": "10:00 · שני",
             "targets": ["רובי"], "last_triggered": None},
        ],
    }


def tasks_payload() -> dict[str, Any]:
    """Grouped per user, as the bridge sends it."""
    return {
        "api_version": "1",
        "users": [
            {
                "user": "ינון",
                "list_name": "משימות ינון",
                "tasks": [
                    {"uid": "task_1", "summary": "לקבוע תור לרופא", "status": "needs_action",
                     "due": _iso(days_ahead(2))},
                    {"uid": "task_3", "summary": "לשלם ארנונה", "status": "needs_action",
                     "due": _iso(days_ahead(5))},
                    {"uid": "task_4", "summary": "לבדוק את מסנן המזגן",
                     "status": "needs_action"},
                    {"uid": "task_5", "summary": "לחדש ביטוח רכב", "status": "completed"},
                ],
            },
            {
                "user": "הודיה",
                "list_name": "משימות הודיה",
                "tasks": [
                    {"uid": "task_2", "summary": "לקנות חלב וביצים", "status": "needs_action",
                     "due": _iso(days_ahead(1))},
                    {"uid": "task_6", "summary": "לתאם גננת", "status": "completed"},
                ],
            },
        ],
    }


def diagnostics_payload() -> dict[str, Any]:
    """`checks` is a **map**, mixing status words with plain figures."""
    return {
        "api_version": "1",
        "ok": False,
        "issue_count": 3,
        "issues": [
            {
                "severity": "error",
                "code": "device_unavailable",
                "title": "מצלמת ליה אינה זמינה",
                "message": "המצלמה לא משדרת כבר כשעתיים ובובי לא מצליח לצלם ממנה.",
                "component": "device",
                "entity_id": "camera.demo_girls_a",
                "suggested_action": "לנתק ולחבר את שקע המצלמה ולוודא שהיא מופיעה ברשת.",
            },
            {
                "severity": "error",
                "code": "device_unavailable",
                "title": "מצלמת שיה אינה זמינה",
                "message": "גם המצלמה השנייה בחדר הבנות לא משדרת.",
                "component": "device",
                "entity_id": "camera.demo_girls_b",
                "suggested_action": "לבדוק שהמצלמה מקבלת חשמל.",
            },
            {
                "severity": "warning",
                "code": "low_battery",
                "title": "סוללה חלשה בשלט הסלון",
                "message": "רמת הסוללה ירדה מתחת ל-15%.",
                "component": "sensor",
                "entity_id": "sensor.demo_remote_battery",
                "suggested_action": "להחליף את הסוללה בהזדמנות.",
            },
        ],
        "checks": {
            "whatsapp": "WORKING",
            "config": "OK",
            "catalog_count": 18,
            "catalog_controllable": 13,
        },
    }


# --- probe ------------------------------------------------------------------
def probe_payload(text: str) -> dict[str, Any]:
    """A stand-in for Bobi's Skill Dispatcher, nesting its answer under `result`.

    Deliberately simple: enough to exercise every branch the UI renders
    (handled/unhandled, valid/invalid schedule, each skill) without pretending
    to be the real parser.
    """
    import re

    lowered = text.strip()

    time_match = re.search(r"\b(\d{1,2}):(\d{2})\b", lowered)
    clock: str | None = None
    if time_match:
        hour, minute = int(time_match.group(1)), int(time_match.group(2))
        if "בערב" in lowered and hour <= 12:
            hour += 12
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            clock = f"{hour:02d}:{minute:02d}"

    device = next(
        (e for e in _ENTRIES if any(alias in lowered for alias in e["aliases"])),
        None,
    )

    if any(word in lowered for word in ("כבה", "לכבות", "תכבה")):
        action = "turn_off"
    elif any(word in lowered for word in ("תדליק", "הדלק", "להדליק", "תפעיל")):
        action = "turn_on"
    elif any(word in lowered for word in ("מה", "כמה", "מתי", "מי")):
        action = "query"
    elif any(word in lowered for word in ("משימה", "תזכיר")):
        action = "add_task"
    else:
        action = None

    def wrap(result: dict[str, Any]) -> dict[str, Any]:
        return {"api_version": "1", "executed": False, "text": text, "result": result}

    if action == "add_task":
        return wrap({
            "handled": True, "status": "ok", "terminal": True, "skill": "tasks",
            "understanding": {"intent": "add_task", "action": "add", "value": lowered},
        })

    if action == "query":
        understanding: dict[str, Any] = {"intent": "state_query", "action": "read"}
        if device:
            understanding |= {"target": device["canonical"], "area": device["area"],
                              "domain": device["domain"]}
        return wrap({
            "handled": True, "status": "ok", "terminal": True, "skill": "state_query",
            "understanding": understanding,
        })

    if action is None:
        return wrap({
            "handled": False, "status": "not_understood", "terminal": False,
            "skill": None, "understanding": {},
            "schedule_reason": "לא זוהתה כוונה בטקסט",
        })

    understanding = {"intent": "device_control", "action": action}
    if device:
        understanding |= {"target": device["canonical"], "area": device["area"],
                          "domain": device["domain"]}
    if clock:
        understanding["time"] = clock

    if clock:
        # Mirrors the real bridge, which reports a schedule_kind of its own.
        return wrap({
            "handled": True, "status": "ok", "terminal": True, "skill": "local_schedule",
            "understanding": understanding,
            "schedule_valid": True,
            "schedule_reason": f"תוזמן ל-{clock}",
            "schedule_kind": "next_night_clock" if int(clock[:2]) < 6 else "one_time",
        })

    if device is None:
        return wrap({
            "handled": False, "status": "target_not_found", "terminal": False,
            "skill": "device_control", "understanding": understanding,
            "schedule_reason": "לא זוהה מכשיר מתאים",
        })

    return wrap({
        "handled": True, "status": "ok", "terminal": True, "skill": "device_control",
        "understanding": understanding, "schedule_kind": "immediate",
    })
