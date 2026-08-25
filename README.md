<div dir="rtl">

# 🤖 בובי — מרכז ניהול

</div>

**Bobi Control Center** — the management interface for *Bobi*, a Home Assistant
based household assistant. Hebrew-first, RTL, mobile-first.

> ### ⚠️ Phase 1: mock data only
>
> This application **cannot** reach a real Home Assistant. It controls no
> devices, creates no automations or calendar events, touches no tasks, sends no
> WhatsApp messages, and needs no credentials. Every write is a dry run against
> in-memory state, and `POST /api/bobi/probe` always answers
> `would_execute: false`.
>
> The seam that makes this true — and that makes Phase 2 a one-line change — is
> described in [`docs/architecture.md`](docs/architecture.md).

---

## Quick start

Requires **Node 20+** and **Python 3.11+**.

```bash
git clone https://github.com/inoncohen2/bobi-control-center.git
cd bobi-control-center

# Install frontend deps, create a venv, install backend deps
npm run setup

# Backend on :8000 and frontend on :5173, together
npm install          # root dev orchestration
npm run dev
```

Open **http://localhost:5173**. The Vite dev server proxies `/api` to the
backend, so the frontend calls same-origin paths in every mode.

No `.env` is needed. To customise anything, `cp .env.example .env` — it is
git-ignored.

### Running the two halves separately

```bash
# Backend — http://localhost:8000  (API docs at /api/docs)
cd backend && ../.venv/bin/python -m uvicorn app.main:app --reload --port 8000

# Frontend — http://localhost:5173
cd frontend && npm install && npm run dev
```

---

## Commands

Every command below is runnable from the repository root.

| Command | What it does |
| --- | --- |
| `npm run setup` | Install frontend deps, create `.venv`, install backend deps |
| `npm run dev` | Backend and frontend together, both with reload |
| `npm run dev:backend` | Backend only, on `:8000` |
| `npm run dev:frontend` | Frontend only, on `:5173` |
| `npm run build` | Compile the frontend to `frontend/dist` |
| `npm test` | Backend (pytest) then frontend (Vitest) |
| `npm run test:backend` | `pytest` — 118 tests |
| `npm run test:frontend` | `vitest run` — 65 tests |
| `npm run lint` | `ruff` on the backend, `eslint` on the frontend |
| `npm run typecheck` | `tsc -b --noEmit` |
| `npm run check` | Lint, typecheck and test — run this before committing |
| `npm run docker:build` | Build the single production image |
| `npm run docker:run` | Run it on `:8000` |

Backend equivalents without the npm wrapper:

```bash
cd backend
../.venv/bin/python -m pytest -q                 # tests
../.venv/bin/python -m uvicorn app.main:app --reload
cd .. && .venv/bin/ruff check backend/           # lint
```

---

## Production

One process serves both the API and the compiled UI.

```bash
npm run build                          # emits frontend/dist
cp -r frontend/dist backend/app/static # FastAPI serves this
cd backend && ../.venv/bin/python -m uvicorn app.main:app --port 8000
```

### Docker

```bash
docker build -t bobi-control-center:latest .
docker run --rm -p 8000:8000 bobi-control-center:latest
```

or:

```bash
docker compose up --build
```

Then open **http://localhost:8000**. The image builds the frontend in a
separate stage, runs as a non-root user, and exposes `GET /health` for the
Docker healthcheck and the Home Assistant watchdog.

---

## Pages

All Hebrew, all RTL, each with loading / empty / error / normal states, in light
and dark mode.

