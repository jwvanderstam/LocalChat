# LocalChat — Deployment (Docker Compose)

> **Single-node by design.** LocalChat runs as one process for a small team
> (≤ 25 users) — see [ADR-1](ADR.md). `AppState`, metrics, the migration runner,
> connector polling and the reranker's scheduler are all in-process state with no
> cross-instance coordination. Running a second instance does not fail loudly; the
> two silently disagree about the active model, rate limits and cached state.
>
> The Helm chart was removed in PG-0 (2026-08-05). It implied a multi-replica
> topology the code does not support, and no Kubernetes deployment existed. It is
> one `git revert` away if that changes — but reinstating it means superseding
> ADR-1 first, not just restoring the files.

## Prerequisites

- Docker Engine 24+ with the Compose plugin
- An NVIDIA GPU with the Container Toolkit for GPU inference (optional — `GPU_BACKEND=cpu` works)
- ~20 GB disk for models, images and Postgres data

## Quick start

```bash
cp .env.example .env         # then edit — see "Required secrets" below
docker compose up -d
docker compose logs -f app   # watch migrations apply and the app come up
```

A healthy boot ends with:

```
INFO - src.app_bootstrap - Alembic migrations applied (or already at head)
INFO - src.app_bootstrap - Application bootstrap complete
INFO:     Uvicorn running on http://0.0.0.0:5000
```

If migrations fail the app **still starts** — `_run_alembic_migrations()` catches and
logs the error rather than aborting. Check for `Alembic migration failed` before
assuming a green container means a migrated schema.

## Services

| Service | Purpose | Exposed |
|---|---|---|
| `app` | FastAPI + Uvicorn | `127.0.0.1:5000` |
| `db` | PostgreSQL 16 + pgvector | `127.0.0.1:5432` |
| `redis` | Cache and rate-limit backend | internal |
| `ollama` | Local LLM inference | `127.0.0.1:11434` (`OLLAMA_BIND_PORT`) |

The three MCP servers are behind a profile: `docker compose --profile mcp up -d`.

Ports bind to `127.0.0.1` deliberately. Put a TLS proxy in front rather than binding
`0.0.0.0` — see [TLS](#tls) below.

### How services find each other

Inside the stack they use **service names on the `backend` network**, not published ports:
the app reaches Ollama at `http://ollama:11434`, Postgres at `db`, Redis at `redis`.
`docker-compose.yml` sets those in each service's `environment:` block.

**Compose's `environment:` overrides `.env`.** `OLLAMA_BASE_URL`, `PG_HOST` and
`REDIS_HOST` in a `.env` file therefore have no effect on a containerised app — a change
there is silently ignored rather than rejected. To repoint a service, edit
`docker-compose.yml` or supply an override file.

The published ports exist for **the host**, not for the containers:

| Variable | Default | Moves |
|---|---|---|
| `BIND_HOST` | `127.0.0.1` | every published port |
| `BIND_PORT` | `5000` | the app |
| `OLLAMA_BIND_PORT` | `11434` | Ollama |

`ollama` is published so the host-run dev path (`python app.py` against
`docker compose up -d db redis ollama`) can reach it, the same reason `db` is. A fork that
already runs Ollama natively on 11434 sets `OLLAMA_BIND_PORT` rather than editing compose.
The containerised app needs neither the `db` nor the `ollama` port published — unpublish
both and the stack still works; only the host-run path breaks. The app's own port is
different: that is how you reach the UI.

## Required secrets

Set these in `.env` before first start.

| Key | Purpose |
|-----|---------|
| `SECRET_KEY` | Session signing key — 32+ random bytes |
| `JWT_SECRET_KEY` | JWT signing key — 32+ random bytes |
| `ADMIN_PASSWORD` | Initial admin password. **Leaving it empty disables authorisation entirely** (`_is_rbac_bypassed`), so set it before exposing the app to anything. |
| `PG_PASSWORD` | PostgreSQL password |
| `TOKEN_ENCRYPTION_KEY` | Fernet key for OAuth token encryption at rest |
| `MICROSOFT_CLIENT_ID` / `_SECRET` | Azure AD app, only for the SharePoint/OneDrive connectors |
| `METRICS_TOKEN` | Bearer token for the metrics endpoints. **Empty means they are public.** |

Generate keys:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Beyond a single trusted host, keep `.env` out of the image and inject secrets from your
platform's secret store instead.

## Resource limits

Every service carries `deploy.resources.limits` (memory and CPU) in `docker-compose.yml`,
overridable per environment: `OLLAMA_MEM_LIMIT`, `DB_MEM_LIMIT`, `APP_CPU_LIMIT` and so
on. They exist so one runaway model cannot take PostgreSQL down with it. Raise a limit
rather than removing it — see [OPERATIONS.md](OPERATIONS.md) and the OOM entry in
[TROUBLESHOOTING.md](TROUBLESHOOTING.md).

Memory *reservations* are deliberately not set: a reservation is a soft floor the kernel
reclaims toward, which would make a service a likelier eviction victim, not a protected one.

## Upgrade

```bash
git pull
docker compose up -d --build
docker compose logs -f app     # confirm migrations applied
```

Migrations run automatically at startup. Back up first — see [OPERATIONS.md](OPERATIONS.md).

## Rollback

```bash
git checkout <previous-tag>
docker compose up -d --build
```

Schema migrations are additive (`ADD COLUMN IF NOT EXISTS`), so an older application
generally runs against a newer schema. Alembic `downgrade` is **not** part of the supported
path — see [MIGRATIONS.md](MIGRATIONS.md).

## Security checklist

Before exposing LocalChat beyond localhost:

| Item | Env var | Requirement |
|------|---------|-------------|
| Admin password | `ADMIN_PASSWORD` | **Must be non-empty.** Empty disables all authorisation, including admin routes. |
| JWT secret | `JWT_SECRET_KEY` | 32+ random bytes. Never the placeholder. |
| Session secret | `SECRET_KEY` | 32+ random bytes. |
| Metrics endpoints | `METRICS_TOKEN` | Set it, or `/api/metrics` and `/api/metrics.json` are public. |
| CORS origins | `CORS_ORIGINS` | Specific domains; never `*`. |
| Token encryption | `TOKEN_ENCRYPTION_KEY` | Required for the OAuth connectors. |
| TLS | — | Terminate at a proxy; see below. |

Which routes require which role is documented in [PERMISSIONS.md](PERMISSIONS.md).

## TLS

Add an Nginx termination proxy with the override file:

```bash
docker compose -f docker-compose.yml -f docker-compose.nginx.yml up -d
```

The override adds an `nginx:alpine` service that listens on 443, terminates TLS and
proxies to the app on port 5000. Mount your certificate and key into the container and
replace the `server_name`, `ssl_certificate` and `ssl_certificate_key` placeholders in
`nginx/nginx.conf`.

## Uninstall

```bash
docker compose down            # keeps volumes
docker compose down -v         # deletes Postgres data, uploads and pulled models
```
