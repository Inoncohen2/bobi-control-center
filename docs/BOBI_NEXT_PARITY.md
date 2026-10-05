# Bobi Next — parity contract

This document is the migration gate between the current Home Assistant-script implementation and the generic Bobi engine.

## Safety baseline

- Production Bobi remains unchanged while Bobi Next is built.
- Pre-migration restore point: Home Assistant backup `5fe92014` (2026-10-04), including the HA database, all Apps, and media/share/ssl.
- Bobi Next runs in shadow/read-only mode until the relevant parity rows are green.
- Home Assistant remains the source of truth for live device state.
- Bobi's SQLite database stores semantic identity, aliases, user context, pending workflows, configuration and ledgers — never an authoritative copy of a device's live state.
- Every mutation must preserve the current sequence: resolve → validate capability/range → authority/safety → dedupe → execute → read HA again → verify → reply.
- Recoverable failures may use Instinct, but Instinct never bypasses Bobi's resolver, safety or executor.

## Audited production surface

The initial exhaustive HA inventory found:

- 660 Bobi-related scripts
- 63 Bobi-related automations
- 330 Bobi-related helpers
- 2 Bobi dashboards
- WAHA GOWS App
- Bobi Control Center App

The counts are inventory, not the desired V2 architecture. Legacy, temporary, probe and regression scripts become tests rather than runtime modules wherever possible.

## Core contracts already audited

| Current component | Behaviour that must survive | Bobi Next destination | Status |
|---|---|---|---|
| `automation.whatsapp_qlytt_hvd_vt_waha` | auth, PN/LID identity, event filtering, exact-message dedupe, reaction/typing, media routes, poll routes, lifecycle, Rescue | `whatsapp.ingress` + policies + router | V2 transport/runtime implemented; live shadow gate pending |
| `script.whatsapp_text_router_entry` | ordered intent routing, negation, menu/dialog authority, context, multi-intent, fallback | typed router/pipeline | V2 router/orchestrator implemented; full legacy family parity pending |
| `script.bobi_entity_resolver` | canonical target, capabilities, ambiguity fail-closed | dynamic HA registry + semantic resolver | implemented + unit tested; live shadow gate pending |
| `script.bobi_target_resolver` | single/group/area targets, exclusions, confidence, authority | semantic resolver | implemented + unit tested; live shadow gate pending |
| `script.bobi_command_validate` | capability/range/step validation | capability contract + planner | implemented + unit tested |
| `script.whatsapp_command_execute` | availability, mutation authority, execution guard, undo, handler dispatch, Rescue | executor + policies | implemented + unit tested; controlled E2E gate pending |
| `script.bobi_command_verify` | HA-state confirmation, tolerance, freshness/truth metadata | verifier | implemented + unit tested |
| `script.bobi_request_lifecycle` | request receipt, atomic reply ownership, terminal ledger | SQLite request ledger | implemented + unit tested |
| `script.bobi_conversation_context_store` | per-user turns, idempotency, typed semantics, expiry | SQLite conversation/context | implemented + unit tested |
| `script.bobi_instinct_rescue` | one rescue per request, RESOLVE/CLARIFY/UNRESOLVED, re-entry through guards | fallback/instinct | implemented; deterministic guards retained |

## Bobi Next implementation snapshot — 2026-10-05

The following V2 foundations are implemented on `chatgpt/bobi-next-generic-core` and covered by automated tests. This is not permission to replace production: shadow/live/rollback gates still apply.

