"""An in-memory stand-in for the Home Assistant write bridge — wired to nothing.

This is a **test double**, not a mode of the application. Neither adapter
returns it from `management_bridge()`, so no running instance uses it. It exists
so the preview → confirm → commit → verify flow can be tested end to end, and it
mimics the real contract closely enough to be worth trusting: the same operation
names, the same `expected_*` comparison, the same `stale_preview` and
`already_in_state` reasons, and the same master switch that defaults to **off**.

That last part matters. `writes_enabled` starts `False` here exactly as it does
in the live install, so the default test is the safe one and enabling it has to
be deliberate.
"""

from __future__ import annotations

import copy
import secrets
from typing import Any

from app.adapters.management import UNAVAILABLE_MESSAGE, ManagementBridge
from app.errors import BobiError
from app.models.manage import (
    BridgeOutcome,
    ManagedOperation,
    ManagedTarget,
    ManagementResource,
    ManagementStatus,
    ObservedState,
    ResourceSnapshot,
    SnapshotTask,
    TaskSnapshot,
)
from app.services.resource_normalize import normalize_resource, unavailable
from app.services.resources import SPECS, VALUELESS_OPERATIONS, canonical_operation

_OPEN = "needs_action"
_COMPLETED = "completed"

#: Stands where a phone number or a LID would be in real bridge data. Nothing
#: may echo it back: if this string ever appears in a response, an audit line or
#: a log, the redaction has a hole in it.
PRIVATE_CANARY = "MUST-NOT-APPEAR"


