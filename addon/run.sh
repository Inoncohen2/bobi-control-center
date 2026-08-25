#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
#
# Home Assistant Add-on entrypoint — SKELETON for Phase 2.
#
# Reads the user's add-on options via bashio and starts the same FastAPI app
# that the standalone container runs.

set -euo pipefail

LOG_LEVEL="$(bashio::config 'log_level')"
ADAPTER="$(bashio::config 'adapter')"

export BOBI_LOG_LEVEL="${LOG_LEVEL}"
export BOBI_ADAPTER="${ADAPTER}"
export BOBI_DATA_DIR="/data"

if [ "${ADAPTER}" = "real" ]; then
    # Phase 2: the Supervisor injects SUPERVISOR_TOKEN when homeassistant_api is
    # enabled in config.yaml. It is read server-side only and never reaches the
    # browser. RealHomeAssistantAdapter is not implemented yet, so the backend
    # will refuse to serve requests and say so plainly.
    export BOBI_HA_URL="http://supervisor/core"
    export BOBI_HA_TOKEN="${SUPERVISOR_TOKEN:-}"
    bashio::log.warning "adapter=real is not implemented yet; Phase 1 supports 'mock' only."
else
    bashio::log.info "Starting Bobi Control Center in mock mode — no Home Assistant access."
fi

bashio::log.info "Listening on port 8000 (Ingress)."

exec python -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --log-level "${LOG_LEVEL}" \
    --proxy-headers \
    --forwarded-allow-ips '*'
