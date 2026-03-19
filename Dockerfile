# ============================================================
# LocalChat — multi-stage Dockerfile
# ============================================================
#
# Stage 1 (builder): installs Python dependencies into a venv.
# Stage 2 (runtime): copies only the venv + source; no build
#                    toolchain in the final image.
#
# Build:
#   docker build -t localchat:latest .
#
# Run (development):
#   docker run --env-file .env -p 5000:5000 localchat:latest
#
# The image expects all configuration through environment variables
# (see config/.env.example for the full list).
# ============================================================

# ---- Stage 1: builder ----------------------------------------
FROM python:3.12-slim AS builder

# System deps needed to compile native extensions (psycopg, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy dependency manifest first — this layer is cached unless
# requirements.txt changes.
COPY requirements.txt .

# Create a virtual environment and install all deps into it.
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt


# ---- Stage 2: runtime ----------------------------------------
FROM python:3.12-slim AS runtime

# Runtime system dep: libpq for psycopg
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user for security
RUN groupadd --gid 1000 localchat && \
    useradd  --uid 1000 --gid localchat --shell /bin/bash --create-home localchat

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Copy application source
COPY --chown=localchat:localchat . /app

# Create runtime directories
RUN mkdir -p /app/logs /app/uploads /app/htmlcov && \
    chown -R localchat:localchat /app/logs /app/uploads

USER localchat

# ── Environment defaults (override in docker-compose / K8s) ──
# All secrets (SECRET_KEY, PG_PASSWORD, …) MUST be injected at
# runtime — never bake them into the image.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    SERVER_HOST=0.0.0.0 \
    SERVER_PORT=5000 \
    LOG_FORMAT=json \
    DEMO_MODE=false

EXPOSE 5000

# Healthcheck — hits the lightweight /api/health endpoint.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python - <<'EOF'
import urllib.request, sys
try:
    urllib.request.urlopen("http://localhost:5000/api/health", timeout=5)
    sys.exit(0)
except Exception:
    sys.exit(1)
EOF

# Gunicorn entrypoint.
# Workers = 2 × CPU + 1  (override with GUNICORN_WORKERS env var).
# Timeout = 120 s for slow RAG responses.
CMD ["sh", "-c", \
     "gunicorn app:create_gunicorn_app() \
        --bind 0.0.0.0:${SERVER_PORT:-5000} \
        --workers ${GUNICORN_WORKERS:-2} \
        --timeout 120 \
        --access-logfile - \
        --error-logfile - \
        --log-level info"]
