<div dir="rtl">

# 🤖 בובי — מרכז ניהול

</div>

**Bobi Control Center** — a Home Assistant App that gives *Bobi*, a Hebrew
household assistant, a management interface. Hebrew-first, RTL, mobile-first,
served through Home Assistant Ingress.

> ### 🔒 Phase 2 is **read-only**
>
> The app calls only Bobi's `script.bobi_cc_*` bridge services, every one of
> which is a read or a probe. It cannot turn on a light, change a schedule,
> complete a task, or save a Shabbat configuration. The adapter interface has
> no write method to implement, so this is structural rather than a matter of
> discipline.

---

## Install in Home Assistant

1. **Add this repository.**
   Settings → Add-ons → Add-on Store → ⋮ (top right) → **Repositories**, then
   paste:

   ```
   https://github.com/Inoncohen2/bobi-control-center
   ```

2. **Install.** Refresh the store, open **Bobi Control Center**, click
   **Install**. The image builds on first install, which takes a few minutes.

3. **Start** the app.

4. **Open Web UI.** The app appears in the store page as *Open Web UI*.

5. *(Optional)* Toggle **Show in sidebar** to get a **Bobi** entry in the Home
   Assistant sidebar.

   `ingress_panel` is Supervisor-owned state, not a manifest key: it starts
   `false` for every Ingress app and this toggle is what turns it on. The
   manifest supplies the panel's title and icon so the result looks right. By
   default the entry is admin-only (`panel_admin: true`) — change that in
   `config.yaml` if every household member should see it.

There is **no token to paste**. The Supervisor injects `SUPERVISOR_TOKEN`
because the app declares `homeassistant_api: true`, and the backend uses it
server-side only.

### Requirements

Bobi's bridge scripts must exist in your Home Assistant:

`script.bobi_cc_status` · `bobi_cc_devices` · `bobi_cc_capabilities` ·
`bobi_cc_users` · `bobi_cc_shabbat` · `bobi_cc_rules` · `bobi_cc_tasks` ·
`bobi_cc_diagnostics` · `bobi_cc_probe`

If one is missing, the affected screen says so plainly rather than failing:
*"שירות הגשר … לא נמצא ב-Home Assistant"*.

### Options

| Option | Values | Default | Meaning |
| --- | --- | --- | --- |
| `log_level` | `debug` / `info` / `warning` / `error` | `info` | Add-on log verbosity. |
| `debug_http` | `true` / `false` | `false` | Log bridge request/response bodies. Off by default so household data never lands in the log. |

---

## Screens

All Hebrew and RTL, each with loading, disconnected, error, empty and normal
states, in light and dark mode.

| Screen | Bridge service | Shows |
| --- | --- | --- |
| **בית** | `bobi_cc_status` + `bobi_cc_diagnostics` | Component health, WhatsApp, AI and its fast paths, household members, feature toggles, counts, and what needs attention |
| **מכשירים** | `bobi_cc_devices` | Bobi's canonical catalog by room, with the 11 semantic scopes, alias search and availability filters |
| **יכולות** | `bobi_cc_capabilities` | The Capability Registry rendered dynamically — label, example, risk — plus read-only master toggles |
| **כללים חכמים** | `bobi_cc_rules` | Bobi's canonical smart rules |
| **שעון שבת** | `bobi_cc_shabbat` | Candle lighting, havdalah, the pre-Shabbat offset, the profiles and their devices, AC temperatures |
| **משימות** | `bobi_cc_tasks` | Open and completed tasks |
| **משתמשים** | `bobi_cc_users` | Household profiles and a read-only permissions matrix |
| **בדיקות** | `bobi_cc_probe` | Type anything and watch Bobi parse it — **without executing** |
| **תקלות** | `bobi_cc_diagnostics` | Issues grouped by severity, with the checks that ran |
| **הגדרות** | — | Connection state, versions, theme |

### The Test Center

The most important safety surface. Type something you would send Bobi, press
**"בדוק בלי לבצע"**, and the bridge runs Bobi's real Skill Dispatcher with
`probe_only=true`. The response is drawn as a pipeline:

```
טקסט → הבנה → יעד → תזמון → Skill → בדיקת בטיחות
```

built from the bridge's own `handled`, `status`, `terminal`, `skill`,
`understanding` and `schedule_*` fields, under a prominent
**בדיקה בלבד — לא בוצעה שום פעולה** banner.