# --- the 3.0 families -------------------------------------------------------
# Raw bridge payloads, deliberately in the shape a `bobi_cc_*_snapshot` service
# answers rather than in the normalized shape — so every test that touches a
# family exercises the normalizer too, and a change there cannot pass unnoticed.
DEFAULT_RESOURCE_PAYLOADS: dict[str, dict[str, Any]] = {
    "settings": {
        "available": True,
        "groups": [
            {
                "id": "morning",
                "label": "סיכום בוקר",
                "items": [
                    {
                        "id": "morning_enabled",
                        "label": "סיכום בוקר אוטומטי",
                        "kind": "toggle",
                        "value": True,
                        "controllable": True,
                        "operations": ["set"],
                        "risk": "low",
                    },
                    {
                        "id": "morning_time",
                        "label": "שעת שליחה",
                        "kind": "time",
                        "value": "07:00",
                        "controllable": True,
                        "operations": ["set"],
                        "risk": "low",
                    },
                    {
                        "id": "morning_user_1",
                        "label": "נמען — ינון",
                        "kind": "toggle",
                        "value": True,
                        "controllable": True,
                        "operations": ["set"],
                    },
                    {
                        "id": "morning_user_2",
                        "label": "נמען — הודיה",
                        "kind": "toggle",
                        "value": False,
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
                        "id": "home_status_policy",
                        "label": "מתי לשלוח",
                        "kind": "choice",
                        "value": "away_only",
                        "controllable": True,
                        "operations": ["set"],
                        "options": [
                            {"value": "away_only", "label": "רק כשאין אף אחד בבית"},
                            {"value": "always", "label": "תמיד"},
                        ],
                    },
                    {
                        "id": "home_status_first_time",
                        "label": "שליחה ראשונה",
                        "kind": "time",
                        "value": "13:00",
                        "controllable": True,
                        "operations": ["set"],
                    },
                ],
            },
            {
                "id": "ai",
                "label": "בינה מלאכותית",
                "items": [
                    {
                        "id": "ai_enabled",
                        "label": "בובי AI",
                        "kind": "toggle",
                        "value": True,
                        "controllable": True,
                        "operations": ["set"],
                        "risk": "medium",
                    },
                    {
                        "id": "ai_monthly_cap",
                        "label": "תקרת עלות חודשית",
                        "kind": "number",
                        "value": 20,
                        "controllable": True,
                        "operations": ["set"],
                        "risk": "medium",
                        "constraints": {"min": 0, "max": 200, "step": 5, "unit": "$"},
                    },
                ],
            },
            {
                "id": "notifications",
                "label": "התראות חכמות",
                "items": [
                    {
                        "id": "smart_notifications",
                        "label": "התראות חכמות",
                        "kind": "toggle",
                        "value": True,
                        "controllable": True,
                        "operations": ["set"],
                        "notification_class": "master",
                    },
                    {
                        "id": "notify_bedtime",
                        "label": "התראת שינה",
                        "kind": "toggle",
                        "value": False,
                        "controllable": True,
                        "operations": ["set"],
                        "notification_class": "smart",
                    },
                    {
                        "id": "notify_bedtime_recipients",
                        "label": "נמעני התראת שינה",
                        "kind": "choice",
                        "value": "both",
                        "controllable": True,
                        "operations": ["set"],
                        "notification_class": "smart",
                        "options": [
                            {"value": "user_1", "label": "ינון בלבד"},
                            {"value": "user_2", "label": "הודיה בלבד"},
                            {"value": "both", "label": "שניהם"},
                        ],
                    },
                    {
                        "id": "notify_low_battery",
                        "label": "סוללה חלשה",
                        "kind": "toggle",
                        "value": True,
                        "controllable": True,
                        "operations": ["set"],
                        "notification_class": "system",
                    },
                ],
            },
        ],
    },
    "users": {
        "available": True,
        "items": [
            {
                "id": "user_1",
                "label": "ינון",
                "kind": "toggle",
                "value": True,
                "controllable": True,
                "operations": ["set", "disable", "set_role", "rename", "set_phone"],
                "risk": "medium",
                "role": "admin",
                "enabled": True,
                "whatsapp_configured": True,
                "phone_masked": "•••• ••• 42",
                "calendar_configured": True,
                "task_list_configured": True,
                # Deliberately present, and deliberately never surfaced. The
                # value is a canary rather than a plausible number: the
                # redaction is by key name, so the shape does not matter, and a
                # test can assert this exact string reaches no response, no
                # audit line and no log.
                "phone": PRIVATE_CANARY,
                "lid": f"{PRIVATE_CANARY}@lid",
            },
            {
                "id": "user_2",
                "label": "הודיה",
                "kind": "toggle",
                "value": True,
                "controllable": True,
                "operations": ["set", "disable", "set_role", "rename", "set_phone"],
                "risk": "medium",
                "role": "member",
                "enabled": True,
                "whatsapp_configured": True,
                "phone_masked": "•••• ••• 17",
                "calendar_configured": True,
                "task_list_configured": False,
                "phone": PRIVATE_CANARY,
            },
        ],
    },
    # The live bridge's shape: one group per profile, dotted item ids, a
    # `multi_select` device list whose choices live in `options`, and a
    # temperature per air conditioner belonging to the profile that turns it
    # on. The double used to publish three groups of its own invention —
    # timing, profiles, temperatures — and a screen written against the real
    # thing engaged with none of it.
    "shabbat": {
        "available": True,
        "groups": [
            {
                "id": "timing",
                "label": "זמנים",
                "items": [
                    {
                        "id": "pre_shabbat_offset_minutes",
                        "label": "הכנת ערב שבת",
                        "kind": "number",
                        "value": 30,
                        "risk": "medium",
                        "controllable": True,
                        "operations": ["set"],
                        "constraints": {"minimum": 0, "maximum": 120, "step": 5,
                                        "unit": "דקות"},
                    },
                    {
                        "id": "alert_enabled",
                        "label": "התראת בובי לפני שבת",
                        "kind": "boolean",
                        "value": True,
                        "risk": "low",
                        "controllable": True,
                        "operations": ["set"],
                    },
                    {
                        "id": "night_off_time",
                        "label": "כיבוי ליל שבת",
                        "kind": "time",
                        "value": "23:15",
                        "risk": "medium",
                        "controllable": True,
                        "operations": ["set"],
                    },
                    {
                        "id": "morning_on_time",
                        "label": "הדלקת שבת בבוקר",
                        "kind": "time",
                        "value": "09:30",
                        "risk": "medium",
                        "controllable": True,
                        "operations": ["set"],
                    },
                    # The two added clocks keep their switch and their hour
                    # with the other times, and the profile card claims both so
                    # neither is shown twice.
                    {
                        "id": "extra_off_enabled",
                        "label": "שעון כיבוי נוסף",
                        "kind": "boolean",
                        "value": False,
                        "risk": "medium",
                        "controllable": True,
                        "operations": ["set"],
                    },
                    {
                        "id": "extra_off_time",
                        "label": "שעת הכיבוי הנוסף",
                        "kind": "time",
                        "value": "00:00",
                        "risk": "medium",
                        "controllable": True,
                        "operations": ["set"],
                    },
                ],
            },
            {
                "id": "pre_off",
                "label": "לפני שבת — כיבוי",
                "items": [
                    {
                        "id": "profile.pre_off.devices",
                        "label": "מכשירים לכיבוי",
                        "kind": "multi_select",
                        "value": ["dining", "salon", "boiler", "ac_salon"],
                        "risk": "medium",
                        "controllable": True,
                        "operations": ["set"],
                        "options": [
                            {"value": "dining", "label": "פינת אוכל"},
                            {"value": "salon", "label": "אור סלון"},
                            {"value": "kitchen", "label": "מטבח"},
                            {"value": "led_salon", "label": "לד סלון"},
                            {"value": "boiler", "label": "דוד"},
                            {"value": "ac_salon", "label": "מזגן סלון"},
                            {"value": "ac_parents", "label": "מזגן הורים"},
                        ],
                    },
                ],
            },
            {
                "id": "pre_on",
                "label": "לפני שבת — הדלקה",
                "items": [
                    {
                        "id": "profile.pre_on.devices",
                        "label": "מכשירים להדלקה",
                        "kind": "multi_select",
                        "value": ["dining", "kitchen", "led_salon", "ac_salon"],
                        "risk": "medium",
                        "controllable": True,
                        "operations": ["set"],
                        "options": [
                            {"value": "dining", "label": "פינת אוכל"},
                            {"value": "salon", "label": "אור סלון"},
                            {"value": "kitchen", "label": "מטבח"},
                            {"value": "led_salon", "label": "לד סלון"},
                            {"value": "boiler", "label": "דוד"},
                            {"value": "ac_salon", "label": "מזגן סלון"},
                            {"value": "ac_parents", "label": "מזגן הורים"},
                        ],
                    },
                    {
                        "id": "profile.pre_on.ac_salon",
                        "label": "מזגן סלון",
                        "kind": "number",
                        "value": 24,
                        "risk": "medium",
                        "controllable": True,
                        "operations": ["set"],
                        "constraints": {"minimum": 16, "maximum": 30, "step": 0.5,
                                         "unit": "°C"},
                    },
                    # A device with more than one setting names each one after
                    # itself — two items cannot share an id — and all of them
                    # still belong to `ac_salon`. The live bridge publishes
                    # these three per air conditioner in each on-profile; a
                    # double carrying only the temperature is how the screen
                    # came to be tested against a payload no bridge sends.
                    {
                        "id": "profile.pre_on.ac_salon.hvac_mode",
                        "label": "מצב הפעלה",
                        "kind": "choice",
                        "value": "cool",
                        "risk": "medium",
                        "controllable": True,
                        "operations": ["set"],
                        "options": ["cool", "heat", "dry", "fan_only", "auto"],
                    },
                    {
                        "id": "profile.pre_on.ac_salon.fan_mode",
                        "label": "עוצמת מאוורר",
                        "kind": "choice",
                        "value": "auto",
                        "risk": "medium",
                        "controllable": True,
                        "operations": ["set"],
                        "options": ["auto", "silent", "low", "medium", "high", "full"],
                    },
                    {
                        "id": "profile.pre_on.ac_salon.swing_mode",
                        "label": "הנפה",
                        "kind": "choice",
                        "value": "off",
                        "risk": "medium",
                        "controllable": True,
                        "operations": ["set"],
                        "options": ["off", "vertical", "horizontal", "both"],
                    },
                    {
                        "id": "profile.pre_on.ac_parents",
                        "label": "מזגן הורים",
                        "kind": "number",
                        "value": 23,
                        "risk": "medium",
                        "controllable": True,
                        "operations": ["set"],
                        "constraints": {"minimum": 16, "maximum": 30, "step": 0.5,
                                         "unit": "°C"},
                    },
                ],
            },
            # A clock the household added. It carries only a device list —
            # its switch and its hour live with the other times, and the card
            # claims them. An added on-clock deliberately has no air
            # conditioner settings of its own: the bridge only turns the unit
            # on and leaves whatever it was set to.
            {
                "id": "extra_off",
                "label": "שעון נוסף — כיבוי",
                "items": [
                    {
                        "id": "profile.extra_off.devices",
                        "label": "מכשירים לכיבוי",
                        "kind": "multi_select",
                        "value": [],
                        "risk": "medium",
                        "controllable": True,
                        "operations": ["set"],
                        "options": [
                            {"value": "dining", "label": "פינת אוכל"},
                            {"value": "salon", "label": "אור סלון"},
                            {"value": "kitchen", "label": "מטבח"},
                            {"value": "led_salon", "label": "לד סלון"},
                            {"value": "boiler", "label": "דוד"},
                            {"value": "ac_salon", "label": "מזגן סלון"},
                            {"value": "ac_parents", "label": "מזגן הורים"},
                        ],
                    },
                ],
            },
            {
                "id": "night_off",
                "label": "ליל שבת — כיבוי",
                "items": [
                    {
                        "id": "profile.night_off.devices",
                        "label": "מכשירים לכיבוי",
                        "kind": "multi_select",
                        "value": ["dining", "salon", "kitchen", "led_salon"],
                        "risk": "medium",
                        "controllable": True,
                        "operations": ["set"],
                        "options": [
                            {"value": "dining", "label": "פינת אוכל"},
                            {"value": "salon", "label": "אור סלון"},
                            {"value": "kitchen", "label": "מטבח"},
                            {"value": "led_salon", "label": "לד סלון"},
                            {"value": "boiler", "label": "דוד"},
                            {"value": "ac_salon", "label": "מזגן סלון"},
                            {"value": "ac_parents", "label": "מזגן הורים"},
                        ],
                    },
                ],
            },
            {
                "id": "morning_on",
                "label": "שבת בבוקר — הדלקה",
                "items": [
                    {
                        "id": "profile.morning_on.devices",
                        "label": "מכשירים להדלקה",
                        "kind": "multi_select",
                        "value": ["dining", "salon", "kitchen"],
                        "risk": "medium",
                        "controllable": True,
                        "operations": ["set"],
                        "options": [
                            {"value": "dining", "label": "פינת אוכל"},
                            {"value": "salon", "label": "אור סלון"},
                            {"value": "kitchen", "label": "מטבח"},
                            {"value": "led_salon", "label": "לד סלון"},
                            {"value": "boiler", "label": "דוד"},
                            {"value": "ac_salon", "label": "מזגן סלון"},
                            {"value": "ac_parents", "label": "מזגן הורים"},
                        ],
                    },
                    {
                        "id": "profile.morning_on.ac_salon",
                        "label": "מזגן סלון",
                        "kind": "number",
                        "value": 24,
                        "risk": "medium",
                        "controllable": True,
                        "operations": ["set"],
                        "constraints": {"minimum": 16, "maximum": 30, "step": 0.5,
                                         "unit": "°C"},
                    },
                    {
                        "id": "profile.morning_on.ac_parents",
                        "label": "מזגן הורים",
                        "kind": "number",
                        "value": 23,
                        "risk": "medium",
                        "controllable": True,
                        "operations": ["set"],
                        "constraints": {"minimum": 16, "maximum": 30, "step": 0.5,
                                         "unit": "°C"},
                    },
                ],
            },
        ],
    },
    "rules": {
        "available": True,
        "items": [
            {
                "id": "rule_1",
                "label": "אור מטבח בערב",
                "kind": "toggle",
                "value": True,
                "controllable": True,
                "operations": ["edit", "disable", "delete"],
                "rule_type": "weekly",
                "days": ["tue"],
                "time": "06:00",
                "action": "להדליק את הדוד",
                "version": 3,
            },
            {
                "id": "rule_2",
                "label": "רובי בימי שני",
                "kind": "toggle",
                "value": False,
                "controllable": True,
                "operations": ["edit", "enable", "delete"],
                "rule_type": "once",
                "next_due": "2026-09-01T20:00:00",
                "action": "לשלוח תזכורת",
                "version": 1,
            },
        ],
    },
    "calendar": {
        "available": True,
        # Which calendars an event may be created in. The family's `create`
        # is aimed at one of these, not at an event.
        "targets": [
            {"id": "user_1", "label": "ינון"},
            {"id": "user_2", "label": "הודיה"},
        ],
        "items": [
            {
                "id": "evt_1",
                "label": "פגישת הורים",
                "kind": "readonly",
                "value": "2026-09-02T18:00:00",
                # An existing event carries no verb, and this double says so
                # because the live bridge does. Home Assistant publishes no
                # service that edits, moves or deletes a calendar event — that
                # path is websocket-only — so advertising the three here made
                # this double describe a system nobody could build.
                "controllable": False,
                "operations": [],
                "user_id": "user_1",
                "start": "2026-09-02T18:00:00",
                "end": "2026-09-02T19:00:00",
                "location": "בית הספר",
                "recurring": False,
            }
        ],
    },
    "devices": {
        "available": True,
        "items": [
            {
                "id": "kitchen",
                "label": "מטבח",
                "kind": "toggle",
                "value": False,
                "controllable": True,
                "operations": ["set"],
                "device_class": "light",
                "capabilities": ["on_off", "brightness"],
                "entity_id": "light.kitchen",
                "constraints": {"min": 1, "max": 100, "step": 1, "unit": "%"},
            },
            # A light that is off, and its brightness beside it. The live bridge
            # used to publish this pair as `controllable: false, operations: []`
            # whenever the light was off — the reading really is absent then —
            # and the effect was that no light in the house could ever be turned
            # on *at* a brightness. You turned it on, waited for the next poll,
            # and only then got a slider.
            #
            # `light.turn_on` carries brightness in the same call, so the
            # capability was never the thing that was missing; only the reading
            # was. The bridge now publishes the control with a value of nothing,
            # and the commit binds an expected of nothing to a light that is off.
            # Both halves are mirrored here so the screen is tested against what
            # Home Assistant actually sends.
            {
                "id": "led_salon",
                "label": "לד סלון",
                "kind": "toggle",
                "value": False,
                "controllable": True,
                "operations": ["power"],
                "device_class": "light",
                "capabilities": ["on_off", "brightness"],
                "entity_id": "light.led_salon",
            },
            {
                "id": "led_salon_brightness",
                "label": "לד סלון — בהירות",
                "kind": "number",
                "value": None,
                "controllable": True,
                "operations": ["brightness"],
                "device_class": "light",
                "constraints": {"min": 1, "max": 255, "step": 1},
                "entity_id": "light.led_salon",
            },
            # The live shape: a device's switch is one item and each capability
            # is another, named `<device>_<capability>`. The double published a
            # single number per air conditioner, so the sheet that gathers a
            # device's controls had nothing to gather and every mode, fan speed
            # and swing setting in the house was unreachable from the screen.
            {
                "id": "ac_salon",
                "label": "מזגן סלון",
                "kind": "toggle",
                "value": True,
                "display": "cool",
                "controllable": True,
                "operations": ["power"],
                "device_class": "climate",
                "capabilities": ["on_off", "temperature", "hvac_mode", "fan_mode"],
                "entity_id": "climate.ac_salon",
            },
            {
                "id": "ac_salon_temperature",
                "label": "מזגן סלון — טמפרטורת יעד",
                "kind": "number",
                "value": 24,
                "controllable": True,
                "operations": ["temperature"],
                "device_class": "climate",
                "constraints": {"min": 16, "max": 30, "step": 0.5, "unit": "°C"},
                "entity_id": "climate.ac_salon",
            },
            {
                "id": "ac_salon_hvac_mode",
                "label": "מזגן סלון — מצב הפעלה",
                "kind": "choice",
                "value": "cool",
                "controllable": True,
                "operations": ["hvac_mode"],
                "device_class": "climate",
                "options": ["off", "auto", "cool", "dry", "heat", "fan_only"],
                "entity_id": "climate.ac_salon",
            },
            {
                "id": "ac_salon_fan_mode",
                "label": "מזגן סלון — עוצמת מאוורר",
                "kind": "choice",
                "value": "auto",
                "controllable": True,
                "operations": ["fan_mode"],
                "device_class": "climate",
                "options": ["silent", "low", "medium", "high", "auto"],
                "entity_id": "climate.ac_salon",
            },
            # The live vocabulary, with no `set` to fall back on. This house
            # names one verb per capability — `power`, `temperature`,
            # `fan_mode` — and a double that only ever said `set` is what let
            # every device in a real contract arrive fully described and
            # entirely inoperable. One device here speaks only the bridge's own
            # words, so the path that reads them is exercised, not assumed.
            {
                "id": "ac_parents",
                "label": "מזגן הורים",
                "kind": "number",
                "value": 23,
                "controllable": True,
                "operations": ["power", "temperature", "fan_mode", "swing_mode"],
                "device_class": "climate",
                "capabilities": ["on_off", "temperature", "fan_mode", "swing_mode"],
                "constraints": {"min": 16, "max": 30, "step": 1, "unit": "°"},
                "entity_id": "climate.ac_parents",
            },
            # A vacuum, because this house has one and because it is the
            # busiest row the live vocabulary can produce: a switch for its
            # power and five verbs that take no payload at all. A double
            # without one meant the row that carries the most controls was the
            # one nobody had ever looked at.
            {
                "id": "vacuum",
                "label": "שואב",
                "kind": "toggle",
                "value": False,
                "controllable": True,
                "operations": ["power", "start", "pause", "stop", "return_to_base", "locate"],
                "device_class": "vacuum",
                "capabilities": ["on_off", "start", "pause", "stop", "return_home"],
                "entity_id": "vacuum.robot",
            },
            {
                # `idle` and not `streaming`, because that is what the live
                # camera reports — for days at a time, including every day the
                # picture itself answered HTTP 500. The double said `streaming`,
                # so nothing ever exercised the word that was actually reaching
                # the screen.
                "id": "cam_lia",
                "label": "מצלמת ליה",
                "kind": "readonly",
                "value": "idle",
                "display": "idle",
                "controllable": False,
                "operations": [],
                "device_class": "camera",
                "detail": {"domain": "camera", "area": "חדר בנות"},
                "unavailable_reason": "המצלמה אינה ניתנת לשליטה מכאן",
                "entity_id": "camera.lia_local",
            },
        ],
    },
    "helpers": {
        "available": True,
        "groups": [
            {
                "id": "toggles",
                "label": "מתגים",
                "items": [
                    {
                        "id": "guest_mode",
                        "label": "מצב אורחים",
                        "kind": "toggle",
                        "value": False,
                        "controllable": True,
                        "operations": ["set"],
                        "helper_kind": "input_boolean",
                    },
                    {
                        "id": "wake_time",
                        "label": "שעת השכמה",
                        "kind": "time",
                        "value": "06:45",
                        "controllable": True,
                        "operations": ["set"],
                        "helper_kind": "input_datetime",
                    },
                ],
            },
            {
                "id": "counters",
                "label": "מונים וטיימרים",
                "items": [
                    {
                        "id": "laundry_timer",
                        "label": "טיימר כביסה",
                        "kind": "readonly",
                        "value": "idle",
                        "controllable": True,
                        "operations": ["start", "pause", "cancel"],
                        "helper_kind": "timer",
                    },
                    {
                        "id": "coffee_counter",
                        "label": "מונה קפה",
                        "kind": "number",
                        "value": 3,
                        "controllable": True,
                        "operations": ["increment", "decrement", "reset"],
                        "helper_kind": "counter",
                        "constraints": {"min": 0, "max": 99, "step": 1},
                    },
                ],
            },
        ],
    },
    "automations": {
        "available": True,
        "items": [
            {
                "id": "morning_lights",
                "label": "אורות בוקר",
                "kind": "toggle",
                "value": True,
                "controllable": True,
                "operations": ["disable", "trigger", "rename"],
                "risk": "medium",
                "mode": "single",
                "last_triggered": "2026-08-26T06:45:00",
                "area": "סלון",
            },
            {
                "id": "away_lock",
                "label": "נעילה ביציאה",
                "kind": "toggle",
                "value": False,
                "controllable": True,
                "operations": ["enable", "trigger", "rename"],
                "risk": "medium",
                "mode": "restart",
                "last_triggered": None,
            },
        ],
    },
    "scripts": {
        "available": True,
        "items": [
            {
                "id": "goodnight",
                "label": "לילה טוב",
                "kind": "readonly",
                "value": "ready",
                "controllable": True,
                "operations": ["run"],
                "risk": "medium",
                "description": "מכבה אורות ונועל דלתות.",
                "last_run": "2026-08-25T23:10:00",
                "fields": [
                    {
                        "id": "delay_minutes",
                        "label": "השהיה",
                        "kind": "number",
                        "constraints": {"min": 0, "max": 30, "step": 5, "unit": " דק׳"},
                    }
                ],
            }
        ],
    },
    "scenes": {
        "available": True,
        "items": [
            {
                "id": "movie_night",
                "label": "ערב סרט",
                "kind": "readonly",
                "value": "ready",
                "controllable": True,
                "operations": ["activate"],
                "area": "סלון",
                "affects": ["salon", "led_salon"],
            }
        ],
    },
    "system": {
        "available": True,
        "items": [
            # `action` with no value, which is what the live system bridge sends
            # and what nothing here used to model. A self-check has nothing to
            # set and nothing to read back; every other kind assumes an item
            # *is* a value, and requiring one is what left this row marked
            # controllable and drawn as a reading.
            {
                "id": "self_check",
                "label": "בדיקה עצמית",
                "kind": "action",
                "value": None,
                "display": "הרץ בדיקה",
                "controllable": True,
                "operations": ["run"],
                "risk": "read_only",
                "description": "בובי בודק את עצמו ומדווח. לא משנה כלום.",
            },
            {
                "id": "undo_last_action",
                "label": "ביטול הפעולה האחרונה",
                "kind": "readonly",
                "value": "available",
                "controllable": True,
                "operations": ["run"],
                "risk": "high",
                "description": "מחזיר את השינוי האחרון שבובי ביצע.",
            },
        ],
    },
}