| Family | Implemented V2 contract | Remaining gate |
|---|---|---|
| Generic HA discovery/control | device/entity discovery, capability inference, stable semantic IDs, resolver, planner, relative climate deltas, secure execution, read-after-write verification | live shadow + controlled mutation |
| Scheduling | persistent schedules, recurrence, retry/cancel, leases, live re-resolution, secure scheduled execution | migration + live E2E |
| Conditional rules | HA state stream, threshold/state rules, cooldown/dedupe, `for X seconds` durable recheck, secure execution | live shadow/E2E |
| Permissions/approval | typed policy, fail-closed authority, exact one-time approvals, state guard, race protection, restart-safe continuation | user-policy migration + live E2E |
| WhatsApp messaging | durable inbox/outbox, dedupe, per-chat ordering, reaction/typing, media ingest, quote context, polls, exact approval polls, crash-safe poll reconciliation; opt-in runtime composition behind `next_messaging_enabled` | WAHA live shadow/E2E |
| AI/Understanding | structured semantic intent, context, provider runtime, Instinct rescue that re-enters deterministic guards | adversarial/live parity |
| Calendar/To-do | native HA response client and productivity engine without Bobi scripts/helpers | live parity |
| Activity/Undo | durable activity ledger and safe exactly-once undo runtime | live mutation parity |
| Archive/Documents | explicit-save authority, semantic archive index, SHA-256 dedupe, private storage, deterministic retrieval and category move/soft-delete/restore, exact deletion/review approval and atomic receipts, bounded advisory receipt/bill extraction and explicit typed review, WAHA `sendFile` with crash-safe delivery | hosted cloud + live E2E; richer document extraction pending |
| Vouchers/Supabase | typed client, voucher wallet and optional archive client; independent generic archive Edge API/schema prepared with isolation, integrity, retry and Python contract tests | provider undeployed; hosted Storage/Deno E2E and onboarding pending; no production Supabase mutation |
| Setup/Integrations | setup store/wizard foundations, roles/policies, secret vault, integration framework; archive local/cloud controls with authenticated protocol/installation check | hosted archive onboarding/provisioning, remaining Control Center UX + migration E2E |

### Archive/Documents safety contract

