# The Bobi Control Center bridge

How this app talks to Home Assistant, and why it cannot do anything else.

## The contract

Home Assistant exposes a stable set of `script.bobi_cc_*` services. They are the
**only** contract between this app and Bobi. The app never enumerates entities,
never reads arbitrary states, and never inspects Bobi's internal scripts,
helpers or WhatsApp logic.

| Bridge service | Parameters | App endpoint |
| --- | --- | --- |
| `script.bobi_cc_status` | — | `GET /api/bobi/status` |
| `script.bobi_cc_devices` | `scope`, `include_unavailable` | `GET /api/bobi/devices` |
| `script.bobi_cc_capabilities` | — | `GET /api/bobi/capabilities` |
| `script.bobi_cc_users` | — | `GET /api/bobi/users` |
| `script.bobi_cc_shabbat` | — | `GET /api/bobi/shabbat` |
| `script.bobi_cc_rules` | — | `GET /api/bobi/rules` |
| `script.bobi_cc_tasks` | — | `GET /api/bobi/tasks` |
| `script.bobi_cc_diagnostics` | — | `GET /api/bobi/diagnostics` |
| `script.bobi_cc_probe` | `text` | `POST /api/bobi/probe` |

Device scopes: `all`, `lighting`, `climate`, `cameras`, `battery`,
`temperature`, `humidity`, `vacuum`, `people`, `switches`, `scent`.

## How a call is made

```
POST http://supervisor/core/api/services/script/bobi_cc_probe?return_response
Authorization: Bearer ${SUPERVISOR_TOKEN}
Content-Type: application/json

{"text": "כבה מזגן הורים ב-1:30 בלילה"}
```

`?return_response` is what makes a script hand data back rather than just fire.

`RealHomeAssistantAdapter.call_service()` is the single method that does this.
It is reused by all nine endpoints and:

- refuses any service outside the nine-item allow-list, **before** issuing a
  request;
- unwraps the response defensively (see below);
- converts every Home Assistant failure into the app's structured error shape.

### Normalization

Unwrapping gets the payload; `app/services/normalize.py` then maps it onto the
canonical contract. It is the only module that knows bridge field names, and it
is written to tolerate variation:

| Bridge sends | Canonical response |
| --- | --- |
| `entries` | `devices` |
| `registry` (map **or** list) | `capabilities` |
| status sections (`whatsapp`, `ai`, `users`, `config`, `features`) | first-class fields, plus a derived `components` row |
| domain limits (`min_temp`, `fan_modes`, `min_kelvin`, `scent_slots`, …) | one `limits` model keeping every one |
| `upcoming` / `profiles` / `drafts` | flat times, one `profiles` list, `has_draft` |
| profile `tokens` + `device_labels` | `devices: [{id, label}]` |
| `ac_temperatures` map | a list, each temperature tied to its air conditioner |
| per-user `users` (tasks) | one flat `tasks` list with `owner` |
| `{"result": {…}}` (probe) | flattened top-level fields |
| `checks` as a **map** | `checks` as a list |

Rules it follows:

* emit **exactly one** collection per resource — never a populated list beside
  an empty legacy one;
* accept a map or a list wherever either is plausible;
* never raise on a missing or oddly-typed field — a partial response must
  produce an empty screen, not a 502;
* route unmapped fields into a per-item `extra` map so nothing is silently lost;
* resolve device tokens to friendly names, so the UI never shows a raw token —
  while keeping the token itself alongside the label, since a write in Phase 3
  will have to send it back;
* drop anything resembling a phone number, LID or chat id, even if a future
  bridge version starts sending one.

### Response unwrapping

Home Assistant has shipped more than one shape for a service-call response, so
`extract_service_response()` handles all of them:

| Received | Returned |
| --- | --- |
| `{"service_response": {...}}` | the inner object |
| `{...}` | itself |
| `[{"service_response": {...}}]` | the inner object |
| `[{...}]` | the single element |
| `{"response": {...}}` | the inner object |
| `[]` | `None` |

Anything else is reported as `bridge_bad_shape` rather than guessed at.

### Errors

