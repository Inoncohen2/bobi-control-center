# Home Assistant Add-on image — SKELETON for Phase 2.
#
# Built on the Home Assistant base image so the Supervisor's s6 init, bashio
# helpers and architecture matrix all work. The application layers are the same
# as the standalone Dockerfile at the repository root.

ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.11-alpine3.19
FROM ${BUILD_FROM}

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BOBI_HOST=0.0.0.0 \
    BOBI_PORT=8000 \
    BOBI_DATA_DIR=/data

WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app

# The prebuilt SPA. The add-on build expects `npm run build` to have run first
# (see the repository root Dockerfile for the multi-stage equivalent).
COPY frontend/dist ./app/static

COPY addon/run.sh /run.sh
RUN chmod a+x /run.sh

# The Supervisor reaches the app through Ingress on this port.
EXPOSE 8000

CMD ["/run.sh"]
