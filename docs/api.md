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
{ "ok": true, "app": "bobi-control-center", "version": "2.2.0",
  "adapter": "home_assistant", "writes_enabled": false }
```

### `GET /api/bobi/connection`

Whether the app is showing real or demo data. Contains no secret.

```json
{ "adapter": "home_assistant", "connected": true, "writes_enabled": false,
  "phase": 2, "app_version": "2.2.0", "detail": "מחובר לגשר של בובי" }
```

---

## `GET /api/bobi/status`

→ `script.bobi_cc_status`

```json
{
  "health": { "status": "healthy", "ok": true, "reason": "הגשר דיווח: True" },
  "ok": true,
  "version": "…",
  "uptime": "…",
  "whatsapp": { "connected": true, "status": "WORKING", "label": "תקין",
                "detail": null, "extra": {} },
  "ai": { "enabled": true, "fast_paths_enabled": true, "fast_paths_count": 3,
          "fast_paths": ["lighting", "climate", "shabbat"],
          "label": "פעיל", "detail": "3 מסלולים מהירים", "extra": {} },
  "users": { "total": 3, "active": 2, "admins": 1, "names": [], "extra": {} },
  "config": { "ok": true, "status": "OK", "label": "תקין", "detail": null, "extra": {} },
  "features": [{ "id": "shabbat", "label": "שעון שבת", "enabled": true, "detail": null }],
  "components": [{ "id": "whatsapp", "name": "WhatsApp", "state": "WORKING",
                   "label": "תקין", "ok": true, "detail": null }],
  "counts": { "catalog_count": 19, "rules_count": 6, "issue_count": 3 },
  "details": {},
  "writes_enabled": false
}
```

`health` is the one resolved answer to "is Bobi alright?", and `ok` mirrors
`health.ok`. It is derived from authoritative information only: whatever the
bridge states about itself first — `ok`, `healthy` (which the real bridge sends,
as a string boolean), or a status word — and otherwise from the component
states, where **only an explicit failure counts**. A component the bridge could
not resolve leaves health `unknown`; it never makes it `false`. `unknown` is a
real answer and the UI renders it as such, never as a fault.

| `status` | `ok` | Meaning |
| --- | --- | --- |
| `healthy` | `true` | The bridge said so, or every known component is fine |
| `degraded` | `false` | Some known component failed |
| `unhealthy` | `false` | The bridge said so, or every known component failed |
| `unknown` | `null` | Nothing authoritative was sent — not a failure |

The bridge reports WhatsApp, the AI fallback, the household, feature toggles and
its own configuration health as separate sections, so they are **first-class
fields** rather than text rows in `details`. Each is accepted nested
(`{"whatsapp": {"connected": true}}`), bare (`{"whatsapp": "WORKING"}`) or
flat-prefixed (`{"whatsapp_connected": true}`).

`components` is the dashboard's health row. The real bridge sends no such list,
so it is derived from the sections above; a list the bridge *does* send wins.
`fast_paths` is normalized from a flag, a count or a list of names into all
three. `counts` is rendered dynamically, so a new counter appears without a
frontend change, and any remaining scalar still becomes a `details` row rather
than being dropped. `writes_enabled` is forced to `false` whatever the bridge
says. Feature toggles are **read-only** in Phase 2.

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
    "limits": { "min": 16, "max": 30, "step": 1,
                "min_temp": 16, "max_temp": 30, "temp_step": 1,
                "preset_modes": ["eco"], "fan_modes": ["low", "high"],
                "swing_modes": [], "hvac_modes": ["off", "cool"],
                "min_kelvin": null, "max_kelvin": null,
                "min_brightness": null, "max_brightness": null,
                "intensity_min": null, "intensity_max": null,
                "scent_slots": [], "timer_max_seconds": null, "extra": {} },
    "last_changed": "2026-08-25T11:00:00+03:00",
    "extra": {}
  }]
}
```

Read out of the bridge's `entries`. `name` is the canonical display name and
`available` is derived from the state, both server-side. The UI shows `name`,
`area`, `state`, `capabilities` and `aliases`; `entity_id`, `handler` and
`extra` appear only under **מתקדם / פרטים טכניים**.

