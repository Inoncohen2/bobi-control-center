# Bobi Control Center — Architecture

> Phase 1 status: **mock only**. No real Home Assistant instance is contacted, no
> device is controlled, and no credentials are required.

## 1. Purpose

Bobi Control Center is the management surface for **Bobi**, a Home Assistant based
household assistant. Today, managing Bobi means hand-editing Home Assistant
scripts, helpers, automations and WhatsApp glue logic. This application replaces
that with a calm, Hebrew-first, mobile-first product.

The guiding product rule:

> A household member should be able to manage Bobi without ever learning what an
> `entity_id` is.

Raw Home Assistant identifiers exist in the data model, but they live behind an
explicit **"מתקדם"** (Advanced) disclosure on every screen.

## 2. High-level architecture

```
┌──────────────────────────────────────────────────────────┐
│  React UI  (TypeScript, Vite, Tailwind, RTL)             │
│  pages → features → components                           │
│  data access only via src/api/*  (TanStack Query)        │
└───────────────────────────┬──────────────────────────────┘
                            │  HTTP/JSON — Bobi vocabulary only
                            ▼
┌──────────────────────────────────────────────────────────┐
│  Bobi Management API  (FastAPI routers, app/api/*)        │
│  typed Pydantic request/response models                   │
│  structured errors, no stack traces                       │
└───────────────────────────┬──────────────────────────────┘
                            │  domain objects
                            ▼
┌──────────────────────────────────────────────────────────┐
│  Bobi service layer  (app/services/*)                     │
│  business rules: drafts, previews, cross-midnight logic,  │
│  probe pipeline, audit records, safety model              │
└───────────────────────────┬──────────────────────────────┘
                            │  adapter interface
                            ▼
┌──────────────────────────────────────────────────────────┐
│  HomeAssistantAdapter (abstract, app/adapters/base.py)    │
├──────────────────────────────────────────────────────────┤
│  Phase 1: MockHomeAssistantAdapter    ← active today      │
│  Phase 2: RealHomeAssistantAdapter    ← not implemented   │
└───────────────────────────┬──────────────────────────────┘
                            │  (Phase 2 only)
                            ▼
                    Home Assistant Core
```

### The architectural rule

**The frontend must never know how Bobi is implemented inside Home Assistant.**

Strings such as `script.bobi_local_schedule_parse`, `input_text.*` or
`automation.bobi_*` must not appear anywhere under `frontend/src`, except as
opaque values rendered inside an Advanced panel. There is an automated guard for
this: `backend/tests/test_architecture.py` scans the frontend source tree and
fails the build if a Home Assistant domain prefix is hard-coded in frontend
logic.

The API speaks **Bobi vocabulary** — capabilities, devices, rooms, schedules,
notification rules — never Home Assistant vocabulary.

## 3. Folder structure

```
bobi-control-center/
├── frontend/
│   ├── src/
│   │   ├── api/              # HTTP client + one module per resource
│   │   │   ├── client.ts     # fetch wrapper, structured error mapping
│   │   │   ├── status.ts  devices.ts  capabilities.ts  automations.ts
│   │   │   ├── shabbat.ts  notifications.ts  users.ts  tasks.ts
│   │   │   └── probe.ts  diagnostics.ts  tests.ts  audit.ts  settings.ts
│   │   ├── components/       # dumb, reusable UI primitives
│   │   │   ├── ui/           # Card, Button, Badge, Toggle, Modal, Drawer…
│   │   │   └── state/        # Loading / Empty / Error / QueryBoundary
│   │   ├── features/         # domain logic per area (no HTTP, no JSX-only)
│   │   │   ├── automations/  # wizard state machine, preview builder
│   │   │   ├── shabbat/      # draft reducer, cross-midnight maths
│   │   │   ├── devices/      # filtering + grouping logic
│   │   │   └── probe/        # pipeline step derivation
│   │   ├── hooks/            # useTheme, useDebounce, useConfirm…
│   │   ├── layouts/          # AppLayout, Sidebar, BottomNav, TopBar
│   │   ├── pages/            # one file per route, thin
│   │   ├── types/            # TS mirrors of the API's Pydantic models
│   │   ├── utils/            # time, format, cn
│   │   └── App.tsx           # routes only
│   ├── public/
│   ├── index.html
│   ├── package.json
│   ├── tailwind.config.js
│   ├── vite.config.ts
│   └── vitest.setup.ts
│
├── backend/
│   ├── app/
│   │   ├── api/              # FastAPI routers, one per resource
│   │   ├── adapters/
│   │   │   ├── base.py       # HomeAssistantAdapter ABC
│   │   │   ├── mock.py       # MockHomeAssistantAdapter
│   │   │   └── real.py       # RealHomeAssistantAdapter (Phase 2 stub)
│   │   ├── models/           # Pydantic domain + response models
│   │   ├── services/         # BobiService, ProbeService, AuditService…
│   │   ├── mock/             # Hebrew fixture data
│   │   ├── errors.py         # structured error envelope
│   │   ├── config.py         # pydantic-settings
│   │   └── main.py           # app factory, static serving, security headers
│   ├── tests/
│   └── requirements.txt
│
├── addon/                    # Home Assistant Add-on skeleton
│   ├── config.yaml  Dockerfile  run.sh  DOCS.md
│
├── docs/
│   ├── architecture.md  api.md  home-assistant-integration.md
│
├── .env.example  .gitignore  docker-compose.yml  Dockerfile
├── package.json              # root dev orchestration
├── README.md  LICENSE
```

## 4. Data flow

### Read path (e.g. the devices page)