| Route | Page | What it shows |
| --- | --- | --- |
| `/` | **בית** | Health cards (בובי · WhatsApp · AI · Home Assistant), five statistics, a "מה קורה עכשיו" activity timeline, and "דורש תשומת לב" warnings phrased for a person, with technical detail collapsed |
| `/capabilities` | **יכולות** | What Bobi can do, grouped, each toggleable with a settings drawer |
| `/devices` | **מכשירים** | Friendly devices grouped by room, with search (name, room, or spoken alias) and room/category/availability filters |
| `/automations` | **אוטומציות** | Bobi-shaped automation cards with edit / disable / duplicate / delete, and a 7-step creation wizard |
| `/shabbat` | **שעון שבת** | Candle-lighting times, templates, per-device schedules with multiple ranges, and an explicit **+ יום הבא** badge on windows that cross midnight |
| `/notifications` | **הודעות חכמות** | Smart notification rules: recipients, lead time, quiet hours, conditions, cooldown |
| `/tasks` | **משימות ויומן** | Open and completed tasks, upcoming events, and which Bobi features react to each |
| `/users` | **משתמשים** | Household profiles and an interactive permissions matrix |
| `/test-center` | **בדיקות** | Write anything to Bobi and watch it be parsed — **without executing** |
| `/tests` | Automated suites | Regression suites with pass counts and a re-run button |
| `/diagnostics` | **תקלות** | Issues grouped as תקין / אזהרות / שגיאות, each with a suggested action |
| `/audit` | Audit log | Every change: who, what, before/after, and from where |
| `/settings` | **הגדרות** | Nine sections. Secrets always render as `••••••••` |

On desktop the navigation is a sidebar on the right; on mobile it is a bottom
bar with five destinations plus **עוד**, with safe-area padding for iPhone.

### The Test Center

The most important safety surface. Type something you would send Bobi, press
**"בדוק בלי לבצע"**, and the response is rendered as a pipeline:

```
טקסט → נרמול → הבנה → יעד → זמן → Skill → בדיקת בטיחות
```

with a prominent **✅ בדיקה בלבד — לא בוצעה שום פעולה** banner, any warnings,
and the raw JSON available to copy. `would_execute` is `false` by construction,
not by configuration.

---

## Architecture

```
React UI  →  Bobi Management API  →  BobiService  →  HomeAssistantAdapter
                                                      ├── MockHomeAssistantAdapter  (active)
                                                      └── RealHomeAssistantAdapter  (Phase 2)
```

The rule the whole project rests on:

> **The frontend never knows how Bobi is implemented inside Home Assistant.**

No `entity_id`, `input_text.*` or `script.*` appears in frontend logic. Such
values exist in the data model under an `advanced` block, shown only behind a
**"מתקדם"** disclosure. Two tests in
`backend/tests/test_architecture.py` enforce this on every run.

- [`docs/architecture.md`](docs/architecture.md) — layers, data flow, folder layout
- [`docs/api.md`](docs/api.md) — every endpoint with examples
- [`docs/home-assistant-integration.md`](docs/home-assistant-integration.md) — the Phase 2 plan

### Preview → Confirm

Impactful changes are always two calls. `preview` returns a human-readable
summary plus an opaque token; `confirm` requires that token *and* an identical
payload. A client cannot skip the preview or confirm something other than what
the user saw on screen.

---

## Testing

```bash
npm test          # 118 backend + 65 frontend
```

Backend (`pytest`) covers the status, capability, device, automation,
serialization, probe, Shabbat and diagnostic endpoints; the adapter conformance
contract; and the architectural guards. Frontend (`Vitest` + Testing Library)
covers dashboard rendering, device filtering, the capability toggle, the
automation preview gate, the Shabbat cross-midnight indicator and the Test
Center pipeline.

---

## Security

- No secret is ever sent to the browser; masked as `••••••••` server-side.
- No Home Assistant token in `localStorage` or any browser storage — the only
  thing stored locally is the light/dark theme preference.
- All future Home Assistant traffic is server-side only.
- `.env` is git-ignored; only `.env.example` is committed, with empty values.
- Security headers (CSP, `X-Content-Type-Options`, `Referrer-Policy`,
  `Permissions-Policy`) are applied by middleware.
- Mock data uses invented names and masked phone hints only. A test fails the
  build if anything resembling a real phone number appears in the fixtures.

---

## Home Assistant Add-on

`addon/` contains the skeleton: `config.yaml` (Ingress, permissions, options
schema, `/health` watchdog), `Dockerfile` and `run.sh`. It is **not published
yet** — see [`addon/DOCS.md`](addon/DOCS.md).

---

## Project layout

```
bobi-control-center/
├── frontend/src/{api,components,features,hooks,layouts,pages,types,utils}
├── backend/app/{api,adapters,models,services,mock}
├── backend/tests/
├── addon/{config.yaml,Dockerfile,run.sh,DOCS.md}
├── docs/{architecture.md,api.md,home-assistant-integration.md}
└── Dockerfile · docker-compose.yml · .env.example
```

## License

MIT — see [LICENSE](LICENSE).