`limits` keeps the bridge's domain-specific constraints in full — temperature
range and mode lists for climate, colour temperature and brightness for lights,
intensity, slots and timer for the scent diffuser — because Phase 3's editing
controls need them. `min`/`max`/`step` remain as a generic view, filled from
whichever domain range applies; anything unrecognised lands in `limits.extra`.

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
  "pre_shabbat_offset_minutes": 30,
  "profiles": [{
    "id": "pre_off", "kind": "pre_off", "label": "כיבוי לפני שבת",
    "active": true, "time": null, "offset_minutes": 20,
    "devices": [{ "id": "dining", "label": "פינת אוכל" },
                { "id": "led_salon", "label": "LED סלון" }],
    "extra": {}
  }],
  "ac_temperatures": [
    { "id": "ac_salon", "label": "מזגן סלון", "temperature": 24.0, "text": "24.0" }
  ],
  "has_draft": false,
  "draft_owners": [],
  "writes_enabled": false,
  "extra": {}
}
```

Times are read out of the bridge's `upcoming`, including
`upcoming.pre_offset_minutes` — which is where the real bridge keeps the
pre-Shabbat offset. Profiles come from `profiles` as **one list**; `kind`
carries the bridge's own key, so a profile the app has never seen still renders.

A profile lists its devices as the bridge's own short `tokens`, which
`device_labels` translates. Both halves are kept: `label` is what the screen
shows, `id` is the token Phase 3 must send back to change the profile. The same
applies to `ac_temperatures`. The bridge keeps those **inside the profiles**
rather than at the top level, so they are collected from the top level, from
`upcoming` and from every profile, then de-duplicated by device — one air
conditioner named by three profiles is one entry, and where two profiles
disagree the first reading is kept rather than the device being listed twice.
`temperature` is the numeric value, `null` for a setting the bridge does not
express as a number; `text` always carries what it actually sent. `has_draft` is derived from
`drafts`. `writes_enabled` is forced to `false`.

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

## Management — Phase 3A

Base path `/api/bobi/manage`. Every change follows one flow:

```
edit → preview → explicit confirmation → commit → read-after-write → result
```

### Two independent layers

| This application | Home Assistant |
| --- | --- |
| Preview token: random, server-side, 5-minute TTL, single use | Master write switch |
| Token bound to operation, target, values **and observed state** | Operation and target whitelists |
| Commit carries no payload — only the stored one is sent | `expected_summary` / `expected_status` / `expected_state` |
| Explicit confirmation; a typed word when destructive | Duplicate protection, read-after-write |

Both must approve. Neither is relaxed because the other exists.

### The bridge services

Five, and only these. `todo.*` and `input_boolean.*` are never called.

| Service | Kind | Endpoint |
| --- | --- | --- |
| `script.bobi_cc_manage_contract` | read | `GET /manage/contract` |
| `script.bobi_cc_task_snapshot` | read | `GET /manage/tasks/snapshot` |
| `script.bobi_cc_task_add_commit` | write | `POST /manage/tasks/commit` |
| `script.bobi_cc_task_update_commit` | write | `POST /manage/tasks/commit` |
| `script.bobi_cc_feature_commit` | write | `POST /manage/features/commit` |

### `GET /api/bobi/manage/contract`

```json
{
  "available": true,
  "reason": null,
  "contract_version": "3a",
  "writes_enabled": false,
  "requires_preview": true, "requires_confirmation": true,
  "requires_read_after_write": true,
  "resources": [
    { "id": "tasks", "label": "משימות", "available": true,
      "operations": [{ "id": "add", "label": "הוספת משימה", "destructive": false },
                     { "id": "delete", "label": "מחיקה", "destructive": true }],
      "targets": [{ "id": "user_1", "label": "…", "risk": null, "enabled": null }] },
    { "id": "features", "label": "תכונות", "available": true,
      "operations": [{ "id": "set", "label": "הפעלה או כיבוי", "destructive": false }],
      "targets": [{ "id": "morning_auto", "label": "סיכום בוקר אוטומטי",
                    "risk": "low", "enabled": null }] }
  ]
}
```

**`writes_enabled` is read, never written.** It is off today, which means
previews work and commits are refused — a disabled feature, not an error. No
endpoint in this API can set it; enabling it is a Home Assistant-side decision.

Task operations are `add`, `edit`, `complete`, `reopen`, `delete`; features
have `set`. An operation the contract does not name is never offered, and one
this application does not implement is dropped rather than passed through.

### `GET /api/bobi/manage/tasks/snapshot`

Open and completed tasks, flattened, each with its owner. `uid` is the bridge's
own handle — **no `todo.*` entity id appears**, because the bridge does not send
one and this app must not infer one.

```json
{ "count": 2, "writes_enabled": false,
  "owners": [{ "id": "user_1", "label": "…", "risk": null, "enabled": null }],
  "tasks": [{ "uid": "…", "summary": "…", "status": "needs_action",
              "completed": false, "due": null,
              "owner_id": "user_1", "owner": "…" }] }
