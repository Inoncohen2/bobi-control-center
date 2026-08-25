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

**Phase 2 is read-only.** No write method exists on `HomeAssistantAdapter`, the
real adapter's `ALLOWED_SERVICES` holds exactly the nine `script.bobi_cc_*`
services, and `POST /api/bobi/probe` is the only non-GET route. `writes_enabled`
and `would_execute` are forced `false` in code, never read from the bridge.
Unfinished write controls render disabled, labelled *"עריכה תהיה זמינה בשלב הבא"*.

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
