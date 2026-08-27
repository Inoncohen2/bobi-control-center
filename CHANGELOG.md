# Changelog

The version here is the one in `bobi_control_center/config.yaml`, which is what
Home Assistant compares to decide whether an update exists. Every change that
reaches the app image gets a new version and an entry below.

## 3.5.1

Five screens were telling people not to look for controls that were already
there.

The devices screen carried a banner reading *"שליטה במכשירים מהממשק תהיה זמינה
בשלב הבא. כרגע זו תצוגה בלבד"* — written in Phase 2, true then — while a live
`ManagedSection`, wired to the contract and to `bobi_cc_device_commit`, sat at
the very bottom of the same page, below the whole nineteen-card catalogue. A
person opened the page, read the first thing on it, and stopped. So did I:
every claim I made about devices being controllable was true of the API and
false of the screen.

Rules, the Shabbat clock, users and settings had the same banner over the same
working section. The dashboard's feature card said editing was coming in a
later phase; those toggles have been writable since 2.2.0.

- **The banners are gone.** The managed section states its own status from the
  contract — *"קריאה בלבד"* when a family has no commit bridge, *"ניהול עדיין
  לא הופעל"* when the master switch is off — and a sentence hard-coded beside
  it can only contradict it. That is the failure this architecture exists to
  prevent, and it had been sitting in the five oldest screens the whole time.
- **On the devices screen the controls come first**, above the catalogue.
- **An inert catalogue row now says where the working control is** rather than
  promising a phase that has arrived.
- Two architecture tests hold the line: no screen with a `ManagedSection` may
  carry a screen-wide read-only banner, and the shared label must point at a
  control rather than at a future.

One "next stage" survives, on the Shabbat drafts card, because it is still
true: nothing bridges draft management.

## 3.5.0

The five bridges that were missing — and the two that turned out to be
impossible, said so rather than faked.

3.4.1 left five families with a snapshot and no commit. Four of them now have
one. The fifth does not, and the reason is worth more than the bridge would
have been.

### What Home Assistant gained

- **`bobi_cc_system_commit`** runs the two safe checks and nothing else.
  Restart, Supervisor update, integration or device deletion, backup restore
  and anything shell-shaped are refused **by name, before dispatch**, so a
  contract that started advertising one tomorrow would meet the same answer.
- **`bobi_cc_script_commit`** runs one of two allow-listed Bobi scripts. The
  canonical id maps to an entity here and nowhere else, so the web cannot name
  a script to execute.
- **`bobi_cc_rule_commit`** switches a smart rule on or off, or deletes it,
  resolving the uid against the rules it can actually see.
- **`bobi_cc_calendar_commit`** creates an event.
- **`bobi_cc_scripts_snapshot`** now publishes its two entries as `action`
  items so a screen can draw a button for them.

### What is refused, and why

- **Scenes.** There are none configured in this house. A commit bridge would
  have been an allow-list with nothing in it, so it was not written.
- **Changing or deleting a calendar event.** Home Assistant publishes no
  service for either — that path is websocket-only and a bridge script cannot
  reach it — and neither mapped calendar advertises UPDATE in the first place.
  The snapshot had been advertising `edit`, `move` and `delete` on every event
  regardless: a fail-open, announcing three operations no bridge could carry
  out. Events are readings now, and say why.
- **Creating and rewriting a rule.** A rule is a compound object and the
  contract carries one value per item. Switching and deleting are offered;
  inventing a form for the rest is not.

Every operation the contract names has a bridge behind it, and every family
with an empty list has a snapshot and no commit. That is now checked by a test
that walks the whole contract rather than one family at a time.

### `action` — a kind that holds no value

The system bridge sends `kind: "action"` with no value, and every other kind in
the contract assumes an item *is* a value: a missing one means the bridge could
not read the item, which makes it unwritable. So both safe checks arrived
marked controllable and rendered as readings — the same shape of fault as the
vocabulary mismatch, one layer down.

`action` is now a kind of its own, exempt from the value requirement and from
nothing else. Forcing these into a toggle would have been worse than the bug: a
toggle says it can be switched back, and a self-check cannot.

### The calendar screen

Adding an event is the one calendar write that exists, so the screen now has a
form for it — reading the calendars it may write to from the contract's own
targets rather than a list kept here. Nothing is sent while typing; the button
opens the same preview → confirm → commit dialog as every other change, and the
backend refuses a payload missing a title or a time before a preview exists.

