# Changelog

The version here is the one in `bobi_control_center/config.yaml`, which is what
Home Assistant compares to decide whether an update exists. Every change that
reaches the app image gets a new version and an entry below.

## 2.2.1

Commits now carry their preview token, which is what Home Assistant was asking
for all along.

2.2.0 was correct on both sides and wired wrongly between them. The preview
store held everything a commit needed, the bridge built a faithful service call,
and nothing passed the token from one to the other — `apply()` had no parameter
for it. Live testing with the master switch briefly on showed the script
receiving `user_id`, `summary`, `due_date`, `confirmed` and `request_id`, an
empty `token`, and answering `invalid_commit_request`. Nothing was written, on
either side of the failure, which is the flow behaving as designed.

- **The token is minted with the preview, never at commit time.** A value
  created when the commit arrives would prove nothing about a preview having
  happened, and proving exactly that is its whole job.
- **It is not the `preview_id`.** The id goes to the browser; the token stays in
  this process and is spoken only to Home Assistant. Someone who read the id out
  of a network tab still cannot drive `script.bobi_cc_*` themselves.
- **All three write services carry it** — `task_add_commit`,
  `task_update_commit` and `feature_commit` — alongside the `expected_*`
  evidence, never instead of it.
- **A tokenless commit is refused before a request is built**, and the test
  double now refuses one the way the live bridge does, so the gap cannot reopen
  unnoticed.
- `debug_http` logs the token's length rather than the token: a five-minute
  secret should not outlive the log file.
- Home Assistant's side is untouched. Its token requirement, whitelists,
  duplicate checks, `expected_*` comparison and read-after-write all stand, and
  the master switch remains read-only and off.

Feature state comes from the management contract, which now reports `enabled`
for all four targets. No raw `input_boolean` is read, then or now: a feature
whose state the contract does not report is shown but stays inoperable.

## 2.2.0

Phase 3A wired to Home Assistant's real write bridge.

Five `script.bobi_cc_*` services and nothing else: `manage_contract` and
`task_snapshot` (reads), `task_add_commit`, `task_update_commit` and
`feature_commit` (writes). `todo.*` and `input_boolean.*` are never called —
the allow-list holds fourteen `bobi_cc_*` names, pinned by a test.

- **The master switch is read, never set.** `writes_enabled` comes from the
  contract and is off today, so **previews work and commits are refused** with
  *"ניהול עדיין לא הופעל ב-Home Assistant"* — presented as a disabled feature,
  not a connection failure. No endpoint, setting or UI control can turn it on.
- **Two independent layers.** This application holds the preview token —
  server-side, random, five-minute TTL, single-use, bound to the operation, the
  target, the requested values *and the state observed at preview time*. Home
  Assistant re-checks its own whitelists, duplicates, `expected_summary` /
  `expected_status` / `expected_state` and read-after-write. Neither is relaxed
  because of the other.
- **Optimistic locking is honoured.** A bridge answering `stale_preview` means
  nothing was mutated, and the result says *השינוי לא בוצע*. `already_in_state`
  is reported as a verified success that needed no change.
- **The commit carries no payload.** Everything sent to Home Assistant comes
  from the stored preview, so a client cannot alter what it confirmed; an
  echoed `operation` or `resource_id` that disagrees is rejected outright.
- Tasks are driven by the management snapshot (open and completed, with the
  bridge's own `uid`); feature toggles by the contract's four feature ids. The
  AI master toggle and Fast Paths stay read-only — they are outside this
  contract.
- A feature whose current state the bridge does not report is shown but not
  operable: `expected_state` must be observed, never guessed.

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
