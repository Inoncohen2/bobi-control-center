# Connecting Home Assistant (Phase 2)

> **Nothing in this document is implemented.** Phase 1 ships
> `MockHomeAssistantAdapter` only. `RealHomeAssistantAdapter` exists as a stub
> whose every method raises, so selecting it cannot silently half-work.

## Why this is a small change

The frontend never learns how Bobi is implemented inside Home Assistant. All
Home Assistant knowledge is confined below one interface:

```
React UI → Bobi Management API → BobiService → HomeAssistantAdapter → (Home Assistant)
```

Because the adapter returns **domain models rather than HA payloads**, Phase 2
is additive: implement the interface, flip one setting, change nothing else.

Two automated guards keep this true as the code grows
(`backend/tests/test_architecture.py`):

- the frontend must contain no hard-coded Home Assistant entity id;
- outside `adapters/`, `mock/` and the device mapper, the backend must not
  either.

## What Phase 1 already guarantees

| Guarantee | How it is enforced |
| --- | --- |
| No real device can be controlled | The mock adapter imports no HTTP client at all — asserted by a test |
| No real automation is created | Writes mutate in-memory state and return `dry_run: true` |
| The probe never executes | `would_execute` is hard-coded `false` in two layers |
| No credentials are needed | `BOBI_HA_URL` / `BOBI_HA_TOKEN` are unread while `adapter=mock` |
| No secret reaches the browser | Settings endpoints emit `"••••••••"`; the value stays server-side |

## Steps

### 1. Implement `RealHomeAssistantAdapter`

In `backend/app/adapters/real.py`, against the existing ABC. Suggested mapping:

| Adapter method | Home Assistant source |
| --- | --- |
| `get_entities` | `GET /api/states`, enriched from the entity/device/area registries over the WebSocket API |
| `get_system_status` | `GET /api/config` + the health of Bobi's own components |
| `get_automations` | Bobi's own schedule store, **not** `automation.*` entities |
| `save_automation` | Write to Bobi's schedule store, then reload |
| `get_shabbat_config` | Bobi's Shabbat store |
| `get_tasks` / `save_task` | `todo.*` entities via `todo.get_items` / `todo.add_item` |
| `get_calendar_events` | `GET /api/calendars/{entity_id}` |
| `preview_text` | Bobi's parser in probe-only mode — never a service call |
| `get_diagnostics` | HA error log plus Bobi's own health checks |

Keep `ProbeEngine` where it is. It is pure logic over the device list and is
identical in both adapters, so the Test Center behaves the same either way.

### 2. Map entities to Bobi devices

`services/devices.py` already does this for the mock fixtures via an id table.
For a real installation, replace that table with a mapping file under
`BOBI_DATA_DIR` so a household can rename devices and add aliases without a
code change:

```yaml
devices:
  living_room_ac:
    entity_id: climate.living_room
    display_name: מזגן סלון
    room: סלון
    aliases: [מזגן סלון, המזגן בסלון]
```

Aliases matter: they are what `ProbeEngine.resolve_target` matches spoken text
against.

### 3. Authenticate — server-side only

Two supported paths, neither of which puts a token in the browser:

- **As an add-on (preferred).** The Supervisor injects `SUPERVISOR_TOKEN` when
  `homeassistant_api: true`; the API base is `http://supervisor/core`. Nothing
  to configure by hand.
- **Standalone.** A long-lived access token in `BOBI_HA_TOKEN`, read from the
  environment by `config.py`.

Rules that must not be relaxed:

1. The token never appears in a response, a log line, or the frontend bundle.
2. All Home Assistant traffic originates from the backend process.
3. `.env` stays git-ignored; only `.env.example` is committed.

### 4. Switch the adapter

```bash
BOBI_ADAPTER=real
BOBI_HA_URL=http://homeassistant.local:8123
BOBI_HA_TOKEN=<long-lived token>
```

`api/deps.py` selects the implementation; nothing else changes.

### 5. Run the conformance suite against it

`backend/tests/test_adapter_contract.py` is written against the ABC, not the
mock. Add `RealHomeAssistantAdapter` to its `ADAPTERS` list and the same tests
validate it unchanged.

### 6. Turn writes on deliberately

Set `read_only = False` on the adapter only once the write paths are trusted.
Until then every write still routes through Preview → Confirm and returns
`dry_run: true`, so the UI is already correct — the flag is the last switch,
not the first.

## Live updates (optional)

Subscribe to `state_changed` over the Home Assistant WebSocket API and fan
changes out to browsers on `/api/bobi/ws`. The frontend already refetches
through TanStack Query, so a socket message need only invalidate a query key.

## Add-on packaging

`addon/` holds the skeleton: `config.yaml` (Ingress, API permissions, options
schema, watchdog on `/health`), `Dockerfile` (Home Assistant base image) and
`run.sh` (reads options via bashio). See `addon/DOCS.md`.

Ingress means the UI is served through Home Assistant's authenticated proxy, so
the add-on publishes no port and needs no login of its own. `uvicorn` runs with
`--proxy-headers` so it builds correct URLs behind that proxy.

## Risks worth planning for

| Risk | Mitigation |
| --- | --- |
| An entity is renamed or removed | Surface it as a diagnostic issue (already modelled) rather than failing the page |
| A service call fails midway | Report per-target results; the audit record already stores `success` |
| A schedule fires while being edited | Drafts are client-side; only a confirmed save is written |
| A token leaks into a log | Never interpolate settings into log lines; `config.py` is the only reader |
| Clock/timezone drift | Take the timezone from `GET /api/config`, replacing the fixed offset in `timeutil.py` |