Nothing is relaxed. The master switch is still read-only and still off, and no
write has been run against hardware.

## 3.4.1

Commits now carry their target under the name the bridge actually reads.

Reconnecting to the live house and comparing every `script.bobi_cc_*_commit`
against what this side sends turned the settings bug found in 3.4.0 into a
pattern: this application names the target field per family — `user_id`,
`profile_id`, `helper_id`, `automation_id` — and five of the six bridges call
it `resource_id`. The field each script read arrived undefined, so **users, the
Shabbat clock, helpers and automations would have refused every write** as
`invalid_commit_request`. Nothing would have been written, and from this side
it would have looked exactly like a bridge declining the change.

The target is now sent twice: under the family's own field name and as
`resource_id`. One value, two names, and a script ignores the one it does not
use — which is also the only fix that suits a bridge written before this field
was named and one written after. The published bridge contract says so, so the
next bridge author reads it rather than discovers it.

## 3.4.0

The two sides now speak the same language, and the house is controllable from
the web.

Connecting to the live Home Assistant showed three families — users, the
Shabbat clock and devices — arriving fully described, marked controllable, and
entirely read-only. Nothing raised. Each verb the bridge declared was a verb
this side did not know, and a verb only one side knows is dropped in silence by
the closed-set filter: the contract announced the operation, the app quietly
did not offer it, and neither reported anything wrong.

Home Assistant's model was the right one. A family is a list of items each
holding a value, `set` sets it, and a device names one verb per capability.
The granular verbs were this application's idea.

### What changed here

- **`set` is accepted wherever the live bridge declares it** — users, the
  Shabbat clock, settings — beside the granular names, which still work where a
  bridge offers them.
- **Sixteen device capability verbs**, matching what the house publishes:
  `power`, `temperature`, `hvac_mode`, `fan_mode`, `swing_mode`, `preset_mode`,
  `brightness`, `color_temp`, `intensity`, `scent`, `timer`, `fan_speed`,
  `start`, `pause`, `stop`, `return_to_base` and `locate`.
- **Every refusal that used to key off a verb now reads the payload.** The
  last-admin guard catches a `set` that switches off the only administrator or
  demotes them; the phone door opens for a `phone` field under `set` as it did
  under `set_phone`, and the change is rated sensitive for what it carries
  rather than for what it is called.
- **`primary_operation`** — one item now carries several verbs, and nothing in
  the payload says which one sets the value it reports. An air conditioner
  reports a temperature and accepts `power` first, so a screen taking the first
  name in the list would have sent `power` when someone edited a temperature:
  the wrong change, previewed honestly, confirmed by a person who read a
  correct-looking dialog. The backend decides it once; no component guesses.
- **A switch verb is no longer checked against the item's own limits.**
  `power: true` measured against a °C range produced "the value must be a
  number" — the check being wrong about the request rather than the request
  being wrong. It is still checked against what a switch can hold.
- **A bare list of choices is understood.** `hvac_modes` and `fan_modes` are
  plain string lists in Home Assistant, and they were being dropped whole: a
  choice control with nothing to choose from.
- **A family declaring no operations is readable, not missing.** An empty
  `operations` list is the documented way to publish a snapshot bridge before
  its commit bridge exists, and it was reporting the family as unavailable —
  the difference between a screen full of values and a screen saying there is
  nothing here.

### What changed in Home Assistant

- **`bobi_cc_devices`** published `kind` as the Home Assistant domain —
  `light`, `climate` — where the contract asks for an editor kind, so every
  device fell through to read-only regardless of vocabulary. It now publishes
  one canonical item per controllable value, the way the Shabbat bridge already
  did: sixteen devices become thirty-one items, each with the limits and
  choices Home Assistant actually holds.
- **`bobi_cc_device_commit`** is new, and reaches only the sixteen canonical
  devices, only through a capability the device has, with the kill switch, the
  preview token, the expected-state match and read-after-write all enforced on
  that side too.
- **`bobi_cc_manage_contract`** declares the fourteen device verbs the commit
  bridge implements, and names `helpers`, `automations`, `scripts` and `scenes`
  — read-only, honestly, because their write path is not verified.
- **`bobi_cc_settings_commit`** read `resource_id` while this application sends
  `setting_id`, so every settings write would have been refused as
  `invalid_commit_request`. It accepts both now.

