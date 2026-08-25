"""Mock bridge payloads.

These are shaped exactly like what `script.bobi_cc_*` returns, so the mock
adapter exercises the same models and the same UI code paths as the real one.

Everything here is invented. No real entity id, phone number, or household
detail appears in this file.
"""

from __future__ import annotations

from typing import Any

from app.timeutil import days_ahead, hhmm, hours_ago, minutes_ago, now


def _iso(value) -> str:  # noqa: ANN001 - datetime
    return value.isoformat()


def status_payload() -> dict[str, Any]:
    return {
        "ok": True,
        "version": "bobi-demo-2.0",
        "uptime": "4 ימים",
        "components": [
            {"id": "bobi", "name": "בובי", "state": "online", "label": "פעיל", "ok": True,
             "detail": "מגיב לפקודות כרגיל"},
            {"id": "whatsapp", "name": "WhatsApp", "state": "online", "label": "מחובר", "ok": True,
             "detail": "החיבור יציב מאז אתמול"},
            {"id": "ai", "name": "AI", "state": "online", "label": "פעיל", "ok": True,
             "detail": "נעזר במודל שפה כשצריך"},
            {"id": "home_assistant", "name": "Home Assistant", "state": "degraded",
             "label": "מצב הדגמה", "ok": False,
             "detail": "אין חיבור אמיתי — הנתונים מדומים"},
        ],
        "counts": {
            "devices": 18,
            "capabilities": 14,
            "rules": 6,
            "open_tasks": 4,
            "issues": 3,
        },
        "writes_enabled": False,
    }


