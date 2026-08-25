# Changelog

The version here is the one in `bobi_control_center/config.yaml`, which is what
Home Assistant compares to decide whether an update exists. Every change that
reaches the app image gets a new version and an entry below.

## 2.0.1

Normalization of real bridge responses, after the second live test.

- **Status** — WhatsApp, the AI fallback and its fast paths, the household,
  feature toggles and configuration health are first-class fields instead of
  text rows in `details`. The dashboard's health row is derived from them, since
  the real bridge sends no `components` array. Each section is accepted nested,
  bare or flat-prefixed.
- **Device limits** — the bridge's domain-specific constraints are kept in full
  (climate temperature range and mode lists, light colour temperature and
  brightness, scent intensity, slots and timer) rather than collapsed into
  `min`/`max`/`step`, which stay as a generic view.
- **Shabbat** — the pre-Shabbat offset is read from
  `upcoming.pre_offset_minutes`, profile device `tokens` are resolved through
  `device_labels` into `{id, label}` pairs, and `ac_temperatures` became a list
  so each temperature stays tied to its air conditioner.
- `/api/bobi/connection` reports `app_version`, so the UI no longer hard-codes it.

## 2.0.0

First release as a Home Assistant App: Ingress on port 8099, no external port,
`SUPERVISOR_TOKEN` used server-side only. Ten screens on the nine
`script.bobi_cc_*` bridge services, read-only throughout.

Shipped in two pushes — `8cc319a` normalized the real bridge responses and fixed
the diagnostics 502 **without bumping this version**, so the Supervisor never
offered it as an update. That mistake is what the version guards now prevent.
