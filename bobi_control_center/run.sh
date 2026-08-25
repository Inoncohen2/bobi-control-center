#!/usr/bin/env sh
#
# Bobi Control Center entrypoint.
#
# Reads add-on options when running under the Supervisor (bashio is available
# on the Home Assistant base images) and falls back to plain defaults so the
# same image runs locally with `docker run`.

set -eu

LOG_LEVEL="info"
DEBUG_HTTP="false"

if command -v bashio >/dev/null 2>&1 && bashio::supervisor.ping 2>/dev/null; then
    LOG_LEVEL="$(bashio::config 'log_level')"
    DEBUG_HTTP="$(bashio::config 'debug_http')"
fi

export BOBI_LOG_LEVEL="${LOG_LEVEL}"
export BOBI_DEBUG_HTTP="${DEBUG_HTTP}"
export BOBI_DATA_DIR="${BOBI_DATA_DIR:-/data}"

# The adapter is chosen by the presence of SUPERVISOR_TOKEN, which the
# Supervisor injects because config.yaml sets homeassistant_api: true. The
# token is never echoed, logged, or passed to the frontend.
if [ -n "${SUPERVISOR_TOKEN:-}" ]; then
    echo "[bobi] SUPERVISOR_TOKEN present — using the real Home Assistant bridge (read-only)."
else
    echo "[bobi] No SUPERVISOR_TOKEN — using mock data. This is expected outside Home Assistant."
fi

echo "[bobi] Listening on 0.0.0.0:8099 (Ingress)."

exec python -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8099 \
    --log-level "${LOG_LEVEL}" \
    --proxy-headers \
    --forwarded-allow-ips '*'
