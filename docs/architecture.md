# Bobi Control Center — Architecture

> **Bridge-only access.** Read screens call Bobi's read bridges. A state change
> can run only through a published management bridge after preview, explicit
> confirmation and read-after-write verification. The app cannot call a device
> or Home Assistant entity directly.

## 1. Purpose

Bobi Control Center is the management surface for **Bobi**, a Home Assistant
based household assistant. It runs as a Home Assistant App behind Ingress.

The guiding product rule:

> A household member should be able to manage Bobi without ever learning what an
> `entity_id` is.

Technical identifiers exist in the data model but live behind an explicit
**"מתקדם / פרטים טכניים"** disclosure on every screen.

## 2. High-level architecture

```
┌──────────────────────────────────────────────────────────┐
│  React UI  (TypeScript, Vite, Tailwind, RTL, HashRouter) │
│  pages → features → components                           │
│  data access only via src/api/*  (TanStack Query)        │
└───────────────────────────┬──────────────────────────────┘
                            │  HTTP/JSON, relative to the Ingress prefix
                            ▼
┌──────────────────────────────────────────────────────────┐
│  FastAPI  (app/api/*)                                     │
│  typed responses, structured errors, no stack traces      │
└───────────────────────────┬──────────────────────────────┘
                            │  bridge contract models
                            ▼
┌──────────────────────────────────────────────────────────┐
│  services/normalize.py                                    │
│  raw bridge shapes → the canonical contract               │
│  the ONLY module that knows bridge field names            │
└───────────────────────────┬──────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────┐
│  HomeAssistantAdapter (abstract — no write method)        │
├──────────────────────────────────────────────────────────┤
│  RealHomeAssistantAdapter  ← SUPERVISOR_TOKEN present     │
│  MockHomeAssistantAdapter  ← everywhere else              │
└───────────────────────────┬──────────────────────────────┘
                            │  POST …/services/script/bobi_cc_*?return_response
                            │  Authorization: Bearer $SUPERVISOR_TOKEN
                            ▼
              Home Assistant Core (via the Supervisor proxy)
                            │
                            ▼
              Bobi's bridge scripts (read-only + probe)
```

### Two rules the design rests on

**1. The browser never talks to Home Assistant.** React calls FastAPI; FastAPI
calls the Supervisor. The token stays in the backend process. A test fails the
build if the frontend references `supervisor/core`, `SUPERVISOR_TOKEN`,
`hassio_ingress` or a `Bearer ` header.

**2. Only the bridge is called.** The app does not enumerate entities or inspect
Bobi's internals. The nine `bobi_cc_*` services are the contract, enforced by an
allow-list checked before any request is issued.

## 3. Folder structure

```
bobi-control-center/
├── repository.yaml               # Home Assistant custom apps repository
├── bobi_control_center/          # the app — self-contained build context
│   ├── config.yaml               # ingress 8099, homeassistant_api, watchdog
│   ├── Dockerfile                # stage 1: Vite build · stage 2: FastAPI
│   ├── run.sh                    # entrypoint; reads options via bashio
│   ├── DOCS.md                   # shown inside Home Assistant
│   ├── frontend/src/
│   │   ├── api/                  # client.ts (Ingress-safe URLs) + bobi.ts
│   │   ├── components/ui/        # Card, Button, Badge, Modal, ReadOnly, Advanced
│   │   ├── components/state/     # QueryBoundary: loading/disconnected/error/empty
│   │   ├── features/             # devices/filter.ts, probe/pipeline.ts
│   │   ├── hooks/                # queries.ts, useTheme.ts
│   │   ├── layouts/              # AppLayout, navigation
│   │   ├── pages/                # one per screen, thin
│   │   ├── types/api.ts          # mirrors the bridge models
│   │   └── utils/                # cn, format
│   └── backend/app/
│       ├── adapters/             # base.py (ABC) · real.py · mock.py
│       ├── api/                  # routes.py · deps.py
│       ├── models/bridge.py      # the bridge contract
│       ├── mock/bridge_data.py   # fixtures in the same shape
│       ├── config.py errors.py main.py
└── docs/
```

## 4. The canonical contract and normalization

`models/bridge.py` defines one model per resource. These are **not** the shapes
Home Assistant sends: the bridge names its collections `entries`, `registry`,
`upcoming`/`profiles`/`drafts` and per-user `users`, and nests the probe answer
under `result`.

`services/normalize.py` is the only module that knows those names. Everything
above it — routes, and therefore React — sees one clean schema.

| Bridge sends | Canonical response |
| --- | --- |
| `entries` | `devices` (plus derived `areas`, `groups`, `available`) |
| `registry` (map or list) | `capabilities` |
| status sections (`whatsapp`, `ai`, `users`, `config`, `features`) | first-class fields + a derived `components` health row |
| domain limits (`min_temp`, `preset_modes`, `min_kelvin`, `scent_slots`, …) | one `limits` model keeping all of them, plus a generic `min`/`max`/`step` |
| `upcoming` + `profiles` + `drafts` | flat times + one `profiles` list + `has_draft` |
| profile `tokens` + `device_labels` | `devices: [{id, label}]` |
| `ac_temperatures` map | a list, each temperature tied to its air conditioner |
| per-user `users` | one flat `tasks` list with `owner` and `list_name` |
| `{"result": {...}}` | flattened probe fields |
| `checks` as a **map** | `checks` as a list |

