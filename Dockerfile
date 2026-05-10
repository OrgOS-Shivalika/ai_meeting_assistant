# Image used by both the FastAPI app and the Celery worker. The container
# command differs between services in docker-compose.yml.

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System packages: psycopg2 needs libpq; build-essential is needed for any
# wheels that fall back to source.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Cache the dependency layer.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code is bind-mounted in dev (see docker-compose.yml). For
# prod / CI, copy it in.
COPY . .

# Default command — overridden per service in compose.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
