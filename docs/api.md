# Bobi Management API

Base path: `/api/bobi` · Interactive docs: `/api/docs` · Schema: `/api/openapi.json`

Every response is a typed Pydantic model. The API speaks **Bobi vocabulary**
(capabilities, devices, rooms, schedules) and never Home Assistant vocabulary;
technical identifiers appear only inside an `advanced` object.

> **Phase 1 is mock-only.** No endpoint can reach a real Home Assistant, and
> every write returns `dry_run: true`.

## Conventions

### Errors

Every failure returns the same envelope, with a Hebrew `message` safe to show a
user. Stack traces never leave the server.

```json
{ "code": "not_found", "message": "לא מצאתי את המכשיר הזה", "details": { "device_id": "x" } }
```

| Status | `code` | Meaning |
| --- | --- | --- |
| 404 | `not_found` | The resource does not exist. |
| 409 | `preview_required` | Confirm was called without a valid preview token. |
| 409 | `read_only` | A write was attempted while the adapter is read-only. |
| 422 | `validation_error` | The payload failed validation. `details.fields` lists the paths. |
| 500 | `internal_error` | Unexpected. Logged server-side, generic message returned. |
| 501 | `adapter_not_implemented` | `BOBI_ADAPTER=real` was selected; Phase 2 is not built. |

### The Preview → Confirm model

Impactful changes are two calls. `preview` validates the payload, returns a
human-readable summary and issues an opaque `token`. `confirm` requires that
token *and* an identical payload — a mismatch is rejected, so a client cannot
skip the preview or confirm something other than what the user saw. Tokens are
single-use and expire after 15 minutes.

```
POST …/preview   {payload}                → ChangePreview { summary, lines, warnings, token }
POST …/confirm   {payload, token}         → OperationResult { success, dry_run, audit_id }
```

Applies to: saving/deleting an automation, saving the Shabbat configuration, and
changing a user's permissions. Reads and simple toggles do not require it.

---

## System

### `GET /health`

Health endpoint for Docker and the Home Assistant Supervisor watchdog.

```json
{ "status": "ok", "adapter": "mock", "version": "1.0.0" }
```

### `GET /api/bobi/status`

Everything the dashboard needs in one call: component health, statistics, the
activity timeline and the warnings that need attention.

```json
{
  "name": "בובי",
  "version": "1.0.0-phase1",
  "adapter": "mock",
  "read_only": true,
  "components": [{ "id": "whatsapp", "name": "WhatsApp", "state": "online", "label": "מחובר" }],
  "stats": [{ "id": "automations", "label": "אוטומציות פעילות", "value": 8, "severity": "ok" }],
  "activity": [{ "id": "act_0", "time": "08:42", "title": "בובי שלח תזכורת לפגישה" }],
  "attention": [{ "id": "att_camera_lia", "title": "מצלמת ליה אינה זמינה", "severity": "warning" }]
}
```

---

## Capabilities

| Method | Path | Returns |
| --- | --- | --- |
| `GET` | `/api/bobi/capabilities` | `Capability[]` |
| `GET` | `/api/bobi/capabilities/{id}` | `Capability` |
| `POST` | `/api/bobi/capabilities/{id}/toggle` | `Capability` — body `{ "enabled": bool }` |

---

## Devices

| Method | Path | Returns |
| --- | --- | --- |
| `GET` | `/api/bobi/devices` | `DeviceList` — `{ devices, rooms, categories }` |
| `GET` | `/api/bobi/devices/{id}` | `Device` |

```json
{
  "id": "living_room_ac",
  "display_name": "מזגן סלון",
  "room": "סלון",
  "category": "climate",
  "state": "off",
  "state_label": "כבוי",
  "available": true,
  "aliases": ["מזגן סלון", "המזגן בסלון"],
  "capabilities": ["turn_on", "turn_off", "set_temperature"],
  "advanced": { "entity_id": "climate.example" }
}
```

Filtering (search, room, category, availability) is done client-side; the
dataset is household-sized.

---