Three properties make it safe:

- **One representation.** A response carries exactly one collection per
  resource. There is never a populated list beside an empty legacy one — the
  bug this layer was written to fix.
- **Nothing dropped.** Unmapped fields land in a per-item `extra` map, surfaced
  in the Advanced panel, so a growing registry shows up rather than vanishing.
  This extends to values the contract *could* have flattened away: a climate
  device's mode lists and a profile's device tokens are kept, because Phase 3's
  editing controls will need exactly those.
- **Tolerant.** A collection may arrive as a map or a list; a field may be
  missing or oddly typed. A partial response produces an empty screen, not a
  502. `checks` arriving as a map is exactly what used to 502 the diagnostics
  endpoint.

Both adapters run through the same normalizer, and the mock emits raw payloads
in the real bridge shape — so mock mode is a rehearsal of the real path, not a
parallel one.

## 5. Data flow

### Read path (the devices page)

1. `DevicesPage` calls `useDevices(scope, includeUnavailable)`.
2. The hook calls `fetchDevices()` in `src/api/bobi.ts`.
3. `client.ts` prefixes the path with the Ingress base derived from
   `location.pathname`.
4. `GET /api/bobi/devices?scope=…` reaches `app/api/routes.py`, which validates
   the scope against the bridge's list.
5. `RealHomeAssistantAdapter.get_devices()` POSTs to
   `…/services/script/bobi_cc_devices?return_response`.
6. The response is unwrapped, then `normalize_devices()` maps `entries` onto the
   canonical `BridgeDevices`.

Scope is a **bridge** parameter, so changing it refetches. Search, area and
availability filters are client-side over the returned set.

### The probe path

`POST /api/bobi/probe` → `script.bobi_cc_probe`, which Home Assistant runs with
`probe_only=true`. The bridge nests its answer under `result`;
`normalize_probe()` flattens it and asserts the safety invariants.
`features/probe/pipeline.ts` then derives the visual stages from the flat
result, as a pure function so every branch is testable without React.

## 6. Ingress

Home Assistant serves the app from a generated prefix that changes between
sessions and cannot be known at build time. Three things make that work:

| Concern | Solution |
| --- | --- |
| Router touching the path | **HashRouter** — routes live in the fragment |
| Asset URLs | Vite `base: './'` — every asset is relative |
| API URLs | Derived at runtime from `location.pathname` |

This is verified end-to-end by a test that serves the app through a simulated
`/api/hassio_ingress/<token>/` prefix and asserts that every API call stays
inside it, across direct load, internal navigation and browser refresh.

## 7. Read-only, structurally

| Guarantee | How it is enforced |
| --- | --- |
| No write method exists | `HomeAssistantAdapter` declares none |
| Only the bridge is reachable | `ALLOWED_SERVICES` checked before the request |
| One non-GET route | A test enumerates the router |
| The probe cannot execute | `would_execute=False` hard-coded in the normalizer, and the model's default |
| An execution claim cannot hide | A bridge reporting `executed: true` still yields `false`, plus a visible warning |
| The UI offers no write control | Disabled controls labelled *"עריכה תהיה זמינה בשלב הבא"* |

## 8. Error handling

The backend never leaks a traceback. Everything becomes:

```json
{ "code": "bridge_service_missing", "message": "…", "details": {} }
```

The frontend's `ApiError.isDisconnected` separates *Home Assistant is
unreachable* from *this is a bug*, so a missing bridge script reads as
"לא הצלחתי לקבל נתונים מ-Home Assistant" rather than an error page. The code and
status live under **פרטים טכניים**.

Every screen implements loading, disconnected, error, empty and normal states
via the shared `QueryBoundary`.

## 9. Security

- `SUPERVISOR_TOKEN` is a property reading the environment, not a settings
  field, so `model_dump()` cannot serialise it.
- It appears only in an outgoing `Authorization` header; no logging call in the
  adapter touches headers or the token.
- Response bodies are logged only when `debug_http` is explicitly enabled.
- No long-lived access token is created or requested.
- No phone numbers or LIDs: the bridge withholds them and the UI shows only
  connection status.

## 10. Load

Every fetch is a Home Assistant service call, so polling is deliberately modest:

| Screen | Interval |
| --- | --- |
| Dashboard, devices | 20s |
| Diagnostics | 60s |
| Capabilities, users, Shabbat, rules, tasks | on entry only |
| Test Center | explicit button press only |

`refetchIntervalInBackground` is false, so polling stops while the tab is
hidden. Measured in the real install at ~0.08% CPU and ~44 MB.

## 11. Deployment

- **Development**: Vite on `:5173` proxies `/api` to uvicorn on `:8099`; no
  token means mock data.
- **Production**: one container. Stage 1 builds the frontend, stage 2 runs
  FastAPI serving both the API and the compiled SPA on `0.0.0.0:8099`.
- **Home Assistant**: the Supervisor builds the same Dockerfile with
  `--build-arg BUILD_FROM=<arch base>` and reaches it through Ingress.