Nothing is swallowed. Each failure becomes `{code, message, details}` with a
Hebrew message safe to display:

| Situation | `code` | What the user sees |
| --- | --- | --- |
| Script not installed | `bridge_service_missing` | *שירות הגשר … לא נמצא ב-Home Assistant* |
| Token rejected | `ha_unauthorized` | *אין הרשאה לגשת ל-Home Assistant* |
| HA returned 5xx | `ha_error` | *Home Assistant החזיר שגיאה* |
| Timeout / transport | `upstream_unavailable` | *Home Assistant לא הגיב בזמן* |
| Unparseable payload | `bridge_bad_shape` | *התקבל מבנה נתונים לא צפוי* |

The frontend distinguishes these from bugs and renders
*"לא הצלחתי לקבל נתונים מ-Home Assistant"* with the code collapsed under
**פרטים טכניים**.

## Authentication

The Supervisor injects `SUPERVISOR_TOKEN` because `config.yaml` declares
`homeassistant_api: true`. Rules enforced in code and asserted by tests:

1. The token is read from the environment via a property, never stored as a
   settings field — so `model_dump()` cannot serialise it.
2. It appears only in the outgoing `Authorization` header.
3. It is never logged; no logging call in the adapter touches headers or the
   token.
4. It never reaches the browser. React calls FastAPI; FastAPI calls Home
   Assistant.
5. No long-lived access token is ever created or requested.

## Adapter selection

```
BOBI_ADAPTER=auto (default)
├── SUPERVISOR_TOKEN present → RealHomeAssistantAdapter
└── otherwise                → MockHomeAssistantAdapter
```

`mock` and `real` can be forced explicitly. Asking for `real` without a token
falls back to mock with a warning, rather than issuing requests that would all
fail with 401.

Both adapters return identical models, so the frontend cannot tell them apart —
which is what makes local development faithful.

## Why writes are impossible

Read-only is structural, not a convention:

- `HomeAssistantAdapter` declares **no write method**. There is nothing for an
  adapter to implement, and adding one means editing the interface.
- The real adapter's `ALLOWED_SERVICES` contains exactly the nine bridge
  scripts. `call_service("script", "anything_else")` raises before a request is
  built — verified by a test that asserts no HTTP call was attempted.
- The API exposes exactly one non-GET route: `POST /api/bobi/probe`. A test
  enumerates the router and asserts that.
- `would_execute` is hard-coded `False` in both adapters and restated by the
  response model. It is never derived from what the bridge returned.
- `writes_enabled` is forced to `False` on status and Shabbat responses even if
  the bridge says otherwise.

## The split read path (3.11)

Device reads come from two places now, chosen by how often each half changes:

| Half | Source | Cached |
| --- | --- | --- |
| Catalogue — which devices exist, canonical ids, Hebrew names, capabilities, limits | `script.bobi_cc_devices` | 60s |
| Live state — what is on right now | `GET /api/states` | never |

Writes are unaffected and stay entirely in the `bobi_cc_*_commit` bridges.

### The one bridge change this needs

The app cannot look up a canonical id's entity for itself — that mapping is the
household's, and it lives in Home Assistant. So `bobi_cc_devices` must publish
`entity_id` on each **managed item** (its `entries` already carry one; the
items do not):

```jinja
{'id': 'laundry', 'label': 'חדר כביסה', 'kind': 'toggle', ...,
 'entity_id': 'switch.tvrt_kbysh_vkhtsr_switch_1'}
```

Nothing else changes. The normalizer already strips `entity_id` from everything
it hands a client, and `live_state.entity_map` reads it from the raw payload
*before* that stripping — so the id is used to look a state up and never
travels any further. There is a test asserting it does not appear in a rendered
snapshot.

The bridge publishes it as of 3.13.1, so the overlay is live. Before that
`entity_map` returned `{}` and device reads behaved exactly as they did before
the split — the intended fail-soft path, not a broken state, and still what
happens if the field ever stops arriving.

## The Shabbat profile device list

`script.bobi_cc_shabbat` offers fifteen device tokens, and that is the whole
list on purpose. Widening it is not one change but three that must agree:

