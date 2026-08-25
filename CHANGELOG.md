# Changelog

The version here is the one in `bobi_control_center/config.yaml`, which is what
Home Assistant compares to decide whether an update exists. Every change that
reaches the app image gets a new version and an entry below.

## 2.1.0

Phase 3A: the management path, prepared and **fail-closed**.

Every change follows one flow — edit → preview → explicit confirmation →
commit → read-after-write verification → result — and it is enforced in the
service layer, so no route, adapter or screen can skip a step.

- **New endpoints.** `GET /api/bobi/manage/status`,
  `POST /api/bobi/manage/{tasks|features}/preview`,
  `POST /api/bobi/manage/{tasks|features}/commit`, `GET /api/bobi/manage/audit`.
- **Fail closed.** Management is discovered from a Home Assistant write bridge,
  never from configuration. No adapter declares one today, so every management
  request is refused with *"ניהול עדיין לא הופעל ב-Home Assistant"*. There is no
  fallback that calls a service anyway, and no environment variable that could
  enable one.
- **Tasks UI** for add, rename, complete, reopen and delete — each opening a
  Hebrew preview dialog rather than acting. Deleting warns and requires the
  confirmation word to be typed.
- **Feature toggles** show current and proposed state through the same dialog.
- **Audit** entries for every preview and commit, including refusals, carrying
  no phone number, LID or credential.
- The result is reported honestly as one of *השינוי בוצע ואומת*,
  *השינוי בוצע אך לא הצלחנו לאמת* or *השינוי לא בוצע*; nothing is shown as
  saved before the read-back agrees.

`writes_enabled` stays `false`, the bridge allow-list still holds only the nine
read/probe services, and no device control, Shabbat saving, rule creation,
automation editing, calendar write or permission change is exposed.

## 2.0.2

Two things the live 2.0.1 install still got wrong.

- **Overall health** — `status.ok` came back `null` while the bridge's own
  `healthy` flag sat in `details` as the string `"True"`. A canonical
  `health {status, ok, reason}` now resolves it from authoritative information
  only: the bridge's own statement first, otherwise the component states, where
  only an explicit failure counts. A component the bridge could not resolve
  leaves health `unknown` rather than dragging it to `false`, and `unknown` is
  rendered as unknown — never as a fault.
- **Shabbat AC temperatures** — the list was empty because the bridge keeps the
  temperatures inside each profile, not at the top level. They are collected
  from wherever they appear and de-duplicated by device. `temperature` is now
  numeric, with the bridge's own text preserved beside it.

`profile.active`, `profile.time` and `profile.offset_minutes` stay nullable: the
bridge has no authoritative value for all of them yet, and a guess is worse than
a null.

## 2.0.1

Normalization of real bridge responses, after the second live test.

- **Status** — WhatsApp, the AI fallback and its fast paths, the household,
  feature toggles and configuration health are first-class fields instead of
  text rows in `details`. The dashboard's health row is derived from them, since
  the real bridge sends no `components` array. Each section is accepted nested,
  bare or flat-prefixed.
- **Device limits** — the bridge's domain-specific constraints are kept in full
  (climate temperature range and mode lists, light colour temperature and
  brightness, scent intensity, slots and timer) rather than collapsed into
  `min`/`max`/`step`, which stay as a generic view.
- **Shabbat** — the pre-Shabbat offset is read from
  `upcoming.pre_offset_minutes`, profile device `tokens` are resolved through
  `device_labels` into `{id, label}` pairs, and `ac_temperatures` became a list
  so each temperature stays tied to its air conditioner.
- `/api/bobi/connection` reports `app_version`, so the UI no longer hard-codes it.

## 2.0.0

First release as a Home Assistant App: Ingress on port 8099, no external port,
`SUPERVISOR_TOKEN` used server-side only. Ten screens on the nine
`script.bobi_cc_*` bridge services, read-only throughout.

Shipped in two pushes — `8cc319a` normalized the real bridge responses and fixed
the diagnostics 502 **without bumping this version**, so the Supervisor never
offered it as an update. That mistake is what the version guards now prevent.
