# The Bobi Control Center bridge

How this app talks to Home Assistant, and why it cannot do anything else.

## The contract

Home Assistant exposes a stable set of `script.bobi_cc_*` services. They are the
**only** contract between this app and Bobi. The app never enumerates entities,
never reads arbitrary states, and never inspects Bobi's internal scripts,
helpers or WhatsApp logic.

| Bridge service | Parameters | App endpoint |
| --- | --- | --- |
| `script.bobi_cc_status` | — | `GET /api/bobi/status` |
| `script.bobi_cc_devices` | `scope`, `include_unavailable` | `GET /api/bobi/devices` |
| `script.bobi_cc_capabilities` | — | `GET /api/bobi/capabilities` |
| `script.bobi_cc_users` | — | `GET /api/bobi/users` |
| `script.bobi_cc_shabbat` | — | `GET /api/bobi/shabbat` |
| `script.bobi_cc_rules` | — | `GET /api/bobi/rules` |
| `script.bobi_cc_tasks` | — | `GET /api/bobi/tasks` |
| `script.bobi_cc_diagnostics` | — | `GET /api/bobi/diagnostics` |
| `script.bobi_cc_probe` | `text` | `POST /api/bobi/probe` |

Device scopes: `all`, `lighting`, `climate`, `cameras`, `battery`,
`temperature`, `humidity`, `vacuum`, `people`, `switches`, `scent`.

## How a call is made

```
POST http://supervisor/core/api/services/script/bobi_cc_probe?return_response
Authorization: Bearer ${SUPERVISOR_TOKEN}
Content-Type: application/json

{"text": "כבה מזגן הורים ב-1:30 בלילה"}
```

`?return_response` is what makes a script hand data back rather than just fire.

`RealHomeAssistantAdapter.call_service()` is the single method that does this.
It is reused by all nine endpoints and:

- refuses any service outside the nine-item allow-list, **before** issuing a
  request;
- unwraps the response defensively (see below);
- converts every Home Assistant failure into the app's structured error shape.

### Response unwrapping

Home Assistant has shipped more than one shape for a service-call response, so
`extract_service_response()` handles all of them:

| Received | Returned |
| --- | --- |
| `{"service_response": {...}}` | the inner object |
| `{...}` | itself |
| `[{"service_response": {...}}]` | the inner object |
| `[{...}]` | the single element |
| `{"response": {...}}` | the inner object |
| `[]` | `None` |

Anything else is reported as `bridge_bad_shape` rather than guessed at.

### Errors

Nothing is swallowed. Each failure becomes `{code, message, details}` with a
Hebrew message safe to display:

| Situation | `code` | What the user sees |
| --- | --- | --- |
| Script not installed | `bridge_service_missing` | *שירות הגשר … לא נמצא ב-Home Assistant* |
| Token rejected | `ha_unauthorized` | *אין הרשאה לגשת ל-Home Assistant* |
| HA returned 5xx | `ha_error` | *Home Assistant החזיר שגיאה* |
| Timeout / transport | `upstream_unavailable` | *Home Assistant לא הגיב בזמן* |
| Unparseable payload | `bridge_bad_shape` | *התקבל מבנה נתונים לא צפוי* |

The frontend distinguishes these from bugs and renders
*"לא הצלחתי לקבל נתונים מ-Home Assistant"* with the code collapsed under
**פרטים טכניים**.

## Authentication

The Supervisor injects `SUPERVISOR_TOKEN` because `config.yaml` declares
`homeassistant_api: true`. Rules enforced in code and asserted by tests:

1. The token is read from the environment via a property, never stored as a
   settings field — so `model_dump()` cannot serialise it.
2. It appears only in the outgoing `Authorization` header.
3. It is never logged; no logging call in the adapter touches headers or the
   token.
4. It never reaches the browser. React calls FastAPI; FastAPI calls Home
   Assistant.
5. No long-lived access token is ever created or requested.

## Adapter selection

```
BOBI_ADAPTER=auto (default)
├── SUPERVISOR_TOKEN present → RealHomeAssistantAdapter
└── otherwise                → MockHomeAssistantAdapter
```

`mock` and `real` can be forced explicitly. Asking for `real` without a token
falls back to mock with a warning, rather than issuing requests that would all
fail with 401.

Both adapters return identical models, so the frontend cannot tell them apart —
which is what makes local development faithful.

## Why writes are impossible

Read-only is structural, not a convention:

- `HomeAssistantAdapter` declares **no write method**. There is nothing for an
  adapter to implement, and adding one means editing the interface.
- The real adapter's `ALLOWED_SERVICES` contains exactly the nine bridge
  scripts. `call_service("script", "anything_else")` raises before a request is
  built — verified by a test that asserts no HTTP call was attempted.
- The API exposes exactly one non-GET route: `POST /api/bobi/probe`. A test
  enumerates the router and asserts that.
- `would_execute` is hard-coded `False` in both adapters and restated by the
  response model. It is never derived from what the bridge returned.
- `writes_enabled` is forced to `False` on status and Shabbat responses even if
  the bridge says otherwise.

## Data the app deliberately does not touch

| Not touched | Why |
| --- | --- |
| Raw entity states | The bridge's device catalog is the contract |
| Bobi's scripts, helpers, automations | Not the app's concern |
| WhatsApp numbers and LIDs | The bridge withholds them; the app must not reintroduce them |
| Task internal descriptions | The bridge sanitises them |
| Native HA automations | `bobi_cc_rules` returns Bobi's canonical rules instead |

## Phase 3: enabling writes

1. Add write methods to `HomeAssistantAdapter` — one per bridge write service.
2. Extend `ALLOWED_SERVICES` with those service names.
3. Implement them in the real adapter; the mock mutates in-memory state.
4. Flip `writes_enabled` once the write paths are trusted.
5. Replace the `DisabledAction` / `NextPhaseBadge` components with live
   controls. The UI already renders them in the right places.

Keep the Preview → Confirm model from Phase 1 for anything destructive.