- Receiving a file does **not** save it automatically. Save is a separate side effect and requires an explicit non-negated user instruction plus `archive.write` permission.
- OCR/transcription/AI-derived text cannot authorize a save. Only the user's original message/caption may do so.
- Save authority is limited to direct imperative captions; mentions, quoted text, negations, questions and deferred/conditional requests do not authorize immediate archive writes.
- Explicit folder/category labels come from the current caption and are persisted as semantic categories. SHA dedupe confirms the existing record's actual category without silently moving it.
- Trusted media must be bound to the current provider/message/kind. Quote-only saves require a new current attachment until a separate trusted quote-media loader exists.
- Archive saves claim the existing durable request ledger before loading/uploading. Terminal dedupe survives restart; concurrent deliveries have one owner; recoverable outages and cancellation release the claim for retry.
- OCR/analysis is optional for an authorized save, while MIME, byte limits and SHA/storage integrity checks remain mandatory. Scanned PDFs may be saved without extracted text.
- Shadow/dry-run mode cannot upload/register archive content or enqueue/send archived files, including already queued file deliveries. Its replies never claim a file was saved or sent.
- Archive retrieval is recognized deterministically from an explicit user request before AI; generic send/show requests that do not clearly refer to saved/archive content stay in the normal Bobi pipeline.
- Archive search is isolated by `owner_key`; ambiguous results require clarification rather than guessing.
- Move/delete/restore commands resolve one named saved object from the current direct text. References, quoted/media-derived authority, questions and deferred instructions cannot create an archive mutation.
- Deletion is reversible: only the SQLite semantic record moves to trash; immutable provider bytes are retained. Category changes are semantic and do not rename provider object paths. Restore refuses a second active copy with the same SHA.
- Deletion and financial field review always need approval. Move/restore also respect the user's risk threshold. The existing pending/approval stores bind approval to the exact user, plan, provider/chat, object and revision; an exact SQL compare-and-swap closes the state-change race.
- Mutation and read-back receipt commit in one SQLite transaction. Confirmation message IDs stay bound to one exact prompt across restart, so replaying an old "yes" cannot approve a newer action. HA approval continuation rejects archive plans before any HA call.
- Private file deliveries recheck owner, active record, binary identity and read policy before loading and again before sending. A queued file deleted during loading is not sent; a provider send already accepted cannot be recalled.
- Current-media labeled text can enrich receipts/bills with merchant, document number, dates and exact integer minor-unit amounts. OCR/vision evidence remains `requires_review=true`; conflicting labels/currencies, ambiguous dates and incomplete text stay missing. It cannot grant authority, change an explicit folder or create expenses/reminders. Scanned/no-text documents remain saveable.
- Direct text can read a named receipt/bill's financial details with `archive.read` and the `archive.details` action, before searching any private records. The response separates explicitly reviewed fields from remaining advisory extraction; it never sends a file or loads a provider URL.
- Typed edits use `archive.write` and the `archive.review` action through the existing archive planner/policy/approval/executor. The approval shows the exact entered values. Amounts require an explicit supported currency and are stored as integer minor units; ambiguous/invalid dates, duplicate/unknown fields, reference-only targets, questions, deferred instructions and hidden formatting/control characters cannot grant edit authority.
- A review writes only explicitly typed fields plus previously reviewed fields. It never copies missing OCR values or promotes the original `financial_document` provenance. The separate owner/media-bound `financial_review` records the exact mutation receipt's request/plan and review timestamp. Changing a currency requires retyping any previously reviewed amounts that would otherwise be silently reinterpreted. Capture discards caller-supplied review metadata.
- Reviewed merchant/document number participate in the existing private search, so corrected details can resolve subsequent retrievals. Review changes neither immutable bytes, provider URI nor category, and creates no expense, reminder or payment. CAS verification and its durable receipt commit together, including recovery after a lost WhatsApp reply or reopening every Bobi store.
- Examples: `מה פרטי הקבלה של איקאה?`; `עדכן את פרטי הקבלה של איקאה: סכום=123.45 ILS; ספק=איקאה; תאריך=2026-10-05`. The edit remains pending until an authorized direct confirmation or exact poll selection. Media-derived/quoted text cannot supply its authority or confirmation. Use semicolons between typed fields; ISO dates avoid locale ambiguity. Supported field labels include supplier, number, date, due date, total and tax in Hebrew/English.
- Bobi can use private local storage under its own data directory without Supabase. Supabase/cloud storage remains an optional provider.
- Runtime reads route by the saved URI's provider, while new uploads use the explicitly selected mode. Existing local blobs remain readable after selecting cloud, and cloud blobs remain readable after selecting local while their cloud integration is enabled. Cloud errors never cause a local upload/read fallback.
- Archive configuration changes hold the request-claim lock and refuse active saves, including expired running claims. A cloud endpoint with retained objects (including trash) cannot be changed without an explicit migration, preserving existing retrieval/restore identity. Voucher-only configuration remains separate.
- Archive setup/integration routes are mounted only with the existing opt-in setup flag. Local storage needs no cloud credentials. A read-only authenticated `ping` must advertise the generic archive protocol and this exact installation; voucher-only or foreign-installation credentials cannot select cloud mode.
- The setup cloud choice requires a connection proof checked within five minutes, bound to the endpoint, enabled state and immutable credential version. Accepted configuration remains ready after that window; this is an identity/protocol check, not an uptime guarantee. Changed credentials invalidate the proof and block new uploads until rechecked. Existing URI reads keep provider authentication and archive read-policy checks.
- Isolated cross-language contracts now exercise trusted WAHA loading, direct-caption authority, real archive protocol/SQL, the durable message/reply/file queues, deletion and typed financial review approval, policy revocation and reopening Bobi's SQLite stores. WAHA and Supabase Storage HTTP are simulated; this does not replace hosted or live-house E2E.
- A prepared or sent reply resumes from its exact durable outbox payload after transport/worker failure. The handler is not reentered to regenerate a different confirmation or repeat side effects. Provider/chat/message context is rechecked before sending; file delivery still uses its separate current authorization checks.
- Private financial details/review replies recheck current read/write policy and the enabled actor/provider identity link immediately before each transport send, including a cached reply after restart. Trusted WAHA ingress persists a salted provider-scoped sender fingerprint; relinking the same sender to another user cannot disclose an old owner's queued fields. Earlier direct-chat inboxes re-resolve their identity; earlier group inboxes without a trusted participant binding fail closed. Static denials contain no financial data and remain deliverable.
- Explicit reply-authorization revocation is terminal and cannot automatically retry into a later grant. A transient authorization lookup error follows the existing bounded retry path and preserves the exact payload without reentering the handler. This prevents future sends; a provider send already accepted cannot be recalled.
- Outbound WhatsApp files use WAHA `sendFile` with private bytes (Base64), so no public document URL is required.
- Because the current WAHA `sendFile` schema has no caller-defined message id, a crash after provider acceptance but before local acknowledgement is marked `uncertain`; Bobi does not automatically resend and risk a duplicate.
- Messaging remains independently gated by `next_messaging_enabled`; enabling the HA/event runtime alone cannot start Bobi Next WhatsApp workers. First trials remain `next_messaging_dry_run=true` by default.