1. `DevicesPage` calls `useDevices()`.
2. The hook calls `fetchDevices()` in `src/api/devices.ts` through TanStack Query.
3. `GET /api/bobi/devices` hits `app/api/devices.py`.
4. The router asks `BobiService.list_devices()`.
5. The service calls `adapter.get_entities()` and maps HA-shaped records into the
   **Bobi device model**: `display_name`, `room`, `category`, `aliases`,
   `capabilities`, plus an `advanced.entity_id` field.
6. FastAPI serialises the typed model; the frontend renders friendly objects.

Filtering (search / room / category / availability) happens client-side in
`features/devices/filter.ts` because the dataset is household-sized.

### Write path (Phase 1: drafts only)

Every impactful change follows the **Preview → Confirm → Execute** model:

```
user edits a draft   →  POST …/preview   →  human-readable summary
                                          ↓
                              user confirms in the UI
                                          ↓
                        POST …/confirm  →  execute + audit record + result
```

In Phase 1 the "execute" step writes to an in-memory store only and returns
`applied: false, dry_run: true`. Nothing leaves the process. The service layer
already emits an audit record for every write so the audit trail is complete on
day one of Phase 2.

Actions that require explicit confirmation: delete automation, delete a Shabbat
configuration, bulk disable, change user permissions, remove a capability,
restore a backup. Simple reads and navigation never prompt.

### The probe pipeline (Test Center)

`POST /api/bobi/probe` is deliberately **probe-only**: it models Bobi's natural
language pipeline and always returns `would_execute: false`.

```
text → normalise → classify family → resolve target → resolve schedule
     → select skill → safety check → ProbeResult
```

`ProbeService` implements each stage as a separate pure function so the UI can
render the pipeline as discrete, inspectable steps and so each stage is unit
testable. Resolution of a spoken target ("המזגן בסלון") to a device uses the
device `aliases` list, which is why aliases are a first-class field.

## 5. Adapter contract

`app/adapters/base.py` defines the only seam between Bobi's domain logic and Home
Assistant:

```python
class HomeAssistantAdapter(ABC):
    async def get_system_status(self) -> SystemStatus: ...
    async def get_entities(self) -> list[RawEntity]: ...
    async def get_automations(self) -> list[Automation]: ...
    async def get_capabilities(self) -> list[Capability]: ...
    async def preview_text(self, text: str) -> ProbeResult: ...
    async def get_shabbat_config(self) -> ShabbatConfig: ...
    async def save_shabbat_config(self, cfg: ShabbatConfig) -> ShabbatConfig: ...
    async def get_users(self) -> list[User]: ...
    async def get_diagnostics(self) -> list[DiagnosticIssue]: ...
    # …plus notifications, tasks, calendar, tests, settings
```

Selection happens once, in `config.py` / the app factory:

```python
adapter = (
    RealHomeAssistantAdapter(settings)      # BOBI_ADAPTER=real
    if settings.adapter == "real"
    else MockHomeAssistantAdapter()          # default
)
```

It is injected into `BobiService` and reached in routers via a FastAPI
dependency. **No router, service or test imports a concrete adapter directly.**

### Replacing Mock with Real

Because the adapter returns **domain models, not HA payloads**, Phase 2 is
additive:

| Concern | Phase 1 (Mock) | Phase 2 (Real) |
| --- | --- | --- |
| Source of truth | Hebrew fixtures in `app/mock/` | HA REST + WebSocket API |
| Auth | none | `SUPERVISOR_TOKEN` (add-on) or a long-lived token, **server-side only** |
| Entity → device | fixture table | HA entity/device/area registries + a Bobi mapping file |
| Writes | in-memory, `dry_run: true` | real service calls, still behind Preview → Confirm |
| Live updates | none | HA WebSocket `state_changed` → `/api/bobi/ws` fan-out |

The steps are:

1. Implement `RealHomeAssistantAdapter` against the same ABC.
2. Set `BOBI_ADAPTER=real` plus connection settings.
3. Run the identical adapter conformance test suite
   (`backend/tests/test_adapter_contract.py`) against it — it is written against
   the ABC, not the mock, so it applies to both implementations unchanged.

**The frontend requires zero changes.** That is the point of the seam.

## 6. Error handling

The backend never leaks a traceback. Exception handlers convert everything into:

```json
{ "code": "automations_unavailable", "message": "לא הצלחתי לטעון את האוטומציות", "details": {} }
```

The frontend's `ApiError` carries `code`, a Hebrew `message` for the user, and
`details` rendered only under **"פרטים טכניים"**.

Every page implements four states: loading, empty, error, normal — provided
centrally by the `QueryBoundary` component so the behaviour is consistent.

## 7. Security posture

- No secret is ever sent to the browser; settings endpoints return `"••••••••"`
  for masked fields and the raw values never leave the process.
- No Home Assistant token in `localStorage` or any browser storage.
- All future Home Assistant traffic is server-side only.
- `.env.example` is committed; `.env` is git-ignored.
- Security headers (`X-Content-Type-Options`, `X-Frame-Options` relaxed for
  Ingress, `Referrer-Policy`, CSP) are applied by middleware.
- Mock data contains only invented names and reserved-range phone numbers.

## 8. Deployment

- **Development**: Vite dev server on `:5173` proxies `/api` to uvicorn on `:8000`.
- **Production**: `npm run build` emits static files; FastAPI mounts them and
  serves an SPA fallback. One process, one container.
- **Home Assistant Add-on**: the same image, started by `run.sh`, exposed through
  Ingress. `GET /health` is the health endpoint. See
  `docs/home-assistant-integration.md`.
