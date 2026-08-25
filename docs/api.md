# Bobi Control Center API

Base path: `/api/bobi` · Interactive docs: `/api/docs` · Schema: `/api/openapi.json`

Every response is a typed Pydantic model. **Phase 2 is read-only**: nine GET
endpoints and one POST, and that POST is a probe.

## Conventions

### Ingress-relative URLs

The app is served from a generated prefix such as
`/api/hassio_ingress/<token>/`. The frontend derives its base from
`location.pathname` at runtime, so paths below are relative to the app root, not
to the domain root.

### Open models

Bridge models set `extra="allow"` and make almost every field optional. The
registry grows independently of this app, so unknown keys are preserved rather
than dropped, and a partial response degrades to a usable screen instead of a
500.

### Errors

```json
{ "code": "bridge_service_missing",
  "message": "שירות הגשר script.bobi_cc_status לא נמצא ב-Home Assistant",
  "details": { "service": "script.bobi_cc_status" } }
```

| Status | `code` | Meaning |
| --- | --- | --- |
| 422 | `validation_error` | Bad payload; `details.fields` lists the paths |
| 500 | `internal_error` | Unexpected; logged server-side, generic message returned |
| 502 | `bridge_service_missing` | A `bobi_cc_*` script is not installed |
| 502 | `ha_unauthorized` | The Supervisor token was rejected |
| 502 | `ha_error` | Home Assistant returned an error |
| 502 | `upstream_unavailable` | Timeout or transport failure |
| 502 | `bridge_bad_shape` | The response was not an object |

Stack traces never leave the process.

---

## System

### `GET /health`

```json
{ "ok": true, "app": "bobi-control-center", "version": "2.0.0",
  "adapter": "home_assistant", "writes_enabled": false }
```

### `GET /api/bobi/connection`

Whether the app is showing real or demo data. Contains no secret.

```json
{ "adapter": "home_assistant", "connected": true,
  "writes_enabled": false, "phase": 2, "detail": "מחובר לגשר של בובי" }
```

---

## `GET /api/bobi/status`

→ `script.bobi_cc_status`

```json
{
  "ok": true,
  "version": "…",
  "uptime": "…",
  "components": [{ "id": "whatsapp", "name": "WhatsApp", "state": "online",
                   "label": "מחובר", "ok": true, "detail": null }],
  "counts": { "devices": 18, "rules": 6, "issues": 3 },
  "writes_enabled": false
}
```

`counts` is rendered dynamically, so a new counter appears without a frontend
change. `writes_enabled` is forced to `false` whatever the bridge says.

---

## `GET /api/bobi/devices`

→ `script.bobi_cc_devices`

| Query | Default | Notes |
| --- | --- | --- |
| `scope` | `all` | One of the 11 semantic scopes; anything else is a 422 |
| `include_unavailable` | `true` | Passed straight to the bridge |

Scopes: `all`, `lighting`, `climate`, `cameras`, `battery`, `temperature`,
`humidity`, `vacuum`, `people`, `switches`, `scent`.

```json
{
  "scope": "climate",
  "include_unavailable": true,
  "count": 3,
  "devices": [{
    "entity_id": "climate.example",
    "name": "מזגן סלון",
    "canonical": "מזגן סלון",
    "semantic_scopes": ["climate", "temperature"],
    "aliases": ["מזגן סלון", "המזגן בסלון"],
    "domain": "climate",
    "group": "מיזוג",
    "area": "סלון",
    "state": "off",
    "controllable": true,
    "logical_controllable": true,
    "handler": "climate_handler",
    "capabilities": ["turn_on", "turn_off", "set_temperature"],
    "limits": { "min": 16, "max": 30, "step": 1 },
    "last_changed": "2026-08-25T11:00:00+03:00"
  }]
}
```

The UI shows `canonical`, `area`, `state`, `capabilities` and `aliases`.
`entity_id` and `handler` appear only under **מתקדם / פרטים טכניים**.

---

## `GET /api/bobi/capabilities`

→ `script.bobi_cc_capabilities`

```json
{
  "count": 16,
  "capabilities": [{
    "id": "lighting", "handler": "lighting_handler",
    "local": true, "local_after_parse": false,
    "risk": "low", "label": "שליטה בתאורה",
    "example": "תדליק את אור הסלון", "group": "שליטה בבית"
  }],
  "toggles": [{ "id": "master_ai", "label": "AI fallback",
                "state": "on", "enabled": true,
                "entity_id": "input_boolean.example" }]
}
```

