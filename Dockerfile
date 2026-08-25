# syntax=docker/dockerfile:1
#
# Bobi Control Center — single production image.
#
# The frontend is built in one stage and copied into the Python image, so the
# final container runs one process that serves both the API and the UI.

# --- stage 1: build the frontend -------------------------------------------
FROM node:22-alpine AS frontend

WORKDIR /build

# Copy manifests first so the dependency layer is cached across source edits.
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
RUN npm run build


# --- stage 2: runtime ------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    BOBI_ADAPTER=mock \
    BOBI_HOST=0.0.0.0 \
    BOBI_PORT=8000

WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app

# The compiled SPA is served by FastAPI from app/static.
COPY --from=frontend /build/dist ./app/static

# Persistent configuration lives here; the add-on mounts /data over it.
RUN mkdir -p /data && \
    adduser --system --group --no-create-home bobi && \
    chown -R bobi:bobi /app /data
USER bobi

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
