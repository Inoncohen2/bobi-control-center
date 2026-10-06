# Bobi Next — audited capability catalog

Source: the live, read-only Bobi Capability Registry captured before migration.
The catalog contains **82 distinct legacy capability families**. Nothing here is
considered migrated merely because Bobi Next has a generic core; every row must
reach `verified` before the old implementation can be removed, unless an
explicit product decision deprecates it.

Status: `foundation` = underlying generic machinery exists; `partial` = some of
the user-visible behavior is implemented; `planned` = audited and still to be
implemented; `ready` = code/tests exist; `verified` = accepted live shadow/E2E.

| Legacy capability | Bobi Next module | Status |
|---|---|---|
| home | device/control core | partial |
| climate | climate adapter | partial |
| vacuum | vacuum adapter | partial |
| calendar | calendar module | planned |
| reminders | reminder scheduler | planned |
| watches | condition-watch engine | planned |
| recipes | recipe store/search | planned |
| diagnostics | diagnostics engine | planned |
| memory | local memory/learning | foundation |
| rules | conversational rule engine | planned |
| voice | voice transport/provider | planned |
| attention | attention center | planned |
| entity_resolver | generic HA semantic resolver | ready |
| dry_run | shadow engine | ready |
| health | self-health engine | planned |
| undo | reversible action ledger | planned |
| personal_memory | user memory | planned |
| knowledge | household knowledge | planned |
| scenes | scene/mode module | planned |
| activity | audit/activity ledger | planned |
| briefing | daily brief engine | planned |
| history | HA history/event reader | planned |
| conflicts | rule conflict detector | planned |
| explain | decision trace/explanation | planned |
| safe_recovery | controlled recovery | planned |
| tasks | task module | planned |
| cameras | camera adapter | foundation |
| shabbat | Jewish calendar/Shabbat engine | planned |
| finance | finance information provider | planned |
| weather | weather provider | planned |
| prayers | prayer-times provider | planned |
| usage | statistics/history analytics | planned |
| menus | dynamic menu engine | planned |
| permissions | user/role/capability policy | planned |
| ai_status | AI provider/status/usage | planned |
| multimodal | media/vision/document ingest | planned |
| shopping | shared shopping module | planned |
| conversation_context | conversation/active context | foundation |
| goals | goal/life-mode engine | planned |
| workflows | multi-step workflow engine | planned |
| root_cause | trace/history/log correlation | planned |
| performance | runtime metrics/health score | planned |
| habits | on-demand habit insights | planned |
| missed_briefing | activity/event digest | planned |
| verification | read-after-write verifier | ready |
| benchmark | benchmark harness | planned |
| meeting_travel_alerts | calendar/ETA alerts | planned |
| printer | printer adapter | planned |
| oref | alert/provider adapter | planned |
| internet | connectivity diagnostics | planned |
| system_status | HA/host system health | planned |
| services | external service/App health | planned |
| backups | HA backup integration | planned |
| github | Git backup/integration status | planned |
| updates | HA/App update discovery | planned |
| parasha | weekly-portion provider | planned |
| jewish_times | Jewish-day times provider | planned |
| eta_home | presence/location ETA | planned |
| robi_stats | vacuum analytics | planned |
| night_usage | history analytics | planned |
| empty_home_stats | presence analytics | planned |
| removal_center | dependency-aware safe removal | planned |
| navigation | command/navigation discovery | planned |
| vouchers | voucher wallet | planned |
| howto | contextual how-to engine | planned |
| checklists | checklist module | planned |
| guest_mode | mode/policy engine | planned |
| snooze | notification/reminder rescheduler | planned |
| packages | package tracking | planned |
| renewals | renewal/expiry scheduler | planned |
| recurring_tasks | recurring task scheduler | planned |
| image_inbox | image inbox | planned |
| exit_check | presence/checklist evaluator | planned |
| receipts | explicit archive + bounded labeled financial extraction; owner-scoped details and typed field review with exact approval/CAS/restart receipts; searchable reviewed merchant/number; richer extraction + hosted/live parity pending | partial |
| documents | explicit save/retrieval + category move/soft-delete/restore; exact approval/state guard/atomic receipts; verified setup choice and isolated WAHA/provider retry/restart contracts; hosted cloud + live parity pending | partial |
| notes | personal notes | planned |
| products | product/warranty store | planned |
| expenses | receipt-linked + complete typed manual entries; exact approval/atomic audit/CAS/dedupe/restart; explicit owner-private edit/soft-delete/restore; source provenance and local v1/v2 upgrades; monthly currency totals exclude deleted entries; refunds/budgets + live parity pending | partial |
| object_search | owner-isolated archive search/retrieval; live parity pending | partial |
| context_authority | typed context authority | partial |
| parking | personal parking memory | planned |
| inventory | consumables inventory | planned |

## Runtime settings and infrastructure observed in legacy Bobi

These are release-blocking even though they are not separate capability rows:

- AI enabled/provider/fallback
- fast paths
- automatic morning briefing
- automatic home-status reporting
- default meeting alerts
- default travel alerts
- WhatsApp session/QR/reactions/typing/voice/media/polls
- request deduplication and one-terminal-reply ownership
- concurrency/queue behavior
- approval ledger and permissions
- Instinct fallback/re-entry through normal safety guards
- Supabase/optional cloud storage
- local-first persistent storage
- setup/onboarding wizard
- automatic HA discovery and capability inference

## Known legacy defects that are **not** parity requirements

- A cover-position request can be routed into an AC swing context.
- A relative climate change can resolve the correct climate entity while the
  legacy plan loses the temperature delta and validates only `power`.

The Bobi Next parity engine therefore supports `match`, `improved`,
`regression`, `mismatch` and `inconclusive`. An explicit expected-behavior
contract is authoritative; a fixed legacy bug is recorded as `improved`.
