# Multi-stage build for Railway deployment.
#
# One image contains both the compiled React frontend AND the FastAPI
# backend. `main.py` already serves `meeting_ai_frontend/dist` as static
# files, so a single uvicorn process handles the API + the SPA on the
# same port.
#
# The same image is reused for the web, worker, and beat services on
# Railway — only the start command differs (set per-service in Railway's
# UI). Web uses the CMD below; worker/beat override it.


# --------------------------------------------------------------------
# Stage 1: build the React frontend
# --------------------------------------------------------------------
FROM node:20-alpine AS frontend
WORKDIR /fe

# Cache-friendly dependency install: copy manifests first, install, then
# copy the rest. Editing app code doesn't invalidate the npm install layer.
COPY meeting_ai_frontend/package.json meeting_ai_frontend/package-lock.json ./
# `npm install` (not `npm ci`): the lockfile is generated on Windows and omits
# Linux-only optional deps (e.g. @emnapi/core needed by native wasm runtimes),
# which makes strict `npm ci` fail inside this Alpine image.
RUN npm install --prefer-offline --no-audit --no-fund

COPY meeting_ai_frontend/ ./
RUN npm run build   # produces /fe/dist


# --------------------------------------------------------------------
# Stage 2: Python backend + copied frontend dist
# --------------------------------------------------------------------
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System packages for psycopg2 (libpq) + wheels that need to compile from
# source. Removed after install to keep the image lean.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Cache-friendly: install deps before copying source.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App code.
COPY . .

# Pull the built frontend from stage 1 into the exact path main.py expects.
COPY --from=frontend /fe/dist /app/meeting_ai_frontend/dist

# Railway injects $PORT at runtime. Fall back to 8000 for local
# `docker run` / `docker compose` invocations.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
