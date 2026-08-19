# ============================================================
# LocalChat — multi-stage Dockerfile
# ============================================================
#
# Stage 1 (builder): installs Python dependencies into a venv.
# Stage 2 (runtime): copies only the venv + source; no build
#                    toolchain in the final image.
#
# Both stages sit on Docker Hardened Images. The runtime variant
# ships no shell and no package manager and runs as uid 65532,
# which is why this file creates no user, installs nothing at
# runtime, and uses exec-form CMD/HEALTHCHECK throughout — there
# is no `sh` to expand a `${VAR:-default}` or to chain `|| exit 1`.
# `docker-entrypoint.py` does that expansion instead.
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
# The -dev variant carries the shell, apt and compilers the runtime
# variant deliberately omits. Nothing from it reaches the final image.
FROM dhi.io/python:3.12-dev@sha256:3b5bbcb41fec489a9ab2c5a16a8bd7cc915526e6e73954415168f9f57f3b58d7 AS builder

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
# --copies, not symlinks: the runtime stage is a different image, and a venv
# symlinked to this stage's interpreter would dangle there.
RUN python -m venv --copies /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# Writable runtime directories, created here because the runtime stage has no
# shell to mkdir with. COPY is the only way to introduce a directory there.
RUN mkdir -p /skel/logs /skel/uploads


# ---- Stage 2: runtime ----------------------------------------
FROM dhi.io/python:3.12@sha256:7c247af7f603bba8197ad5c34595066e1e6b81644c5a37b576d157979ceb4ea6 AS runtime

# No libpq layer: psycopg[binary] vendors libpq inside the wheel, and the
# hardened base has no apt to install a system copy with. Verified by importing
# psycopg in the built image — see the docker-smoke job in tests.yml.

# Copy virtual environment from builder
COPY --from=builder --chown=65532:65532 /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Copy application source
COPY --chown=65532:65532 . /app

# Runtime directories (see the builder stage for why they arrive by COPY)
COPY --from=builder --chown=65532:65532 /skel/logs /app/logs
COPY --from=builder --chown=65532:65532 /skel/uploads /app/uploads

# uid:gid of the hardened base image's own nonroot user. Numeric because the
# image carries no /etc/passwd entry this file could refer to by name.
USER 65532:65532

# ── Environment defaults (override in docker-compose / K8s) ──
# All secrets (SECRET_KEY, PG_PASSWORD, …) MUST be injected at
# runtime — never bake them into the image.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    SERVER_HOST=0.0.0.0 \
    SERVER_PORT=5000 \
    LOG_FORMAT=json

EXPOSE 5000

# Healthcheck — hits the lightweight /api/health endpoint. Exec form: with no
# shell there is no `|| exit 1`, so the check relies on urlopen raising (and
# python exiting non-zero) for any non-200.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:5000/api/health', timeout=5)"]

CMD ["python", "docker-entrypoint.py"]
