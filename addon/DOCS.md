# Bobi Control Center — Add-on

> **Status: skeleton.** These files describe how the add-on *will* be packaged.
> It is not published to an add-on repository yet, and in Phase 1 the
> application cannot read from or write to Home Assistant.

## What it does

Runs the Bobi Control Center web app inside Home Assistant and exposes it
through **Ingress**, so it appears in the sidebar and is protected by Home
Assistant's own authentication. No port is published to your network.

## Options

| Option | Values | Default | Meaning |
| --- | --- | --- | --- |
| `log_level` | `debug` \| `info` \| `warning` \| `error` | `info` | Verbosity of the add-on log. |
| `adapter` | `mock` \| `real` | `mock` | Data source. `mock` serves demo data; `real` is Phase 2 and not implemented. |

## Safety

While `adapter` is `mock`:

- the process contains no HTTP client for Home Assistant at all;
- every write returns `dry_run: true` and changes only in-memory state;
- `POST /api/bobi/probe` always answers `would_execute: false`.

Setting `adapter: real` before Phase 2 lands does not enable anything — the
backend returns a clear "not implemented" error rather than half-working.

## Health

The Supervisor watchdog polls `GET /health`, which answers:

```json
{ "status": "ok", "adapter": "mock", "version": "1.0.0" }
```

## Persistent data

`/data` is mapped for persistent configuration and is set as `BOBI_DATA_DIR`.

## Building locally

The add-on image expects the frontend to be built first:

```bash
cd frontend && npm ci && npm run build && cd ..
docker build -f addon/Dockerfile -t bobi-addon:dev .
```

For ordinary local use prefer the root `Dockerfile`, which builds the frontend
itself in a separate stage.

## Phase 2

See `docs/home-assistant-integration.md` for the plan to connect a real
installation, including what permissions are needed and why every write stays
behind the Preview → Confirm model.
