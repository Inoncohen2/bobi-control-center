# Working on this repository

## The release rule — read this first

**Every change that should reach Home Assistant must bump `version` in
`bobi_control_center/config.yaml`.**

The Supervisor decides whether an update exists by comparing that one string.
It does not look at commits, tags or image digests. A change pushed without a
bump is invisible: the store shows no update, the running app keeps the old
code, and the next real test reports the bug you thought you had fixed. This
has already happened once — `8cc319a` shipped a full normalization rewrite while
the manifest still said `2.0.0`.

So, on any change to what ends up inside the image:

1. Bump `bobi_control_center/config.yaml` — patch for a fix (`2.0.1` → `2.0.2`),
   minor for a feature. Never reuse or lower a version.
2. Bump the two copies that must match it:
   `bobi_control_center/backend/app/version.py` and the root `package.json`.
3. Add a `CHANGELOG.md` entry.
4. Report the new version alongside the commit SHA.

What counts as reaching Home Assistant: `config.yaml`, `Dockerfile`, `run.sh`,
`backend/app/**`, `backend/requirements.txt`, `frontend/**`. Documentation,
tests and CI do not — they never enter the image, so they need no bump.

Two guards enforce this, but do not rely on them to remember for you:

- `tests/test_architecture.py::test_one_version_number_everywhere` fails if the
  three copies disagree.
- The CI job **App version bumped** fails if the image changed and the manifest
  version did not.

## The other rules that outlive a session

**Writes fail closed, and the switch is Home Assistant's.** `ALLOWED_SERVICES`
holds exactly fourteen `bobi_cc_*` names — nine reads, two management reads,
three management writes. A raw `todo.*` or `input_boolean.*` is never called and
must never be added. `writes_enabled` is *read* from the contract and is off
today: previews run, commits answer *"ניהול עדיין לא הופעל ב-Home Assistant"*,
and no endpoint, setting or control anywhere may set it. `would_execute` stays
hard-coded `false`, and the only non-GET routes are the probe and the managed
preview/commit pair.

**Every change is previewed, confirmed, committed and verified.** In that order,
enforced in `services/manage.py` so no route or screen can skip a step. A
preview never writes; it reads the current state and **binds the token to it**,
because Home Assistant compares that state again before acting and answers
`stale_preview` if it moved. A commit needs a single-use, unexpired preview id
plus an explicit confirmation — and, when destructive, the confirmation word
typed — and carries no payload of its own. The result is *בוצע ואומת*,
*בוצע אך לא הצלחנו לאמת* or *לא בוצע*, and the UI shows no saved state before
the read-back agrees.

**Two layers, neither relaxed for the other.** This app owns the token, expiry,
single use, payload binding and confirmation; Home Assistant owns the master
switch, whitelists, duplicate checks, expected-state comparison and
read-after-write. Phase 3A covers tasks and feature toggles only — device
control, Shabbat, rules, automations, calendar, permissions, the AI master
toggle and Fast Paths each need their own contract first.

**Normalize in `app/services/normalize.py`, never in React.** It is the only
module that may know a bridge field name. The frontend receives one canonical
schema and contains no mapping logic. When the bridge sends something new,
extend the canonical model — do not let a raw key through.

**Nothing is dropped and nothing is duplicated.** A response carries exactly one
collection per resource; unmapped fields land in a per-item `extra` map. A value
the contract cannot represent is kept in `extra` rather than silently reported
as empty.

**Never touch Home Assistant.** Do not modify Bobi's scripts, helpers or
entities, and do not connect to the real install — it is tested separately.

**Secrets stay in the backend.** `SUPERVISOR_TOKEN` is read from the environment,
used only in an outgoing `Authorization` header, and never logged, serialised or
sent to the browser. No long-lived token is ever created. No phone number, LID
or chat id reaches a response.

**Keep polling modest.** Every fetch is a Home Assistant service call: dashboard
and devices 20s, diagnostics 60s, everything else on entry, and never while the
tab is hidden.

## Before pushing

`npm run check` (ruff, eslint, tsc, pytest, vitest). For a change to the image,
also `npm run docker:build` and hit `/health` on the container.