class MockManagementBridge(ManagementBridge):
    """Keeps tasks and features in memory and checks them the way HA does."""

    def __init__(
        self,
        *,
        tasks: dict[str, dict[str, Any]] | None = None,
        features: dict[str, bool] | None = None,
        users: dict[str, str] | None = None,
        available: bool = True,
        #: Home Assistant's master switch. Off by default, as it is today.
        writes_enabled: bool = False,
        #: When False, the feature contract omits current state — which must
        #: block a preview rather than be guessed at.
        reports_feature_state: bool = True,
        fail_on: str | None = None,
        verifies: bool = True,
        #: Raw family payloads, keyed by resource. A family missing from this
        #: mapping answers "unavailable", which is exactly what a bridge that
        #: has not shipped does — so a test can hold one back on purpose.
        resources: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.tasks: dict[str, dict[str, Any]] = tasks or {}
        self.features: dict[str, bool] = features or {}
        self.users: dict[str, str] = users or {"user_1": "ינון", "user_2": "הודיה"}
        self._available = available
        self.writes_enabled = writes_enabled
        self._reports_feature_state = reports_feature_state
        self._fail_on = fail_on
        self._verifies = verifies
        self.resources: dict[str, dict[str, Any]] = (
            copy.deepcopy(DEFAULT_RESOURCE_PAYLOADS) if resources is None else resources
        )
        #: Every apply() call, so a test can assert a preview made none.
        self.applied: list[dict[str, Any]] = []

    def _declared_operations(self, resource: str) -> tuple[str, ...]:
        """The verbs this family's payload says it has.

        Falls back to the whole spec when the payload is silent, which keeps
        every test that predates the `operations` key working. A payload that
        *does* name them is taken at its word, including an empty list — the
        live contract publishes exactly that for `scenes`, because this house
        has no scenes.

        Names go through `canonical_operation` on the way in, exactly as the
        real contract normalizer does. Skipping that step here reproduced the
        original bug inside the double itself: the house says `add` for a
        calendar and this application says `create`, so an untranslated `add`
        was filtered out by the closed set and the calendar came back with no
        operations at all.
        """
        payload = self.resources.get(resource) or {}
        declared = payload.get("operations")
        if declared is None:
            return SPECS[resource].operations
        allowed = SPECS[resource].operations
        canonical = (canonical_operation(resource, str(name)) for name in declared)
        return tuple(name for name in canonical if name in allowed)

    async def status(self) -> ManagementStatus:
        if not self._available:
            return ManagementStatus(available=False, reason=UNAVAILABLE_MESSAGE)
        return ManagementStatus(
            available=True,
            contract_version="mock-3a",
            writes_enabled=self.writes_enabled,
            resources=[
                ManagementResource(
                    id="tasks",
                    label="משימות",
                    available=True,
                    operations=[
                        ManagedOperation(id="add", label="הוספת משימה"),
                        ManagedOperation(id="edit", label="שינוי תוכן"),
                        ManagedOperation(id="complete", label="סימון כבוצעה", valueless=True),
                        ManagedOperation(id="reopen", label="החזרה לפעילה", valueless=True),
                        ManagedOperation(
                            id="delete", label="מחיקה", destructive=True, valueless=True
                        ),
                    ],
                    targets=[
                        ManagedTarget(id=user_id, label=name)
                        for user_id, name in self.users.items()
                    ],
                ),
                ManagementResource(
                    id="features",
                    label="תכונות",
                    available=True,
                    operations=[ManagedOperation(id="set", label="הפעלה או כיבוי")],
                    targets=[
                        ManagedTarget(
                            id=feature_id,
                            label=feature_id,
                            risk="low",
                            enabled=state if self._reports_feature_state else None,
                        )
                        for feature_id, state in self.features.items()
                    ],
                ),
                # A family is advertised only when this double actually holds
                # data for it, which is how the live contract behaves: the
                # bridge names what it has implemented. Withhold a family from
                # `resources=` and every route for it fails closed, which is
                # what a test of "the bridge has not landed" needs.
                *[
                    ManagementResource(
                        id=resource,
                        label=SPECS[resource].label,
                        available=True,
                        # What the *family payload* declares, not what this
                        # application can imagine. Every operation in
                        # `SPECS[resource].operations` used to be advertised
                        # here, and the live 3c contract advertises a subset of
                        # them: calendar names `add` and nothing else, helpers
                        # name `set` and none of the timer verbs, automations
                        # and scripts name no `rename`. So the double was more
                        # permissive than Home Assistant, and every "this
                        # operation was not declared" path went untested against
                        # anything realistic.
                        #
                        # A payload with no `operations` key still falls back to
                        # the spec, so a test that only cares about one family's
                        # data does not have to spell out a contract.
                        operations=[
                            ManagedOperation(
                                id=operation,
                                label=SPECS[resource].titles.get(operation, operation),
                                destructive=operation in SPECS[resource].destructive,
                                valueless=operation in VALUELESS_OPERATIONS,
                            )
                            for operation in self._declared_operations(resource)
                        ],
                        # What a `create` may be aimed at — the live contract
                        # publishes these for the families that have them, and
                        # a screen with no targets offers no "add" form. The
                        # calendar screen was blank here for exactly that
                        # reason while the live bridge published two.
                        targets=[
                            ManagedTarget(id=target["id"], label=target.get("label"))
                            for target in self.resources[resource].get("targets", [])
                        ],
                    )
                    for resource in self.resources
                    if resource in SPECS
                ],
            ],
        )

    async def snapshot(self) -> TaskSnapshot:
        tasks = [
            SnapshotTask(
                uid=uid,
                summary=task["summary"],
                status=task["status"],
                completed=task["status"] == _COMPLETED,
                due=task.get("due") or None,
                owner_id=task["user_id"],
                owner=self.users.get(task["user_id"], task["user_id"]),
            )
            for uid, task in self.tasks.items()
        ]
        return TaskSnapshot(
            count=len(tasks),
            tasks=tasks,
            owners=[ManagedTarget(id=k, label=v) for k, v in self.users.items()],
            writes_enabled=self.writes_enabled,
        )

    async def resource_snapshot(self, resource: str) -> ResourceSnapshot:
        payload = self.resources.get(resource)
        if payload is None:
            return unavailable(resource, f"{resource}: הגשר של בובי עדיין לא כולל את השירות הזה")
        return normalize_resource(resource, {**payload, "writes_enabled": self.writes_enabled})

    def _raw_item(self, resource: str, item_id: str) -> dict[str, Any] | None:
        """The raw entry behind a normalized item, so a commit can change it."""
        payload = self.resources.get(resource) or {}
        for group in payload.get("groups", []):
            for entry in group.get("items", []):
                if entry.get("id") == item_id:
                    return entry
        for entry in payload.get("items", []):
            if entry.get("id") == item_id:
                return entry
        return None

    async def observe(self, resource_type: str, resource_id: str | None) -> ObservedState | None:
        if resource_type in SPECS and resource_type not in ("tasks", "features"):
            if resource_id is None:
                return ObservedState(resource_id=None, label=None, values={})
            snapshot = await self.resource_snapshot(resource_type)
            if not snapshot.available:
                return None
            item = next((entry for entry in snapshot.items if entry.id == resource_id), None)
            if item is None or item.value is None:
                return None
            values: dict[str, Any] = {"value": item.value}
            for key, value in item.detail.items():
                if isinstance(value, str | int | float | bool):
                    values[key] = value
            return ObservedState(resource_id=item.id, label=item.label, values=values)

        if resource_type == "tasks":
            if resource_id is None:
                return ObservedState(values={})
            task = self.tasks.get(resource_id)
            if task is None:
                return None
            return ObservedState(
                resource_id=resource_id,
                label=task["summary"],
                values={
                    "summary": task["summary"],
                    "status": task["status"],
                    "user_id": task["user_id"],
                    "owner": self.users.get(task["user_id"], task["user_id"]),
                },
            )

        if resource_type == "features":
            if not self._reports_feature_state or resource_id not in self.features:
                return None
            enabled = self.features[resource_id]
            return ObservedState(
                resource_id=resource_id,
                label=resource_id,
                values={"state": "on" if enabled else "off", "enabled": enabled},
            )
        return None

    async def apply(
        self,
        *,
        resource_type: str,
        operation: str,
        resource_id: str | None,
        payload: dict[str, Any],
        observed: ObservedState,
        request_id: str,
        preview_token: str,
    ) -> BridgeOutcome:
        self.applied.append(
            {
                "resource_type": resource_type,
                "operation": operation,
                "resource_id": resource_id,
                "payload": payload,
                "observed": observed.values,
                "request_id": request_id,
                "preview_token": preview_token,
            }
        )
        # What the live bridge does with a commit carrying no token, and the
        # reason it is mimicked here: a tokenless commit reached a real Home
        # Assistant once, because this double did not care about the field.
        if not preview_token:
            return BridgeOutcome(executed=False, verified=False, reason="invalid_commit_request")
        # The bridge's own master switch, checked again on its side.
        if not self.writes_enabled:
            return BridgeOutcome(executed=False, verified=False, reason="writes_disabled")
        if self._fail_on == operation:
            raise BobiError("הגשר סירב לבצע את הפעולה", code="bridge_refused")

        if resource_type == "tasks":
            return self._apply_task(operation, resource_id, payload, observed)
        if resource_type == "features":
            return self._apply_feature(resource_id, payload, observed)
        if resource_type in SPECS:
            return self._apply_resource(resource_type, operation, resource_id, payload, observed)
        raise BobiError("משאב לא נתמך", code="unsupported_resource")

    def _apply_resource(
        self,
        resource: str,
        operation: str,
        resource_id: str | None,
        payload: dict[str, Any],
        observed: ObservedState,
    ) -> BridgeOutcome:
        """A 3.0 family commit, checked the way the live bridge checks one."""
        spec = SPECS[resource]
        # The family's own declaration, so a double configured with a real
        # contract refuses what that contract omits — the same refusal Home
        # Assistant gives, arriving at the same point.
        if operation not in self._declared_operations(resource):
            return BridgeOutcome(executed=False, verified=False, reason="unsupported_operation")

        if operation in spec.creating:
            new_id = f"{resource}_{secrets.token_hex(3)}"
            entry = {
                "id": new_id,
                # `name` too: a smart rule carries its title there, not in
                # `label` or `value`, so a created rule used to come back
                # labelled `rules_a1b2c3`.
                "label": (
                    payload.get("label") or payload.get("name") or payload.get("value") or new_id
                ),
                "kind": "toggle",
                "value": True,
                "controllable": True,
                "operations": [
                    name for name in self._declared_operations(resource)
                    if name not in spec.creating
                ],
                **{k: v for k, v in payload.items() if k not in ("label",)},
            }
            self.resources.setdefault(resource, {"available": True}).setdefault(
                "items", []
            ).append(entry)
            return BridgeOutcome(executed=True, verified=self._verifies, reason="ok",
                                 resource_id=new_id)

        entry = self._raw_item(resource, resource_id or "")
        if entry is None:
            return BridgeOutcome(executed=False, verified=False, reason="not_found")

        # Optimistic locking, exactly as Home Assistant does it.
        if observed.values.get("value") != entry.get("value"):
            return BridgeOutcome(executed=False, verified=False, reason="stale_preview")

        if operation in spec.destructive:
            for container in (self.resources[resource].get("items", []),):
                if entry in container:
                    container.remove(entry)
            for group in self.resources[resource].get("groups", []):
                if entry in group.get("items", []):
                    group["items"].remove(entry)
            return BridgeOutcome(executed=True, verified=self._verifies, reason="ok",
                                 resource_id=resource_id)

        wanted = payload.get("value", payload.get("enabled"))
        if operation == "enable":
            wanted = True
        elif operation == "disable":
            wanted = False

        if wanted is not None and entry.get("value") == wanted:
            return BridgeOutcome(executed=False, verified=True, reason="already_in_state",
                                 resource_id=resource_id)
        if wanted is not None:
            entry["value"] = wanted
        # Structured edits — a rule's days, an event's start — land beside it.
        for key, value in payload.items():
            if key not in ("value", "enabled"):
                entry[key] = value
        return BridgeOutcome(executed=True, verified=self._verifies, reason="ok",
                             resource_id=resource_id)

    def _apply_task(
        self,
        operation: str,
        resource_id: str | None,
        payload: dict[str, Any],
        observed: ObservedState,
    ) -> BridgeOutcome:
        if operation == "add":
            summary = payload.get("summary")
            if any(
                task["summary"] == summary and task["status"] == _OPEN
                for task in self.tasks.values()
            ):
                return BridgeOutcome(executed=False, verified=False, reason="duplicate")
            uid = f"uid_{secrets.token_hex(4)}"
            self.tasks[uid] = {
                "summary": summary,
                "status": _OPEN,
                "user_id": payload.get("user_id"),
                "due": payload.get("due_date") or "",
            }
            return BridgeOutcome(
                executed=True, verified=self._verifies, reason="ok", resource_id=uid
            )

        task = self.tasks.get(resource_id or "")
        if task is None:
            return BridgeOutcome(executed=False, verified=False, reason="not_found")

        # Optimistic locking, exactly as Home Assistant does it: compare what
        # the preview saw against what is true now, and refuse if they differ.
        if (
            task["summary"] != observed.values.get("summary")
            or task["status"] != observed.values.get("status")
        ):
            return BridgeOutcome(executed=False, verified=False, reason="stale_preview")

        if operation == "edit":
            task["summary"] = payload.get("new_summary")
        elif operation == "complete":
            task["status"] = _COMPLETED
        elif operation == "reopen":
            task["status"] = _OPEN
        elif operation == "delete":
            self.tasks.pop(resource_id or "", None)
        return BridgeOutcome(
            executed=True, verified=self._verifies, reason="ok", resource_id=resource_id
        )

    def _apply_feature(
        self, resource_id: str | None, payload: dict[str, Any], observed: ObservedState
    ) -> BridgeOutcome:
        if resource_id not in self.features:
            return BridgeOutcome(executed=False, verified=False, reason="unknown_feature")

        actual = "on" if self.features[resource_id] else "off"
        if actual != observed.values.get("state"):
            return BridgeOutcome(executed=False, verified=False, reason="stale_preview")

        wanted = bool(payload.get("enabled"))
        if self.features[resource_id] == wanted:
            return BridgeOutcome(
                executed=False, verified=True, reason="already_in_state", resource_id=resource_id
            )

        self.features[resource_id] = wanted
        return BridgeOutcome(
            executed=True, verified=self._verifies, reason="ok", resource_id=resource_id
        )