| Script | What it holds |
| --- | --- |
| `bobi_cc_shabbat` | the `labels` map — which devices are *offered* |
| `bobi_cc_shabbat_commit` | `allowed_tokens` — which may be *written* |
| `shabbat_apply_profile` | a branch per token — which are actually *switched* |

A token added only to the first is selectable, savable, and does nothing at the
hour it matters. That is worse than not offering it.

It was reviewed against the whole install in August 2026 and left at fifteen.
What remains unlisted is not an oversight: infrastructure (`switch.hacs_*`),
child locks, the switch-side duplicates of three lights already covered through
their `light.*` entities, the camera's own feature switches, and the vacuum,
which is deliberately fenced off — a profile that turns things *on* must never
be able to start it.

## The air conditioner settings in a profile (3.14)

Each air conditioner in an on-profile publishes a target temperature plus
`hvac_mode`, `fan_mode` and `swing_mode`, stored in `input_select` helpers named
`shabbat_{pre,morning}_ac_{salon,parents,girls}_{hvac,fan,swing}_mode`.

Two rules keep this honest:

* the accepted options are read from the helper itself
  (`state_attr(ac_helper, 'options')`), so the bridge that reads and the bridge
  that writes cannot come to disagree about what is legal;
* each helper's first option is what the executor previously hard-coded —
  `cool`, `auto`, `off` — so an unedited profile behaves as it always did.

The item ids are `profile.<phase>.<device>.<setting>`. The device a setting
belongs to is the **first** segment after the phase, which is what lets a
device with several settings keep them together on one screen.

## The camera picture (3.15)

`GET /api/bobi/cameras/{canonical_id}/snapshot` returns image bytes. It is the
second read that does not go through a `bobi_cc_*` script — there is no bridge
service that returns an image, and a Jinja template could not carry one.

| Step | Where |
| --- | --- |
| Read the camera catalogue | `script.bobi_cc_devices` with `scope=cameras` |
| Resolve canonical id → entity | `app/services/camera.resolve` |
| Fetch the frame | `GET /camera_proxy/<entity>` with the Supervisor token |

Three rules hold it in place:

* **the request names a canonical id**, never an entity id — the route's path
  pattern admits only `[a-z0-9_]+`, so an entity id (which has a dot) is
  rejected before any lookup, and there is no parameter that accepts one;
* **the resolved entity must be in the `camera` domain** — `laundry` is a real
  canonical id in the catalogue and is refused, which is what stops this being
  a general image proxy for whatever else the bridge published;
* **the camera's own `access_token` is never read.** Home Assistant publishes
  one on the entity as `entity_picture`, and it is a working credential for the
  stream. The frame is authorised with the Supervisor token in a header
  instead, and only bytes reach the browser.

Both failure modes — unknown id, and an id that is not a camera — answer the
same 404 with the same message. The response is `no-store, private` and
`nosniff`; a camera frame is a picture of the inside of a house and does not
belong in a cache.

Reading a camera never starts one. `camera.lia_local` answers 500 while the
camera is unplugged, and that becomes *המצלמה אינה זמינה כרגע*.

## Data the app deliberately does not touch

| Not touched | Why |
| --- | --- |
| Raw entity states *for anything but a switch position* | The bridge's device catalog is the contract; see the split above |
| Bobi's scripts, helpers, automations | Not the app's concern |
| WhatsApp numbers and LIDs | The bridge withholds them; the app must not reintroduce them |
| Task internal descriptions | The bridge sanitises them |
| Native HA automations | `bobi_cc_rules` returns Bobi's canonical rules instead |

## Phase 3: enabling writes

1. Add write methods to `HomeAssistantAdapter` — one per bridge write service.
2. Extend `ALLOWED_SERVICES` with those service names.
3. Implement them in the real adapter; the mock mutates in-memory state.
4. Flip `writes_enabled` once the write paths are trusted.
5. Replace the `DisabledAction` / `NextPhaseBadge` components with live
   controls. The UI already renders them in the right places.

Keep the Preview → Confirm model from Phase 1 for anything destructive.