def _device(
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


_DEVICES: list[dict[str, Any]] = [
    _device("light.demo_living_room", "אור סלון", "light", "סלון", "on",
            group="תאורה", scopes=["lighting"], aliases=["אור סלון", "האור בסלון"],
            capabilities=["turn_on", "turn_off", "set_brightness"], handler="lighting_handler"),
    _device("light.demo_kitchen", "אור מטבח", "light", "מטבח", "off",
            group="תאורה", scopes=["lighting"], aliases=["אור מטבח", "האור במטבח"],
            capabilities=["turn_on", "turn_off"], handler="lighting_handler", minutes=95),
    _device("light.demo_garden", "אור חצר", "light", "חוץ", "off",
            group="תאורה", scopes=["lighting"], aliases=["אור חצר", "התאורה בחצר"],
            capabilities=["turn_on", "turn_off"], handler="lighting_handler", minutes=300),
    _device("climate.demo_living_room", "מזגן סלון", "climate", "סלון", "off",
            group="מיזוג", scopes=["climate", "temperature"],
            aliases=["מזגן סלון", "המזגן בסלון"],
            capabilities=["turn_on", "turn_off", "set_temperature"], handler="climate_handler",
            limits={"min": 16, "max": 30, "step": 1}, minutes=140),
    _device("climate.demo_parents", "מזגן הורים", "climate", "חדר הורים", "off",
            group="מיזוג", scopes=["climate", "temperature"],
            aliases=["מזגן הורים", "המזגן בחדר הורים"],
            capabilities=["turn_on", "turn_off", "set_temperature"], handler="climate_handler",
            limits={"min": 16, "max": 30, "step": 1}, minutes=620),
    _device("climate.demo_girls", "מזגן חדר בנות", "climate", "חדר בנות", "cool",
            group="מיזוג", scopes=["climate", "temperature"],
            aliases=["מזגן בנות", "המזגן בחדר בנות"],
            capabilities=["turn_on", "turn_off", "set_temperature"], handler="climate_handler",
            limits={"min": 16, "max": 30, "step": 1}, minutes=300),
    _device("camera.demo_entrance", "מצלמת כניסה", "camera", "חוץ", "recording",
            group="מצלמות", scopes=["cameras"], aliases=["מצלמת כניסה"],
            capabilities=["snapshot"], handler="camera_handler", controllable=False, minutes=5),
    _device("camera.demo_girls_a", "מצלמת ליה", "camera", "חדר בנות", "unavailable",
            group="מצלמות", scopes=["cameras"], aliases=["מצלמת ליה"],
            capabilities=["snapshot"], handler="camera_handler", controllable=False, minutes=125),
    _device("camera.demo_girls_b", "מצלמת שיה", "camera", "חדר בנות", "unavailable",
            group="מצלמות", scopes=["cameras"], aliases=["מצלמת שיה"],
            capabilities=["snapshot"], handler="camera_handler", controllable=False, minutes=540),
    _device("switch.demo_boiler", "דוד", "switch", "מטבח", "off",
            group="חשמל", scopes=["switches"], aliases=["דוד", "המים החמים"],
            capabilities=["turn_on", "turn_off", "run_for"], handler="boiler_handler", minutes=240),
    _device("switch.demo_kettle", "קומקום", "switch", "מטבח", "off",
            group="חשמל", scopes=["switches"], aliases=["קומקום"],
            capabilities=["turn_on", "turn_off"], handler="switch_handler", minutes=180),
    _device("switch.demo_scent", "מפיץ ריח", "switch", "סלון", "off",
            group="ריח", scopes=["scent", "switches"], aliases=["מפיץ ריח", "הריח"],
            capabilities=["turn_on", "turn_off"], handler="scent_handler", minutes=400),
    _device("vacuum.demo_robot", "רובי", "vacuum", "מטבח", "docked",
            group="ניקיון", scopes=["vacuum"], aliases=["רובי", "השואב"],
            capabilities=["start", "stop", "return_to_base"], handler="vacuum_handler",
            minutes=1500),
    _device("sensor.demo_outdoor_temp", "טמפרטורה בחוץ", "sensor", "חוץ", "31.2",
            group="חיישנים", scopes=["temperature"], aliases=["טמפרטורה בחוץ"],
            capabilities=["read"], handler="sensor_handler", controllable=False, minutes=6),
    _device("sensor.demo_living_room_humidity", "לחות בסלון", "sensor", "סלון", "48",
            group="חיישנים", scopes=["humidity"], aliases=["לחות בסלון"],
            capabilities=["read"], handler="sensor_handler", controllable=False, minutes=9),
    _device("sensor.demo_remote_battery", "סוללת שלט", "sensor", "סלון", "12",
            group="חיישנים", scopes=["battery"], aliases=["סוללת שלט"],
            capabilities=["read"], handler="sensor_handler", controllable=False, minutes=60),
    _device("person.demo_a", "ינון", "person", "בית", "home",
            group="אנשים", scopes=["people"], aliases=["ינון"],
            capabilities=["read"], handler="presence_handler", controllable=False, minutes=45),
    _device("person.demo_b", "הודיה", "person", "בית", "not_home",
            group="אנשים", scopes=["people"], aliases=["הודיה"],
            capabilities=["read"], handler="presence_handler", controllable=False, minutes=200),
]


def devices_payload(scope: str = "all", include_unavailable: bool = True) -> dict[str, Any]:
    """Filter the catalog the way the bridge does, server-side."""
    devices = _DEVICES
    if scope != "all":
        devices = [d for d in devices if scope in d["semantic_scopes"]]
    if not include_unavailable:
        devices = [d for d in devices if d["state"] not in {"unavailable", "unknown"}]
    return {
        "scope": scope,
        "include_unavailable": include_unavailable,
        "count": len(devices),
        "devices": devices,
    }


def _capability(
    cap_id: str,
    label: str,
    example: str,
    handler: str,
    risk: str,
    group: str,
    *,
    local: bool = True,
    local_after_parse: bool = False,
) -> dict[str, Any]:
    return {
        "id": cap_id,
        "handler": handler,
        "local": local,
        "local_after_parse": local_after_parse,
        "risk": risk,
        "label": label,
        "example": example,
        "group": group,
    }


def capabilities_payload() -> dict[str, Any]:
    capabilities = [
        _capability("lighting", "שליטה בתאורה", "תדליק את אור הסלון",
                    "lighting_handler", "low", "שליטה בבית"),
        _capability("climate", "שליטה במזגנים", "תכבה את המזגן בסלון",
                    "climate_handler", "low", "שליטה בבית"),
        _capability("boiler", "הפעלת דוד", "תדליק את הדוד לחצי שעה",
                    "boiler_handler", "medium", "שליטה בבית"),
        _capability("scent", "מפיץ ריח", "תפעיל את מפיץ הריח",
                    "scent_handler", "low", "שליטה בבית"),
        _capability("vacuum", "הפעלת רובי", "תשלח את רובי לנקות את המטבח",
                    "vacuum_handler", "medium", "שליטה בבית"),
        _capability("cameras", "צילום ממצלמה", "תצלם את מצלמת הכניסה",
                    "camera_handler", "high", "שליטה בבית"),
        _capability("covers", "תריסים", "תסגור את תריס הסלון",
                    "cover_handler", "medium", "שליטה בבית"),
        _capability("schedule", "תזמונים", "כבה את המזגן ב-1:30 בלילה",
                    "schedule_handler", "medium", "זמן ותזמון",
                    local_after_parse=True),
        _capability("shabbat", "שעון שבת", "מתי כניסת שבת",
                    "shabbat_handler", "low", "זמן ותזמון"),
        _capability("calendar", "יומן", "מה יש לי מחר ביומן",
                    "calendar_handler", "low", "זמן ותזמון"),
        _capability("tasks", "משימות", "תוסיף משימה לקנות חלב",
                    "tasks_handler", "low", "זמן ותזמון"),
        _capability("state_query", "שאלות על הבית", "מה הטמפרטורה בסלון",
                    "query_handler", "low", "מידע"),
        _capability("presence", "מי בבית", "מי נמצא בבית עכשיו",
                    "presence_handler", "low", "מידע"),
        _capability("notifications", "התראות יזומות", "תודיע לי כשהכביסה נגמרת",
                    "notify_handler", "low", "תקשורת"),
        _capability("ai_fallback", "AI fallback", "שאלה חופשית שבובי לא מזהה",
                    "ai_handler", "medium", "בינה מלאכותית",
                    local=False, local_after_parse=True),
        _capability("vision", "עיבוד תמונות", "מה רואים בתמונה הזו",
                    "vision_handler", "high", "בינה מלאכותית", local=False),
    ]
    toggles = [
        {"id": "master_notifications", "name": "התראות יזומות", "label": "התראות יזומות",
         "state": "on", "enabled": True, "entity_id": "input_boolean.demo_notifications"},
        {"id": "master_ai", "name": "AI fallback", "label": "AI fallback",
         "state": "on", "enabled": True, "entity_id": "input_boolean.demo_ai"},
        {"id": "master_vision", "name": "עיבוד תמונות", "label": "עיבוד תמונות",
         "state": "off", "enabled": False, "entity_id": "input_boolean.demo_vision"},
        {"id": "master_shabbat", "name": "שעון שבת", "label": "שעון שבת",
         "state": "on", "enabled": True, "entity_id": "input_boolean.demo_shabbat"},
    ]
    return {"count": len(capabilities), "capabilities": capabilities, "toggles": toggles}


def users_payload() -> dict[str, Any]:
    """No phone numbers, no LIDs — matching what the bridge withholds."""
    return {
        "count": 2,
        "users": [
            {
                "id": "user_a",
                "name": "ינון",
                "role": "admin",
                "enabled": True,
                "whatsapp_connected": True,
                "calendar": "יומן ינון",
                "task_list": "משימות ינון",
                "permissions": ["control_devices", "manage_automations", "manage_shabbat",
                                "manage_tasks", "manage_calendar", "view_cameras", "manage_bobi"],
                "areas": ["סלון", "מטבח", "חדר הורים", "חוץ"],
            },
            {
                "id": "user_b",
                "name": "הודיה",
                "role": "member",
                "enabled": True,
                "whatsapp_connected": True,
                "calendar": "יומן משפחה",
                "task_list": "משימות הודיה",
                "permissions": ["control_devices", "manage_shabbat", "manage_tasks",
                                "manage_calendar", "view_cameras"],
                "areas": ["סלון", "מטבח", "חדר בנות"],
            },
        ],
    }


def shabbat_payload() -> dict[str, Any]:
    return {
        "candle_lighting": "18:52",
        "havdalah": "19:51",
        "pre_shabbat_offset_minutes": 20,
        "pre_off_profile": {
            "id": "pre_off_default", "name": "כיבוי לפני שבת", "label": "כיבוי לפני שבת",
            "active": True, "devices": ["kitchen_light", "living_room_ac"],
            "offset_minutes": 20,
        },
        "pre_on_profile": {
            "id": "pre_on_default", "name": "הדלקה לפני שבת", "label": "הדלקה לפני שבת",
            "active": True, "devices": ["living_room_light", "garden_light"],
            "offset_minutes": 10,
        },
        "night_off_profile": {
            "id": "night_off", "name": "כיבוי לילה", "label": "כיבוי לילה",
            "active": True, "devices": ["living_room_light", "living_room_ac"], "time": "23:30",
        },
        "morning_on_profile": {
            "id": "morning_on", "name": "הדלקת בוקר", "label": "הדלקת בוקר",
            "active": True, "devices": ["kitchen_light", "boiler"], "time": "06:30",
        },
        "ac_temperatures": {"living_room_ac": 24, "parents_ac": 23, "girls_ac": 24},
        "device_labels": {
            "kitchen_light": "אור מטבח",
            "living_room_light": "אור סלון",
            "garden_light": "אור חצר",
            "living_room_ac": "מזגן סלון",
            "parents_ac": "מזגן הורים",
            "girls_ac": "מזגן חדר בנות",
            "boiler": "דוד",
        },
        "has_draft": False,
        "writes_enabled": False,
    }


def rules_payload() -> dict[str, Any]:
    return {
        "count": 6,
        "rules": [
            {"id": "rule_evening_light", "name": "אור מטבח בערב", "label": "אור מטבח בערב",
             "description": "מדליק את אור המטבח בשעה 18:00 בימי חול.",
             "enabled": True, "kind": "schedule", "schedule": "18:00 · ראשון–חמישי",
             "targets": ["אור מטבח"], "last_triggered": _iso(hours_ago(14))},
            {"id": "rule_ac_night", "name": "מזגן סלון בלילה", "label": "מזגן סלון בלילה",
             "description": "מדליק את מזגן הסלון בערב ומכבה אחרי חצות.",
             "enabled": True, "kind": "schedule", "schedule": "22:00 → 01:00",
             "targets": ["מזגן סלון"], "last_triggered": _iso(hours_ago(11))},
            {"id": "rule_left_on", "name": "מכשיר נשאר דולק", "label": "מכשיר נשאר דולק",
             "description": "מודיע כשמזגן או אור נשארו דולקים והבית ריק.",
             "enabled": True, "kind": "notification", "trigger": "דולק מעל 4 שעות",
             "targets": ["מזגן סלון", "אור סלון"], "last_triggered": _iso(hours_ago(7))},
            {"id": "rule_meeting", "name": "תזכורת לפני פגישה", "label": "תזכורת לפני פגישה",
             "description": "שולח תזכורת 30 דקות לפני אירוע ביומן.",
             "enabled": True, "kind": "notification", "trigger": "30 דקות לפני אירוע",
             "targets": ["ינון"], "last_triggered": _iso(hours_ago(2))},
            {"id": "rule_camera", "name": "מצלמה לא משדרת", "label": "מצלמה לא משדרת",
             "description": "מודיע כשמצלמה מפסיקה לשדר יותר מ-10 דקות.",
             "enabled": True, "kind": "notification", "trigger": "מצלמה לא זמינה",
             "targets": ["מצלמת ליה", "מצלמת שיה"], "last_triggered": _iso(minutes_ago(120))},
            {"id": "rule_vacuum", "name": "רובי בימי שני", "label": "רובי בימי שני",
             "description": "מפעיל את רובי בבוקר יום שני.",
             "enabled": False, "kind": "schedule", "schedule": "10:00 · שני",
             "targets": ["רובי"], "last_triggered": None},
        ],
    }


def tasks_payload() -> dict[str, Any]:
    return {
        "count": 6,
        "tasks": [
            {"id": "task_1", "title": "לקבוע תור לרופא", "status": "needs_action",
             "completed": False, "due": _iso(days_ahead(2)), "owner": "ינון",
             "list_name": "משימות ינון"},
            {"id": "task_2", "title": "לקנות חלב וביצים", "status": "needs_action",
             "completed": False, "due": _iso(days_ahead(1)), "owner": "הודיה",
             "list_name": "משימות הודיה"},
            {"id": "task_3", "title": "לשלם ארנונה", "status": "needs_action",
             "completed": False, "due": _iso(days_ahead(5)), "owner": "ינון",
             "list_name": "משימות ינון"},
            {"id": "task_4", "title": "לבדוק את מסנן המזגן", "status": "needs_action",
             "completed": False, "due": None, "owner": "ינון", "list_name": "משימות ינון"},
            {"id": "task_5", "title": "לחדש ביטוח רכב", "status": "completed",
             "completed": True, "due": None, "owner": "ינון", "list_name": "משימות ינון"},
            {"id": "task_6", "title": "לתאם גננת", "status": "completed",
             "completed": True, "due": None, "owner": "הודיה", "list_name": "משימות הודיה"},
        ],
    }


def diagnostics_payload() -> dict[str, Any]:
    return {
        "ok": False,
        "issue_count": 3,
        "issues": [
            {
                "id": "issue_camera_a", "severity": "error",
                "title": "מצלמת ליה אינה זמינה",
                "message": "המצלמה לא משדרת כבר כשעתיים ובובי לא מצליח לצלם ממנה.",
                "component": "מצלמות",
                "entity_id": "camera.demo_girls_a",
                "suggested_action": "לנתק ולחבר את שקע המצלמה ולוודא שהיא מופיעה ברשת.",
                "detail": "state=unavailable · retries=14 · last_error=ConnectTimeout",
            },
            {
                "id": "issue_camera_b", "severity": "error",
                "title": "מצלמת שיה אינה זמינה",
                "message": "גם המצלמה השנייה בחדר הבנות לא משדרת.",
                "component": "מצלמות",
                "entity_id": "camera.demo_girls_b",
                "suggested_action": "לבדוק שהמצלמה מקבלת חשמל.",
                "detail": "state=unavailable · last_seen=01:58",
            },
            {
                "id": "issue_battery", "severity": "warning",
                "title": "סוללה חלשה בשלט הסלון",
                "message": "רמת הסוללה ירדה מתחת ל-15%.",
                "component": "חיישנים",
                "entity_id": "sensor.demo_remote_battery",
                "suggested_action": "להחליף את הסוללה בהזדמנות.",
                "detail": "state=12 · unit=%",
            },
        ],
        "checks": [
            {"id": "check_bridge", "name": "גשר בובי", "label": "גשר בובי", "ok": True,
             "detail": "כל סקריפטי הגשר זמינים"},
            {"id": "check_whatsapp", "name": "WhatsApp", "label": "WhatsApp", "ok": True,
             "detail": "מחובר"},
            {"id": "check_entities", "name": "מכשירים", "label": "מכשירים", "ok": False,
             "detail": "2 מכשירים אינם זמינים"},
            {"id": "check_schedules", "name": "תזמונים", "label": "תזמונים", "ok": True,
             "detail": "כל התזמונים תקינים"},
            {"id": "check_shabbat", "name": "שעון שבת", "label": "שעון שבת", "ok": True,
             "detail": "פרופילים טעונים"},
        ],
    }


# --- probe ------------------------------------------------------------------
_HEBREW_DIGITS = {"אחת": 1, "שתיים": 2, "שלוש": 3, "ארבע": 4, "חמש": 5,
                  "שש": 6, "שבע": 7, "שמונה": 8, "תשע": 9, "עשר": 10}


def probe_payload(text: str) -> dict[str, Any]:
    """A small stand-in for Bobi's Skill Dispatcher running probe-only.

    Deliberately simple: enough to exercise every branch the UI renders
    (handled/unhandled, valid/invalid schedule, each skill) without pretending
    to be the real parser.
    """
    import re

    lowered = text.strip()
    understanding: dict[str, Any] = {}

    time_match = re.search(r"\b(\d{1,2}):(\d{2})\b", lowered)
    clock: str | None = None
    if time_match:
        hour, minute = int(time_match.group(1)), int(time_match.group(2))
        if "בערב" in lowered and hour <= 12:
            hour += 12
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            clock = f"{hour:02d}:{minute:02d}"

    device = next(
        (d for d in _DEVICES
         if any(alias in lowered for alias in d["aliases"])),
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

    if action == "add_task":
        return {
            "handled": True, "status": "ok", "terminal": True, "skill": "tasks",
            "understanding": {"intent": "add_task", "action": "add", "value": lowered},
            "schedule_valid": None, "schedule_reason": None, "schedule_kind": None,
            "text": text,
        }

    if action == "query":
        understanding = {"intent": "state_query", "action": "read"}
        if device:
            understanding["target"] = device["canonical"]
            understanding["area"] = device["area"]
            understanding["domain"] = device["domain"]
        return {
            "handled": True, "status": "ok", "terminal": True, "skill": "state_query",
            "understanding": understanding,
            "schedule_valid": None, "schedule_reason": None, "schedule_kind": None,
            "text": text,
        }

    if action is None:
        return {
            "handled": False, "status": "not_understood", "terminal": False,
            "skill": None, "understanding": {},
            "schedule_valid": None,
            "schedule_reason": "לא זוהתה כוונה בטקסט",
            "schedule_kind": None,
            "text": text,
        }

    understanding = {"intent": "device_control", "action": action}
    if device:
        understanding["target"] = device["canonical"]
        understanding["area"] = device["area"]
        understanding["domain"] = device["domain"]
    if clock:
        understanding["time"] = clock

    if clock:
        return {
            "handled": True, "status": "ok", "terminal": True, "skill": "local_schedule",
            "understanding": understanding,
            "schedule_valid": True,
            "schedule_reason": f"תוזמן ל-{clock}",
            "schedule_kind": "one_time",
            "text": text,
        }

    if device is None:
        return {
            "handled": False, "status": "target_not_found", "terminal": False,
            "skill": "device_control", "understanding": understanding,
            "schedule_valid": None,
            "schedule_reason": "לא זוהה מכשיר מתאים",
            "schedule_kind": None,
            "text": text,
        }

    return {
        "handled": True, "status": "ok", "terminal": True, "skill": "device_control",
        "understanding": understanding,
        "schedule_valid": None, "schedule_reason": None, "schedule_kind": "immediate",
        "text": text,
    }


def current_clock() -> str:
    return hhmm(now())
