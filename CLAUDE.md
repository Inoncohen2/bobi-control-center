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
holds 33 `bobi_cc_*` names — nine reads, thirteen management reads, fourteen
management writes — and it is *derived* from `SPECS` in `services/resources.py`
rather than hand-listed, so a family gains a service by gaining a spec. Anything
outside the set raises before a request is made. A raw `todo.*` or
`input_boolean.*` is never called and must never be added: the bridge scripts own
those entities and this app asks by operation name instead.

`writes_enabled` is *read* from the contract and never written. It is **on**
today — the live 3c contract returns `true`, so commits reach Home Assistant.
That is the household's switch, not ours: no endpoint, setting or control
anywhere may set it, and when it is off the same commits answer
*"ניהול עדיין לא הופעל ב-Home Assistant"* with nothing written. Do not confuse it
with the adapter's `unrestricted_writes`, which is a different claim — "this
adapter may write without a bridge" — and is `False` for every implementation.
`would_execute` stays hard-coded `false`, and the only non-GET routes are the
probe and the managed preview/commit pair.

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
read-after-write.

**The contract decides what exists, and it is not a wish list.** Contract 3c
covers eleven families. An operation is named there only once a
`script.bobi_cc_*_commit` implements it *and* that commit has been run against
the real house and come back `executed` and `verified` — which is why the
contract carries a Hebrew `detail` line recording that run. What sits in
`not_supported` is mostly not a gap waiting to be filled: Home Assistant exposes
exactly two calendar services, so deleting or updating an event is a WebSocket
command a script cannot reach, and there is no rename service anywhere in Home
Assistant. Check before you promise one of those again.

**Normalize in `app/services/normalize.py`, never in React.** It is the only
module that may know a bridge field name. The frontend receives one canonical
schema and contains no mapping logic. When the bridge sends something new,
extend the canonical model — do not let a raw key through.

**Nothing is dropped and nothing is duplicated.** A response carries exactly one
collection per resource; unmapped fields land in a per-item `extra` map. A value
the contract cannot represent is kept in `extra` rather than silently reported
as empty.

**The app never touches Home Assistant; a bridge change is separate work.**
Nothing in `backend/` or `frontend/` may reach past the `bobi_cc_*` scripts, and
the test suite never connects to the real install — it runs against the double in
`app/mock/`. Editing a `bobi_cc_*` bridge script is a different job, done
deliberately through the Home Assistant MCP with the household's say-so, and it
is finished only when the new operation has been run against the real house and
verified. Everything else in that install is off limits: Bobi's own engine
scripts, helpers and entities, and anything that restarts, updates, deletes or
restores. Leave the house as you found it — a device switched on to prove a path
works gets switched back.

**The double mirrors the live bridge, not the app's ambitions.**
`app/mock/management.py` is what every test sees, so a double that advertises
more than Home Assistant does means the "this operation does not exist" paths are
never exercised. Two files hold the house's own words for that reason, and when
the bridge changes they change with it: `tests/test_live_contract_3c.py` holds a
captured contract payload and checks the *normalizer* against it, and
`tests/test_double_matches_the_house.py` configures the double with the live
per-family operation lists and checks the *screens*.

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