```

### `POST /api/bobi/manage/{resource}/preview`

`resource` is `tasks` or `features`; anything else is a 404 before any service
is consulted. **This performs no write** — it reads the snapshot or the
contract, and describes what would change.

Request: `{ "operation": "delete", "resource_id": "<uid>" }`

The client sends the target and what the user typed. It does **not** send the
current state: the backend observes that itself, so a screen cannot mis-state
what is being changed. A resource whose state cannot be read yields an invalid
preview rather than a guess.

```json
{
  "preview_id": "pv_…",
  "operation": "delete", "resource_type": "tasks", "resource_id": "<uid>",
  "title": "מחיקת משימה",
  "changes": [{ "label": "משימה", "before": "לקבוע תור לרופא", "after": null }],
  "explanation": "המשימה תוסר לגמרי מהרשימה.",
  "destructive": true,
  "warning": "פעולה זו אינה הפיכה…",
  "confirm_word": "מחק", "confirm_label": "מחק משימה",
  "valid": true, "errors": [],
  "expires_at": "…", "would_execute": false
}
```

### `POST /api/bobi/manage/{resource}/commit`

Request: `{ "preview_id": "pv_…", "confirmed": true, "confirm_word": "מחק" }`

No payload: everything sent to Home Assistant comes from the stored preview.
`operation` and `resource_id` may be echoed and are then checked for agreement —
a mismatch is rejected, not corrected.

| Status | `code` | When |
| --- | --- | --- |
| 409 | `preview_expired` | Unknown, expired, already used, wrong resource, or a disagreeing echo |
| 428 | `confirmation_required` | Not confirmed, or a destructive change without its word |
| 409 | `writes_disabled` | Home Assistant's master switch is off — *ניהול עדיין לא הופעל ב-Home Assistant* |

```json
{
  "preview_id": "pv_…", "operation": "delete", "resource_type": "tasks",
  "result": {
    "status": "committed", "message": "השינוי בוצע ואומת",
    "resource_id": "<uid>", "reason": "ok",
    "verification": { "verified": true, "method": "read_after_write", "detail": null }
  },
  "audit": { "…": "the entry this produced" }
}
```

`status` is `committed` (*השינוי בוצע ואומת*), `committed_unverified`
(*השינוי בוצע אך לא הצלחנו לאמת*) or `failed` (*השינוי לא בוצע*). The bridge's
own `reason` is carried through:

| `reason` | Result |
| --- | --- |
| `stale_preview` | `failed` — the state moved after the preview, and **nothing was mutated** |
| `already_in_state` | `committed`, verified, with *המצב כבר היה כמבוקש* |
| `duplicate`, `not_found`, `invalid_*` | `failed`, with the bridge's reason explained in Hebrew |

### `GET /api/bobi/manage/audit`

Recent previews and commits, newest first, including refusals. Each record has
`timestamp`, `operation`, `resource_type`, `resource_id`, `requested_change`,
`result`, `verified` and `source: "web"`. Fields resembling a phone number, LID,
chat id or credential are stripped before a record is created — and before the
payload reaches the bridge.

---

## What does not exist

There is still no endpoint to control a device, save a Shabbat configuration,
create a smart rule, edit an automation, write to a calendar, change a user's
permissions, or move the AI master toggle or Fast Paths — each needs its own
Home Assistant contract first. There is also **no endpoint that enables Home
Assistant's master write switch**, and a test asserts none of the management
modules can set it. A test enumerates the published surface and asserts the only
non-GET routes are the probe and the managed preview/commit pair.
