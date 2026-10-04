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
| `automation.whatsapp_qlytt_hvd_vt_waha` | auth, PN/LID identity, event filtering, exact-message dedupe, reaction/typing, media routes, poll routes, lifecycle, Rescue | `whatsapp.ingress` + policies + router | inventoried |
| `script.whatsapp_text_router_entry` | ordered intent routing, negation, menu/dialog authority, context, multi-intent, fallback | typed router/pipeline | inventoried |
| `script.bobi_entity_resolver` | canonical target, capabilities, ambiguity fail-closed | dynamic HA registry + semantic resolver | V2 foundation started |
| `script.bobi_target_resolver` | single/group/area targets, exclusions, confidence, authority | semantic resolver | V2 foundation started |
| `script.bobi_command_validate` | capability/range/step validation | capability contract + planner | V2 foundation started |
| `script.whatsapp_command_execute` | availability, mutation authority, execution guard, undo, handler dispatch, Rescue | executor + policies | contract extracted |
| `script.bobi_command_verify` | HA-state confirmation, tolerance, freshness/truth metadata | verifier | contract extracted |
| `script.bobi_request_lifecycle` | request receipt, atomic reply ownership, terminal ledger | SQLite request ledger | schema started |
| `script.bobi_conversation_context_store` | per-user turns, idempotency, typed semantics, expiry | SQLite conversation/context | schema started |
| `script.bobi_instinct_rescue` | one rescue per request, RESOLVE/CLARIFY/UNRESOLVED, re-entry through guards | fallback/instinct | contract extracted |

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
