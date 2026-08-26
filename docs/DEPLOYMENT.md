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
| `ENCRYPTION_KEY` | Fernet key encrypting OAuth tokens, messages and memories at rest. Required in production — startup aborts without it. (`TOKEN_ENCRYPTION_KEY` is accepted as a legacy alias.) |
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

### Upgrading onto the hardened image: fix the volume ownership first

The first rebuild onto the Docker Hardened Images base (#287) puts an existing deployment
into a **restart loop**:

```
PermissionError: [Errno 13] Permission denied: '/app/logs/app.log'
```

The runtime image runs as **uid 65532**, and the `Dockerfile` creates `/app/logs` and
`/app/uploads` owned by it. But both paths are **named volumes**, and a volume keeps the
ownership it was created with — uid 1000 under the pre-hardening image. The image is
correct; the volume predates it.

Docker only seeds a volume from the image on *first* use, so this cannot fix itself, and
`docker-smoke` cannot catch it — CI always starts with fresh volumes. It only ever surfaces
on a real upgrade.

Stop the app and re-own both volumes (data is untouched — this changes ownership, nothing
else). Substitute your compose project name if it is not `localchat`:

```bash
docker compose stop app
for v in localchat_app_logs localchat_app_uploads; do
  docker run --rm -v "$v":/v alpine chown -R 65532:65532 /v
done
docker compose up -d
```

A helper container is needed because the runtime image has no shell to run `chown` in.
Check the result with `docker run --rm -v localchat_app_logs:/v alpine stat -c '%u:%g' /v`
— it must report `65532:65532`.

### Upgrading past SEC-4: `ENCRYPTION_KEY` is now required

`docker compose up` will stop with `ENCRYPTION_KEY must be set` if your `.env` has no key.
That is deliberate — without one, OAuth tokens, message content and long-term memories were
being written to Postgres in plain text, signalled only by a single log line. Generate a key
and add it to `.env`:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**No data migration is needed.** Values written before you set a key are read back unchanged
— `decrypt()` returns anything it cannot decrypt as-is — while new writes are encrypted. Keep
the key: losing it makes everything written after this point unreadable.

## Rollback

```bash
git checkout <previous-tag>
docker compose up -d --build
```

Schema migrations are additive (`ADD COLUMN IF NOT EXISTS`), so an older application
generally runs against a newer schema. Alembic `downgrade` is **not** part of the supported
path — see [MIGRATIONS.md](MIGRATIONS.md).

## The application image

The `app` image is a two-stage build on **Docker Hardened Images**
(`dhi.io/python:3.12-dev` builds, `dhi.io/python:3.12` runs), both pinned by digest.
Adopted in #287; the decision and its revisit condition are [ADR-3](ADR.md).

What that means when you operate it:

| Property | Consequence |
|---|---|
| Runs as **uid 65532**, nonroot, no `/etc/passwd` entry | `docker exec ... whoami` fails; refer to the user numerically. Mounted volumes must be writable by 65532 — a volume created by an older image keeps its old ownership and puts the app in a restart loop, see [the upgrade note](#upgrading-onto-the-hardened-image-fix-the-volume-ownership-first). |
| **No shell** | `docker exec <container> sh` does not work. There is nothing to `exec` into. Debug with `--entrypoint python`, or read the logs. |
| **No package manager** | You cannot `apt-get install` a missing library into a running container. A missing native library shows up as **SIGSEGV on import** — exit 139, no traceback. |
| `CMD` and `HEALTHCHECK` are exec form | No shell means no `${VAR:-default}`. `docker-entrypoint.py` expands `SERVER_HOST`, `SERVER_PORT`, `UVICORN_WORKERS` and `UVICORN_TIMEOUT`, then `exec`s uvicorn so it stays PID 1 and still receives signals. |

**Debugging without a shell:**

```bash
# Run any Python in the image
docker compose run --rm --entrypoint python app -c "import psycopg; print(psycopg.__version__)"

# Health, as the container's own HEALTHCHECK runs it
docker compose run --rm --entrypoint python app docker-entrypoint.py --healthcheck

# Logs are the primary instrument, and LOG_FORMAT=json by default
docker compose logs -f app
```

**The CI gate.** `docker-smoke` in `.github/workflows/tests.yml` builds this image on
every PR and asserts the invariants above, then boots it against Postgres and requires
`/api/health`. It exists because the failure mode is silent: the image builds and
publishes cleanly, then the container dies on start. See LESSONS_LEARNED Ch. 17.

## Security checklist

Before exposing LocalChat beyond localhost:

| Item | Env var | Requirement |
|------|---------|-------------|
| Admin password | `ADMIN_PASSWORD` | **Must be non-empty.** Empty disables all authorisation, including admin routes. |
| JWT secret | `JWT_SECRET_KEY` | 32+ random bytes. Never the placeholder. |
| Session secret | `SECRET_KEY` | 32+ random bytes. |
| Metrics endpoints | `METRICS_TOKEN` | Set it, or `/api/metrics` and `/api/metrics.json` are public. |
| CORS origins | `CORS_ORIGINS` | Specific domains; never `*`. |
| Field encryption | `ENCRYPTION_KEY` | Required in production; `validate_secrets()` aborts the boot if it is missing or malformed. Covers OAuth tokens, messages and memories — not document text, see SECURITY.md. |
| TLS | — | Terminate at a proxy; see below. |
| Container user | — | Runs as uid 65532 by default. Do not override with `user: root` in compose. |
| Image provenance | — | Base images are digest-pinned. A bare tag makes the CVE posture unverifiable later. |

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

The override also sets `TRUSTED_PROXY_IPS`, which is what lets the app read the real
client address out of the `X-Forwarded-For` header nginx sets. Without it every request
appears to come from the nginx container and all callers share one rate-limit bucket —
see [CONFIGURATION.md](CONFIGURATION.md#rate-limiting-behind-a-reverse-proxy). If you
front the app with a different proxy, set that variable yourself.

## Connection poolers and vector search

The pool sets `hnsw.ef_search = 100` once per physical connection and every vector
query relies on it persisting. A **transaction-pooling** proxy — pgbouncer in
`transaction` mode, or a managed Postgres that fronts you with one — resets or reassigns
session state between transactions, so the setting is gone by the first real query.

Nothing fails when that happens. HNSW search runs at the server default (40 instead of
100), retrieval recall drops, and there is no error anywhere: answers just get quietly
worse. Verified against pgbouncer in transaction mode with `server_reset_query_always=1`,
where every query saw 40 while the application reported itself healthy.

The app now reads the setting back in a separate transaction at connection time and logs
one warning if it did not survive:

```
hnsw.ef_search did not survive a transaction boundary (set to 100, reads back as '40')
```

**If you see that line**, put the app in front of the database directly, or switch the
pooler to `session` mode. The compose stack connects straight to `db`, so it does not
apply there — it applies to managed Postgres, which is why it matters for the
[Scaleway target](localchat_scaleway_deployment_plan.md).

**One thing this check cannot see.** pgbouncer in transaction mode does not reset by
default; it *leaks* session state between clients instead. The setting then survives on
whichever server connection happens to carry it and is absent on the others, so a
read-back at connection time can pass by luck while later queries still degrade. The
warning is a positive signal, not a clean bill of health. Behind any pooler, confirm with
`SHOW hnsw.ef_search;` on a live connection under load.

## Uninstall

```bash
docker compose down            # keeps volumes
docker compose down -v         # deletes Postgres data, uploads and pulled models
```