Rendered dynamically and grouped by whatever `group` values the registry
supplies; entries with none fall under *יכולות נוספות*. Toggles are **read-only**
in Phase 2.

---

## `GET /api/bobi/users`

→ `script.bobi_cc_users`

Contains no phone number and no LID — the bridge withholds them, and the UI
shows only whether WhatsApp is connected.

```json
{ "count": 2,
  "users": [{ "id": "…", "name": "ינון", "role": "admin", "enabled": true,
              "whatsapp_connected": true, "calendar": "…", "task_list": "…",
              "permissions": ["control_devices"], "areas": ["סלון"] }] }
```

---

## `GET /api/bobi/shabbat`

→ `script.bobi_cc_shabbat` · **read-only**

```json
{
  "candle_lighting": "18:52",
  "havdalah": "19:51",
  "pre_shabbat_offset_minutes": 20,
  "pre_off_profile":     { "id": "…", "label": "…", "active": true, "devices": ["kitchen_light"] },
  "pre_on_profile":      { … },
  "night_off_profile":   { … },
  "morning_on_profile":  { … },
  "ac_temperatures": { "living_room_ac": 24 },
  "device_labels": { "kitchen_light": "אור מטבח" },
  "has_draft": false,
  "writes_enabled": false
}
```

`device_labels` maps a token to a friendly name; the UI never shows a raw token.
`writes_enabled` is forced to `false`.

---

## `GET /api/bobi/rules`

→ `script.bobi_cc_rules` — Bobi's canonical smart rules, not native HA
automations.

```json
{ "count": 6,
  "rules": [{ "id": "…", "name": "אור מטבח בערב", "description": "…",
              "enabled": true, "kind": "schedule",
              "schedule": "18:00 · ראשון–חמישי", "trigger": null,
              "targets": ["אור מטבח"], "last_triggered": "…" }] }
```

---

## `GET /api/bobi/tasks`

→ `script.bobi_cc_tasks`. The bridge strips internal metadata.

```json
{ "count": 6,
  "tasks": [{ "id": "…", "title": "לקבוע תור לרופא", "status": "needs_action",
              "completed": false, "due": null, "owner": "ינון",
              "list_name": "משימות ינון" }] }
```

---

## `GET /api/bobi/diagnostics`

→ `script.bobi_cc_diagnostics`

```json
{
  "ok": false,
  "issue_count": 3,
  "issues": [{ "id": "…", "severity": "error", "title": "מצלמת ליה אינה זמינה",
               "message": "…", "component": "מצלמות",
               "entity_id": "camera.example", "entity_ids": [],
               "suggested_action": "…", "detail": "state=unavailable" }],
  "checks": [{ "id": "…", "name": "גשר בובי", "ok": true, "detail": "זמין" }]
}
```

`entity_id`, `entity_ids` and `detail` are rendered only inside the collapsed
**פרטים טכניים** section.

---

## `POST /api/bobi/probe`

→ `script.bobi_cc_probe`, which Home Assistant invokes with `probe_only=true`.

Request: `{ "text": "כבה מזגן הורים ב-1:30 בלילה" }`

```json
{
  "handled": true,
  "status": "ok",
  "terminal": true,
  "skill": "local_schedule",
  "understanding": { "intent": "device_control", "action": "turn_off",
                     "domain": "climate", "target": "מזגן הורים",
                     "area": "חדר הורים", "time": "01:30" },
  "schedule_valid": true,
  "schedule_reason": "תוזמן ל-01:30",
  "schedule_kind": "one_time",
  "text": "…",
  "probe_only": true,
  "would_execute": false
}
```

`probe_only: true` and `would_execute: false` are asserted by this application
in both adapters — they are never derived from the bridge response.

The UI derives its pipeline
(`טקסט → הבנה → יעד → תזמון → Skill → בדיקת בטיחות`) from these fields and
displays **בדיקה בלבד — לא בוצעה שום פעולה**.

---

## What does not exist

There is no endpoint to turn a device on or off, change a schedule, complete a
task, edit permissions, or toggle a capability. A test enumerates the router and
asserts that `POST /api/bobi/probe` is the only non-GET route.
