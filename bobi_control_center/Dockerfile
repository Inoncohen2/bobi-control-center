# syntax=docker/dockerfile:1
#
# Bobi Control Center — Home Assistant App image.
#
# The entire build context lives under this directory, so the image builds
# standalone (`docker build bobi_control_center/`) exactly the way the
# Supervisor builds it.

# --- stage 1: compile the React frontend -----------------------------------
FROM node:22-alpine AS frontend

WORKDIR /build

# Manifests first so the dependency layer survives source edits.
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
RUN npm run build


# --- stage 2: Python runtime -----------------------------------------------
ARG BUILD_FROM=python:3.11-slim
FROM ${BUILD_FROM}

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    BOBI_HOST=0.0.0.0 \
    BOBI_PORT=8099 \
    BOBI_DATA_DIR=/data

WORKDIR /app

# Production dependencies only — no pytest, ruff or other dev tooling.
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app

# FastAPI serves the compiled SPA from here.
COPY --from=frontend /build/dist ./app/static

COPY run.sh /run.sh
RUN chmod a+x /run.sh

# Ingress reaches the app on this port; it is never published to the host.
EXPOSE 8099

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8099/health', timeout=4).status == 200 else 1)"

CMD ["/run.sh"]