### Load

Every refresh is a Home Assistant service call, so polling is deliberately
modest: dashboard and devices every 20s, diagnostics every 60s, and everything
else on entry only. Polling stops entirely while the tab is hidden. Measured in
the real install at ~0.08% CPU and ~44 MB.

### Technical detail stays hidden

`entity_id`, `handler`, `domain` and raw tokens appear **only** inside a
collapsed **"מתקדם / פרטים טכניים"** disclosure. An automated test fails the
build if an entity id is hard-coded in frontend logic.

---

## Architecture

```
React (HashRouter)  →  FastAPI  →  http://supervisor/core/api  →  script.bobi_cc_*
                                   Authorization: Bearer $SUPERVISOR_TOKEN
```

The browser never talks to the Supervisor. All Home Assistant traffic is
server-side, and the token never leaves the backend process.

```
HomeAssistantAdapter (abstract, read-only)
├── RealHomeAssistantAdapter   ← used when SUPERVISOR_TOKEN is present
└── MockHomeAssistantAdapter   ← used everywhere else, same bridge shapes
```

The adapter is selected automatically. Both return identical models, so local
development exercises the same UI paths as production.

- [`docs/architecture.md`](docs/architecture.md) — layers, data flow, adapters
- [`docs/api.md`](docs/api.md) — every endpoint with examples
- [`docs/home-assistant-integration.md`](docs/home-assistant-integration.md) — the bridge contract

---

## Local development

Requires **Node 20+** and **Python 3.11+**. No Home Assistant needed — without
`SUPERVISOR_TOKEN` the app serves mock data in the exact bridge shape.

```bash
git clone https://github.com/Inoncohen2/bobi-control-center.git
cd bobi-control-center

npm run setup     # frontend deps + venv + backend deps
npm install       # root dev orchestration
npm run dev       # backend :8099, frontend :5173
```

Open **http://localhost:5173**.

### Commands

| Command | What it does |
| --- | --- |
| `npm run dev` | Backend and frontend together, both with reload |
| `npm run build` | Compile the frontend |
| `npm test` | Backend (pytest) then frontend (Vitest) |
| `npm run lint` | ruff + eslint |
| `npm run typecheck` | `tsc -b --noEmit` |
| `npm run check` | Lint, typecheck and test — run before committing |
| `npm run docker:build` | Build the app image |
| `npm run docker:run` | Run it on `:8099` |

### Running the container directly

```bash
docker build -t bobi-control-center:latest bobi_control_center/
docker run --rm -p 8099:8099 bobi-control-center:latest
```

Then open **http://localhost:8099**. Without a token it starts in mock mode and
says so on the dashboard.

---

## Repository layout

```
bobi-control-center/
├── repository.yaml              # marks this a Home Assistant apps repository
├── bobi_control_center/         # the app — a self-contained build context
│   ├── config.yaml              # app manifest (ingress 8099, homeassistant_api)
│   ├── Dockerfile               # multi-stage: Vite build → FastAPI runtime
│   ├── run.sh                   # entrypoint, reads options via bashio
│   ├── frontend/                # React + TypeScript + Tailwind
│   ├── backend/                 # FastAPI + adapters + tests
│   └── DOCS.md                  # shown inside Home Assistant
├── docs/
└── .github/workflows/           # lint, typecheck, tests, Docker build
```

The Dockerfile references nothing outside `bobi_control_center/`, which is what
lets the Supervisor build it.

---

## Security

- `SUPERVISOR_TOKEN` is read from the environment, used only in an
  `Authorization` header, and never serialised, logged or sent to the browser.
- No long-lived access token is created, and none is ever requested from you.
- The real adapter can call **only** the nine bridge services — anything else is
  refused before a request is made.
- Response bodies are logged only when `debug_http` is explicitly enabled.
- Users show WhatsApp *connection status* only: no phone numbers, no LIDs.
- Mock fixtures contain invented data only; a test fails the build if anything
  resembling a phone number appears.

---

## Phase 3

Writes. The UI already renders every write control disabled and labelled
*"עריכה תהיה זמינה בשלב הבא"*, so enabling them is a matter of adding write
methods to the adapter interface and wiring the existing controls — the shape
of the product does not change.

## License

MIT — see [LICENSE](LICENSE).
