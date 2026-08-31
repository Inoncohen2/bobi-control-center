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

1. Bump `bobi_control_center/config.yaml` — patch for a fix, minor for a feature.
   Never reuse or lower a version.
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
is derived from `SPECS` and the explicit Phase-3A bridges; never document a
hand-count as an architectural fact because the set changes whenever a family
gains a bridge. Anything outside the derived set raises before a request is
made. A raw `todo.*` or `input_boolean.*` is never called and must never be
added: the bridge scripts own those entities and this app asks by operation
name instead.

`writes_enabled` is *read* from the contract and never written. On the current
house it is enabled, so commits may reach Home Assistant. That is the
household's switch, not ours: no endpoint, setting or control anywhere may set
it, and when it is off the same commits answer *"ניהול עדיין לא הופעל
ב-Home Assistant"* with nothing written. Do not confuse it with the adapter's
`unrestricted_writes`, which means "this adapter may write without a bridge"
and is `False` for every implementation. `would_execute` stays hard-coded
`false`, and the only state-changing HTTP routes are the managed preview/commit
flow and the probe remains non-executing.

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

**The live contract decides what exists, and it is not a wish list.** An
operation is advertised only once its `script.bobi_cc_*_commit` implements it
and the path has been run against the real house and returned `executed` and
`verified`. What sits in `not_supported` is not automatically a backlog: Home
Assistant exposes no script service for updating/deleting calendar events and no
entity-rename service. Check the live services before promising one of those.

**A captured live contract is dated evidence, not current truth forever.**
`tests/test_live_contract_3c.py` and `tests/test_double_matches_the_house.py`
exist to stop vocabulary drift, but every fixture must say when it was captured.
Whenever a live bridge changes, refresh the operation lists and the explanatory
comments in the same change. Never infer today's `writes_enabled`, script count,
or supported operation from an old fixture.

**Normalize in `app/services/normalize.py` and
`app/services/resource_normalize.py`, never in React.** They are the layers that
may know bridge field names. The frontend receives one canonical schema and
contains no raw Home Assistant mapping logic. When the bridge sends something
new, extend the canonical model — do not let a raw key through.

**Nothing is dropped and nothing is duplicated.** A response carries exactly one
collection per resource; unmapped safe fields land in the canonical detail map.
A value the contract cannot represent is kept as safe detail rather than
silently reported as empty.

**Voucher codes and voucher images are secrets.** A normal voucher snapshot must
never include the redeemable code or a permanent/public image URL. Voucher
media lives in the private `bobi-vouchers` bucket. A picture is opened through a
short-lived signed URL requested for that voucher only; a redeemable code, when
a UI eventually exposes it, must come from a separate deliberate read and must
not be preloaded into the wallet snapshot. Never make the bucket public to make
the screen easier to build.

**The app never reaches around Home Assistant.** Nothing in `backend/` or
`frontend/` may talk directly to Supabase, WAHA, a device, or a Home Assistant
entity. The Control Center calls only `bobi_cc_*` bridges. Editing a bridge
script is separate Home Assistant work, done deliberately through the authorized
HA tooling and finished only after a real read or safe round-trip verifies it.
Do not restart, update, delete, restore, or start a physical device merely to
prove a UI path. Leave the house as you found it.

**The double mirrors the live bridge, not the app's ambitions.**
`app/mock/management.py` is what every test sees, so a double that advertises
more than Home Assistant does means the "this operation does not exist" paths
are never exercised. The live fixtures must therefore stay narrower than or
equal to what the house really publishes.

**Secrets stay in the backend.** `SUPERVISOR_TOKEN` is read from the environment,
used only in an outgoing `Authorization` header, and never logged, serialised or
sent to the browser. No long-lived Home Assistant token is created. No phone
number, LID, chat id, voucher code, private media URL, or storage credential
belongs in a general API response or log.

**Keep polling modest.** Every fetch is a Home Assistant service call: dashboard
and devices 20s, diagnostics 60s, everything else on entry, and never while the
tab is hidden.

## Before pushing

`npm run check` (ruff, eslint, tsc, pytest, vitest). For a change to the image,
also `npm run docker:build` and hit `/health` on the container. If a bridge
changed, run the relevant safe path against the real house and refresh the dated
live fixture after it verifies.