An item whose current value Home Assistant cannot read is published with a
reason and no control rather than with a guess — a light's brightness while it
is off, a mode the integration does not report. A preview binds to what the
bridge reports, so a guessed value would be a guess that got confirmed.

Nothing is relaxed. The master switch is still read-only and still off; the
preview token, the single-use expiry, the payload and observed-state binding,
the explicit confirmation, read-after-write and the closed service allow-list
all stand.

## 3.1.1

External authentication now remains fail-closed when Cloudflared rewrites the
origin `Host` header to the add-on's internal Docker hostname. Bobi recognizes
the paired headers that Cloudflare creates at its edge, while its unpublished
container port keeps that trust boundary inside Home Assistant's app network.

## 3.1.0

Bobi can now run at a dedicated HTTPS hostname through the existing Cloudflare
Tunnel while Home Assistant Ingress keeps working in parallel.

- Requests on the configured external hostname require a salted-scrypt
  password and a 12-hour, server-side session. The browser receives only a
  `Secure`, `HttpOnly`, `SameSite=Strict` session cookie.
- Login attempts are throttled, state-changing requests require the exact
  HTTPS origin, and an incomplete external configuration fails closed.
- Ingress continues to use Home Assistant authentication and needs no second
  login. There is still no published host port.
- The frontend includes a Hebrew login screen and logout control. Home
  Assistant credentials, raw entity IDs and raw services remain backend-only.

## 3.0.1

Support the complete Home Assistant management contract `3c` without filtering
the seven families added after tasks and features.

## 3.0.0

The complete management release — settings, users, the Shabbat clock, rules, the
calendar, devices and the system, all reachable from the web.

Home Assistant has not shipped those seven bridges yet, so the honest way to
build this was to **let the bridge describe them**. It names the items, says
which are operable, and supplies the limits; this side renders that description
in Hebrew and refuses whatever does not fit. Hard-coding seven contracts that do
not exist would have meant writing screens that assert what Bobi does, and
inventing the answer to a question only Home Assistant can answer.

The practical consequence: **every family works the day its bridge lands**, and
until then it says so. A family the contract does not name shows as unavailable
with the reason Home Assistant gave, never as a broken screen and never as a
control that silently does nothing.

### What is new

- **Eight API families**, each with a snapshot, a preview and a commit:
  settings, users, Shabbat, rules, the calendar, devices and the system, beside
  the tasks and features 2.2.1 already managed.
- **One editor for all of them.** `kind` picks the control, `constraints`
  bounds it, `options` fills it, `controllable` decides whether there is a
  control at all. A row the bridge did not mark operable is a reading.
- **Screens**: smart notifications, the calendar, cameras, the system, and a
  persistent activity log. Devices, the Shabbat clock, rules and users keep the
  read-only screens they already had and gain management underneath.
- **A trail that survives a restart.** Written to the app's `/data`, bounded and
  rotated, redacted on the way in — a number that never reaches the file cannot
  leak from it later.

### What it refuses

Four rules hold whatever the bridge says, because a bridge that has not shipped
cannot be relied on to catch them:

- A household never runs out of enabled administrators.
- A phone number is shown masked, and reaches the trail redacted. Setting one is
  the single field allowed past the private-field filter, and it is still never
  displayed or recorded whole.
- Saving a Shabbat profile changes the schedule and no device, and the dialog
  says so before anyone presses save.
- A control the bridge did not advertise is refused rather than passed along.

Restarting Home Assistant, updating the Supervisor, deleting an integration or a
device, and restoring a backup are refused for being what they are — checked
before the question of whether such an action exists is even asked, so a bridge
that started offering one tomorrow would meet the same answer.

Nothing from 2.2.1 is relaxed. The preview token, the five-minute single-use
expiry, the payload binding, the observed-state binding, the explicit
confirmation, read-after-write and Home Assistant's master switch all stand, and
the switch is still read-only: no endpoint, setting or screen can turn it on.

### Notes for the Home Assistant side

The seven new commit services receive the Phase 3A shape extended rather than
replaced — flat fields, the target under the name its bridge expects, one
`expected_*` per value the preview observed, plus `preview_token`, `confirmed`
and `request_id`. A bridge author who has read `bobi_cc_task_update_commit` can
write the next one without a new document.

Smart notifications and cameras have no bridge of their own by design: the first
are settings the contract marks with a `notification_class`, the second are
devices whose class is `camera`. Neither invents a service.

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
