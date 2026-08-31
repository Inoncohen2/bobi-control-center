<div dir="rtl">

# 🤖 בובי — מרכז ניהול

</div>

**Bobi Control Center** is a Hebrew-first, RTL, mobile-first Home Assistant App
for seeing and managing the parts of Bobi that Home Assistant explicitly
publishes through `script.bobi_cc_*` bridge services.

The central rule is simple: **Home Assistant stays the authority.** The web app
never calls a device, `todo.*`, WAHA, Supabase or a raw Home Assistant service
directly. It asks Bobi's bridge for canonical data and, for a write, follows
preview → confirmation → commit → Home Assistant validation → read-after-write.

## Safety model

Writes fail closed at several independent layers:

- the live Home Assistant contract decides which resource families and
  operations exist;
- the backend accepts only the closed set declared in `services/resources.py`;
- every change receives a single-use preview token bound to the state that was
  observed;
- destructive and sensitive changes require stronger confirmation;
- Home Assistant re-checks the master write switch, target allowlists and the
  expected state immediately before acting;
- success is reported only after Home Assistant reads the result back.

`writes_enabled` belongs to Home Assistant. The Control Center can read it but
contains no setting or endpoint that can change it.

## Install

1. Add this repository to Home Assistant's App/Add-on Store:

   ```text
   https://github.com/Inoncohen2/bobi-control-center
   ```

2. Install **Bobi Control Center** and start it.
3. Open its Web UI. Optionally enable **Show in sidebar**.

No Home Assistant token is pasted into the app. Because the manifest declares
`homeassistant_api: true`, Supervisor provides `SUPERVISOR_TOKEN` to the backend
process. It is used server-side only and never reaches the browser.

The released image is pulled from GHCR for `aarch64` and `amd64`; Home Assistant
does not rebuild the frontend on the Raspberry Pi for each update.

## What is on the site

The navigation contains the full current surface, not just the first features
that were implemented:

| Screen | Source | Purpose |
| --- | --- | --- |
| ראשי | status + diagnostics | Bobi, WhatsApp, AI, configuration and issues |
| משימות | task bridge | open/completed household tasks |
| רשימות | lists bridge | shopping and other family lists |
| מכשירים | device bridge | canonical devices and safe controls |
| שוברים | voucher bridge | voucher wallet |
| מצלמות | camera bridge | camera state/snapshot surface |
| שעון שבת | Shabbat bridge | profiles, timing, device membership, temperatures |
| אוטומציות | Bobi rules bridge | Bobi's smart rules |
| יומן | calendar bridge | calendars and supported writes |
| עזרים | helpers bridge | curated Home Assistant helpers |
| אוטומציות HA | automations bridge | Home Assistant automations |
| סקריפטים | scripts bridge | curated Home Assistant scripts |
| סצנות | scenes bridge | scenes when the house publishes any |
| התראות חכמות | notification/status bridge | Bobi notification configuration |
| משתמשים | user bridge | household profiles and permissions |
| AI והגדרות | settings bridge | Bobi configuration |
| מערכת | system bridge | explicitly safe system checks |
| פעילות | activity/audit | recent activity without private identifiers |
| יכולות | capability registry | what Bobi understands and examples |
| בדיקות | probe | parse a command without executing it |
| תקלות | diagnostics | actionable health issues |
| חוזה הגשרים | live contract + build spec | implemented/missing bridge services |

The mobile bottom bar intentionally stays small; less-frequent screens are under
**עוד** rather than shrinking every tap target.

## A bridge can be read-only while it is being built

The application does not guess that an operation exists. A family can be
published with a snapshot bridge and an empty operations list. In that state the
screen shows all values and clearly says **קריאה בלבד**. Once Home Assistant
publishes the commit operation, the same screen exposes the corresponding
control automatically.

The developer screen **חוזה הגשרים** compares the build specification with the
live Home Assistant contract, so a missing snapshot/commit bridge is visible as
a missing service rather than a mysterious empty page.

## Lists and vouchers

Lists are a distinct family from the task screen. The Home Assistant bridge
owns the allowlist of household lists because the installation also contains
internal `todo` entities that must never be exposed as family data.

A voucher enters Bobi from WhatsApp/image understanding; the Control Center does
not invent a second voucher-creation form. Voucher media belongs in the private
Supabase `bobi-vouchers` bucket. The wallet snapshot must never preload a
redeemable voucher code or a permanent/public image URL. Images are opened only
with short-lived signed URLs, and a future code-reveal control must use a
separate deliberate read for that single voucher.

## Test Center

The Test Center runs Bobi's real parser with execution disabled and renders the
pipeline:

```text
טקסט → הבנה → יעד → תזמון → Skill → בדיקת בטיחות
```

It is a parser/probe surface, not a hidden execution endpoint.

## Architecture

```text
React (HashRouter)
        ↓
FastAPI
        ↓
Supervisor Core API
        ↓
script.bobi_cc_*
        ↓
Bobi / Home Assistant
```

The browser never talks to Supervisor. The real adapter accepts only the
allowed bridge services; the mock adapter returns the same canonical shapes for
tests and local development.

Normalization belongs in the backend (`normalize.py` and
`resource_normalize.py`), not React. Raw Home Assistant vocabulary, entity ids,
phone numbers, chat ids and secrets must not leak into general frontend models.

## External HTTPS access

Ingress uses Home Assistant authentication. An optional dedicated external
hostname can be configured with a salted-scrypt password verifier and a role.
External sessions are server-side, short-lived, `Secure`, `HttpOnly` and
`SameSite=Strict`. Without the hostname and verifier, external login fails
closed.

## Development

Requires Node 20+ and Python 3.11+.

```bash
git clone https://github.com/Inoncohen2/bobi-control-center.git
cd bobi-control-center
npm run setup
npm install
npm run dev
```

Useful commands:

| Command | Purpose |
| --- | --- |
| `npm run dev` | backend + frontend with reload |
| `npm run build` | build the frontend |
| `npm test` | backend pytest + frontend Vitest |
| `npm run lint` | ruff + eslint |
| `npm run typecheck` | TypeScript type check |
| `npm run check` | lint + typecheck + all tests |
| `npm run docker:build` | build the Home Assistant app image locally |

## Releasing

Home Assistant detects an update from `version` in
`bobi_control_center/config.yaml`. Every image change therefore bumps that
version and keeps it equal to `backend/app/version.py` and root `package.json`.
CI verifies the version contract and the published multi-architecture image.

## Repository layout

```text
bobi-control-center/
├── repository.yaml
├── bobi_control_center/
│   ├── config.yaml
│   ├── Dockerfile
│   ├── run.sh
│   ├── backend/
│   └── frontend/
├── docs/
└── .github/workflows/
```

## Security invariants

- `SUPERVISOR_TOKEN` stays server-side.
- No raw Home Assistant service or entity write is exposed to the browser.
- No direct Control Center → Supabase/WAHA/device bypass is allowed.
- A missing bridge means unavailable/read-only, never a guessed fallback.
- Preview tokens are single-use and state-bound.
- Private identifiers and credentials are removed before API responses/logs.
- Voucher codes are not general snapshot data; voucher images stay private and
  use expiring signed access.
- The test double must mirror the live bridge, including operations the house
  deliberately does **not** support.

See `CLAUDE.md` for the rules that must survive future development and
`docs/` for the detailed API/bridge documentation.

## License

MIT — see `LICENSE`.