## Runtime families requiring parity

### Transport and UX

- WhatsApp connection/session management
- PN/LID user identity and permissions
- text, voice, image, PDF/document ingestion
- quoted/replied-to message context
- reactions before work, typing state, progress state
- text/RTL transport
- polls/menus and vote routing
- concurrency, queueing and one-primary-reply ownership
- exact and semantic deduplication
- WAHA health/recovery

### Understanding, context and safety

- typo/semantic normalization
- local/fast understanding
- entity/target resolution
- active device and room references
- conversation/quote/dialog context
- multi-intent and target inheritance
- clarification and correction
- capability/range validation
- negation/non-execution authority
- approval flows
- execution guard and idempotency
- undo
- read-after-write verification
- user-visible failure contracts
- Instinct rescue and AI/provider fallback

### Home/device control

- lights including brightness and colour temperature
- climates including exact and relative temperature (`±0.5` follows each entity's own step), HVAC, fan, swing and preset modes
- switches and boiler/timed boiler behaviour
- covers/position where present
- fans where present
- vacuums
- cameras and vendor-specific secondary entities
- KUNI/scent and future multi-entity devices
- scenes/modes and whole-home/group actions
- status/history/device truth

### Personal/productivity domains

- calendar create/read/update/delete and semantic resolution
- reminders, location reminders and event-linked reminders
- tasks, recurring tasks and checklists
- shopping and generic lists
- notes and personal memory
- contacts/iCloud
- Gmail ingest/read/actions/attachments/digest
- documents, images, receipts, vouchers and Supabase-backed media
- vehicles and vehicle documents/reminders
- utilities, electricity/water bills and analytics
- expenses/budget
- packages/deliveries
- renewals/expiries
- products/warranty
- recipes
- parking/location/ETA
- travel and meeting flows
- weather, morning brief and clothing advice
- Shabbat profiles/times/alerts
- vocabulary and other proactive features

### Operations / Control Center

- setup/onboarding
- automatic HA discovery
- users/roles/permissions
- settings and feature toggles
- capabilities and device inventory
- smart rules/automations/scenes/scripts views
- diagnostics and health
- audit/activity
- performance benchmarks
- regression/Test Center
- backups/system status

## Generic-device requirements

1. No private entity id, private room name, phone number or household alias is allowed in generic core code.
2. Semantic identity prefers HA `device_id`; standalone entities use `(platform, unique_id)` and only fall back to `entity_id` when HA exposes no stable identifier.
3. One physical device may own many HA entities; Bobi presents one semantic device and selects the entity that owns the requested capability.
4. Entity-id renames must not erase Bobi memory.
5. Capability limits are learned from live HA attributes/registries, not copied from the current house.
6. Ambiguity fails closed and asks for clarification instead of guessing.
7. Learned aliases/preferences live in Bobi storage and are optional overlays on HA's discovered names/areas.
8. Setup should not require the user to create Bobi helpers or scripts.

## Migration gates

A family may replace production only after all applicable gates pass:

- [ ] inventory complete
- [ ] typed V2 contract defined
- [ ] state migrated where required
- [ ] unit tests pass
- [ ] shadow result matches old Bobi on representative and adversarial cases
- [ ] live read-only probe passes on the user's HA
- [ ] controlled E2E mutation passes with read-after-write verification
- [ ] rollback path verified

No removal of the old scripts/helpers is part of the build phase.
