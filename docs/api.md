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

### One canonical schema

Responses are **not** the shape Home Assistant sends. The bridge names its
collections `entries`, `registry`, `upcoming`/`profiles`/`drafts` and per-user
`users`, and nests the probe answer under `result`.
`backend/app/services/normalize.py` maps all of that onto one canonical
contract, so:

* a response carries **exactly one** collection per resource — never a
  populated list beside an empty legacy one;
* the frontend contains no normalization logic and never sees a raw bridge key;
* fields the normalizer does not map explicitly land in a per-item `extra` map,
  shown under "מתקדם / פרטים טכניים" so a growing registry surfaces rather than
  disappearing;
* a partial or oddly-typed response degrades to a usable screen instead of a
  500 — `checks` arriving as a map rather than a list is handled, not rejected.

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
  "areas": ["חדר הורים", "סלון"],
  "groups": ["מיזוג"],
  "devices": [{
    "id": "climate.example",
    "name": "מזגן סלון",
    "area": "סלון",
    "group": "מיזוג",
    "domain": "climate",
    "state": "off",
    "available": true,
    "aliases": ["מזגן סלון", "המזגן בסלון"],
    "capabilities": ["turn_on", "turn_off", "set_temperature"],
    "semantic_scopes": ["climate", "temperature"],
    "controllable": true,
    "logical_controllable": true,
    "entity_id": "climate.example",
    "handler": "climate_handler",
    "limits": { "min": 16, "max": 30, "step": 1 },
    "last_changed": "2026-08-25T11:00:00+03:00",
    "extra": {}
  }]
}
```

Read out of the bridge's `entries`. `name` is the canonical display name and
`available` is derived from the state, both server-side. The UI shows `name`,
`area`, `state`, `capabilities` and `aliases`; `entity_id`, `handler` and
`extra` appear only under **מתקדם / פרטים טכניים**.

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

Read out of the bridge's `registry`, which may arrive as a map keyed by id or
as a list. Rendered dynamically and grouped by whatever `group` values the
registry supplies; entries with none fall under *יכולות נוספות*. Toggles are
**read-only** in Phase 2.

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
  "parasha": "פרשת ראה",
  "pre_shabbat_offset_minutes": 20,
  "profiles": [{
    "id": "pre_off", "kind": "pre_off", "label": "כיבוי לפני שבת",
    "active": true, "time": null, "offset_minutes": 20,
    "devices": ["אור מטבח"], "extra": {}
  }],
  "ac_temperatures": { "מזגן סלון": "24" },
  "has_draft": false,
  "draft_owners": [],
  "writes_enabled": false,
  "extra": {}
}
```

Times are read out of the bridge's `upcoming`. Profiles come from `profiles` as
**one list** — `kind` carries the bridge's own key, so a profile the app has
never seen still renders. Device tokens are resolved to friendly names
server-side, including the keys of `ac_temperatures`; the UI never receives a
raw token. `has_draft` is derived from `drafts`. `writes_enabled` is forced to
`false`.

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

→ `script.bobi_cc_tasks`. The bridge groups tasks per user under `users` and
strips internal metadata; they are flattened into one list with `owner` and
`list_name` inherited from the group.

```json
{ "count": 6,
  "owners": ["ינון", "הודיה"],
  "tasks": [{ "id": "…", "title": "לקבוע תור לרופא", "status": "needs_action",
              "completed": false, "due": null, "owner": "ינון",
              "list_name": "משימות ינון", "extra": {} }] }
```

---

## `GET /api/bobi/diagnostics`

→ `script.bobi_cc_diagnostics`

```json
{
  "ok": false,
  "issue_count": 3,
  "issues": [{ "id": "device_unavailable:camera.example", "severity": "error",
               "title": "מצלמת ליה אינה זמינה", "message": "…",
               "component": "device", "code": "device_unavailable",
               "entity_ids": ["camera.example"], "suggested_action": "…",
               "detail": "state=unavailable", "extra": {} }],
  "checks": [{ "id": "whatsapp", "label": "WhatsApp", "ok": true,
               "value": "WORKING", "detail": null },
             { "id": "catalog_count", "label": "מכשירים בקטלוג", "ok": null,
               "value": "19", "detail": null }]
}
```

The bridge sends `checks` as a **map** mixing status words with plain figures;
it is normalized into a list. A status word sets `ok`; a figure leaves `ok`
`null` and renders as an informational value rather than a green pass.

Issue ids are made unique — two devices sharing `device_unavailable` are
qualified by entity — so they are safe as list keys.

`code`, `entity_ids` and `detail` are rendered only inside the collapsed
**פרטים טכניים** section.

---

## `POST /api/bobi/probe`

→ `script.bobi_cc_probe`, which Home Assistant invokes with `probe_only=true`.

The bridge nests its answer under `result`; the normalizer flattens it, so the
top-level fields below are always the real values rather than nulls.

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
  "schedule_kind": "next_night_clock",
  "text": "…",
  "warnings": [],
  "probe_only": true,
  "would_execute": false,
  "raw": { "executed": false, "result": { "…": "the untouched bridge response" } }
}
```

`probe_only: true` and `would_execute: false` are asserted by the normalizer —
never derived from the bridge response. If the bridge ever reported
`executed: true`, the flag still reads `false` **and** a warning is added, so
the discrepancy is visible rather than hidden.

`raw` carries the untouched bridge response for the Test Center's JSON view.

The UI derives its pipeline
(`טקסט → הבנה → יעד → תזמון → Skill → בדיקת בטיחות`) from these fields and
displays **בדיקה בלבד — לא בוצעה שום פעולה**.

---

## What does not exist

There is no endpoint to turn a device on or off, change a schedule, complete a
task, edit permissions, or toggle a capability. A test enumerates the router and
asserts that `POST /api/bobi/probe` is the only non-GET route.