## Automations

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/api/bobi/automations` | `AutomationList` |
| `GET` | `/api/bobi/automations/{id}` | `Automation` |
| `POST` | `/api/bobi/automations/preview` | Body: `AutomationDraft` → `ChangePreview` |
| `POST` | `/api/bobi/automations/confirm` | Body: `{ draft, token }` → `OperationResult` |
| `POST` | `/api/bobi/automations/{id}/delete/preview` | → `ChangePreview` (`destructive: true`) |
| `POST` | `/api/bobi/automations/{id}/delete/confirm` | Body: `{ token }` |
| `POST` | `/api/bobi/automations/{id}/toggle` | Body: `{ enabled }` |
| `POST` | `/api/bobi/automations/{id}/duplicate` | Clone starts disabled |

`summary` and `crosses_midnight` are computed server-side so the card, the
wizard preview and any future WhatsApp confirmation all read identically.

---

## Shabbat

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/api/bobi/shabbat` | `ShabbatConfig` — times, schedules, templates |
| `POST` | `/api/bobi/shabbat/preview` | Body: `ShabbatDraft` → `ChangePreview` |
| `POST` | `/api/bobi/shabbat/confirm` | Body: `{ draft, token }` |
| `POST` | `/api/bobi/shabbat/templates` | Body: `{ name, description, schedules }` |

Each `TimeRange` carries a server-computed `crosses_midnight`. The UI renders
that flag rather than re-deriving it, so the badge and the preview text cannot
disagree.

---

## Notifications, users, tasks and calendar

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/api/bobi/notifications` | `NotificationList` |
| `POST` | `/api/bobi/notifications/{id}/toggle` | Body: `{ enabled }` |
| `GET` | `/api/bobi/users` | `UserList` — users plus the permission catalogue |
| `GET` | `/api/bobi/users/{id}` | `User` |
| `POST` | `/api/bobi/users/{id}/permissions/preview` | Body: `{ permissions }` |
| `POST` | `/api/bobi/users/{id}/permissions/confirm` | Body: `{ payload, token }` |
| `GET` | `/api/bobi/tasks` | `TaskList` — split into open and completed |
| `PATCH` | `/api/bobi/tasks/{id}` | Body: `{ completed?, title? }` |
| `DELETE` | `/api/bobi/tasks/{id}` | `OperationResult` |
| `GET` | `/api/bobi/calendar` | `CalendarList` |

Mock users never contain a real phone number — only a masked hint.

---

## Probe (Test Center)

### `POST /api/bobi/probe`

Runs text through Bobi's understanding pipeline **without executing anything**.
`would_execute` is hard-coded `false` in both the engine and the service layer,
and a regression test asserts it stays that way.

Request: `{ "text": "כבה מזגן הורים ב-1:30 בלילה" }`

```json
{
  "original_text": "כבה מזגן הורים ב-1:30 בלילה",
  "normalized_text": "כבה מזגן הורים ב 1:30 בלילה",
  "family": "schedule",
  "domain": "climate",
  "action": "turn_off",
  "target": { "id": "parents_ac", "name": "מזגן הורים", "matched_alias": "מזגן הורים" },
  "schedule": { "kind": "one_time", "time": "01:30", "date": "2026-08-26" },
  "skill": "local_schedule",
  "safe": true,
  "would_execute": false,
  "warnings": ["הפעולה מתוזמנת לשעת לילה מאוחרת."],
  "steps": [{ "id": "target", "label": "יעד", "status": "ok", "value": "מזגן הורים" }],
  "confidence": 0.93,
  "duration_ms": 4
}
```

`steps` mirrors the pipeline the UI draws:
`טקסט → נרמול → הבנה → יעד → זמן → Skill → בדיקת בטיחות`.

### `GET /api/bobi/probe/history`

The last 20 probes from this process. In-memory, not persisted.

---

## Diagnostics, tests, audit and settings

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/api/bobi/diagnostics` | `DiagnosticsReport` with severity counts |
| `GET` | `/api/bobi/tests` | `TestReport` — regression suites |
| `POST` | `/api/bobi/tests/run` | Re-runs them (mock in Phase 1) |
| `GET` | `/api/bobi/audit?limit=100` | `AuditLog`, newest first |
| `GET` | `/api/bobi/settings` | `SettingsResponse` — secrets already masked |

Diagnostic issues carry both a human `description` and a separate
`technical_details` field, which the UI keeps collapsed.

Settings fields with `secret: true` always carry the literal `"••••••••"`. The
real value never leaves the server process.
