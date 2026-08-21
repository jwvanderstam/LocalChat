# Operations Guide

Backup, restore, and maintenance procedures for a production LocalChat deployment.

---

## Plugin Security

LocalChat supports custom tool plugins loaded from the `plugins/` directory at startup
(`src/tools/plugin_loader.py`). Plugins are plain `.py` files imported with full Python
interpreter access — they can import any module, open files, make network requests, or
modify application state.

**Only load plugins from trusted sources.** There is no sandboxing, signature
verification, or capability restriction. Treat a plugin file with the same level of
trust as any other Python source code running in your production environment.

Operational checklist before adding a plugin:
- Review the source code manually before deploying.
- Run it in a staging environment first.
- Restrict filesystem permissions on the `plugins/` directory so only authorised
  operators can write to it.

---

## PostgreSQL Backup

### Full database dump

```bash
docker compose exec db pg_dump \
  -U postgres \
  -d rag_db \
  --no-password \
  -F c \
  -f /tmp/rag_db_$(date +%Y%m%d_%H%M%S).dump

# Copy the dump out of the container
docker compose cp db:/tmp/rag_db_*.dump ./backups/
```

`-F c` produces a custom-format dump (compressed, supports parallel restore).  Use `-F p` for a plain SQL file if you need to inspect or edit it.

### pgvector-safe restore

The `vector` extension must exist in the target database before restoring, or pg_restore will fail on the `embedding` column.

```bash
# 1. Create the target database and install the extension
docker compose exec db psql -U postgres -c "CREATE DATABASE rag_db_restore;"
docker compose exec db psql -U postgres -d rag_db_restore \
  -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 2. Restore
docker compose exec db pg_restore \
  -U postgres \
  -d rag_db_restore \
  --no-password \
  /tmp/rag_db_20260101_120000.dump
```

### Scheduled backups (cron example)

```cron
# Daily at 02:00, keep 7 days
0 2 * * * cd /opt/localchat && \
  docker compose exec -T db pg_dump -U postgres -d rag_db -F c \
  > backups/rag_db_$(date +\%Y\%m\%d).dump && \
  find backups/ -name "rag_db_*.dump" -mtime +7 -delete
```

---

## Redis Persistence

Redis is used for rate-limiting counters and the embedding/query cache.  By default the Docker image runs with no persistence — data is lost on container restart.

### Recommended: RDB snapshots

Add to `docker-compose.yml` under the `redis` service:

```yaml
redis:
  command: redis-server --save 60 1 --loglevel warning
  volumes:
    - redis_data:/data
```

This saves a snapshot every 60 seconds if at least 1 key changed.

### AOF (append-only file) for stricter durability

```yaml
redis:
  command: redis-server --appendonly yes --appendfsync everysec
  volumes:
    - redis_data:/data
```

AOF with `everysec` loses at most 1 second of writes on crash.

### When Redis data loss is acceptable

The embedding and query caches are warm-caches only — losing them causes a short performance dip (cache misses regenerated on next request) but no data loss.  Rate-limit counters reset on Redis restart, which briefly allows extra requests.  For most self-hosted deployments, RDB snapshots are sufficient.

---

## Docker Volume Backup

LocalChat uses named volumes for persistent data.  Back them up by streaming the volume contents through `tar`.

```bash
# Back up PostgreSQL data volume
docker run --rm \
  -v localchat_pgdata:/source:ro \
  -v $(pwd)/backups:/dest \
  busybox tar czf /dest/pgdata_$(date +%Y%m%d).tar.gz -C /source .

# Back up Redis data volume
docker run --rm \
  -v localchat_redis_data:/source:ro \
  -v $(pwd)/backups:/dest \
  busybox tar czf /dest/redis_$(date +%Y%m%d).tar.gz -C /source .
```

To restore, reverse the process into a fresh volume before starting the stack:

```bash
docker volume create localchat_pgdata
docker run --rm \
  -v localchat_pgdata:/dest \
  -v $(pwd)/backups:/source:ro \
  busybox tar xzf /source/pgdata_20260101.tar.gz -C /dest
```

> **Note:** Always stop the stack (`docker compose down`) before restoring volumes to avoid corruption.

---

## Logs and Retention

**Logs are not backed up, and deliberately so.** They are diagnostic output, not
state — nothing reconstructs from them, and they are the one volume whose loss costs
you nothing but hindsight. `app_logs` is therefore absent from the backup recipes
above. What matters instead is knowing *how far back you can look*.

### Reading the log without a shell

**Settings → Logs** (admin only) tails the log file in the browser, with a level filter
and substring search. It reads the `file` sink, so it shows nothing when `file` is absent
from `LOG_SINKS` — and says so rather than rendering an empty table.

It reads the file rather than `docker logs` for the same two reasons the file sink exists:
the file survives container recreation, and it holds DEBUG where the console holds INFO.
The runtime image has no shell, so this is also the only way to read the log from inside a
running container without attaching a helper container.

`LOG_FORMAT=json` makes the viewer meaningfully better — the fields land in their own
columns and the level filter is a real filter. Text lines still render, with the level
picked out of the line, so a file holding both formats is fine.

### How far back your logs go

Retention is not a fixed number of days — it is a division:

```
window = LOG_MAX_BYTES * (1 + LOG_BACKUP_COUNT) / log volume per day
```

The ceiling is 20 MB by default. Log volume, however, is dominated by the log level,
which follows `APP_ENV`:

| `APP_ENV` | Level | Typical volume | Window at 20 MB |
|---|---|---|---|
| `production` | INFO | ~3 MB/day | about a week |
| anything else | DEBUG | ~30 MB/day | **under a day** |

That tenfold gap is third-party DEBUG chatter, not application detail — the `markdown`
library alone emits ~1275 records per boot. A stack left on `APP_ENV=development`
therefore has a log window measured in hours, and its operator usually does not know it.

Measure your own rate rather than trusting the table — the sizes and timestamps give it
to you directly:

```bash
docker run --rm -v localchat_app_logs:/v alpine   sh -c 'cd /v && for f in app.log*; do printf "%s %s %s
" "$f" "$(stat -c %s $f)" "$(stat -c %y $f)"; done'
```

One full file divided by the gap between its timestamp and the next one is your daily rate.

### Widening the window

In order of preference:

1. **Check `APP_ENV=production`.** Cutting DEBUG buys roughly a tenfold window for free,
   and it also turns on the startup secret validation, which is inert otherwise.
2. **Ship to a collector.** Add `syslog` to `LOG_SINKS` and history lives on the SIEM,
   bounded by its retention rather than yours — see
   [CONFIGURATION.md](CONFIGURATION.md#logging-sinks-rotation-and-shipping-to-a-siem).
3. **Raise the ceiling.** `LOG_MAX_BYTES` and `LOG_BACKUP_COUNT`. Do this last: the
   ceiling is a disk-exhaustion control, since request volume drives log volume and an
   attacker controls request volume.

### Disk footprint

Two independent caps, one per sink:

| Sink | Where | Cap | Set by |
|---|---|---|---|
| `file` | `app_logs` volume | 20 MB | `LOG_MAX_BYTES` × (1 + `LOG_BACKUP_COUNT`) |
| `console` | Docker's json-file driver | 30 MB | `logging.options` on the `app` service in `docker-compose.yml` |

Both are bounded on purpose. Removing either limit reintroduces a way to fill the disk
by generating requests.

### Grabbing logs during an incident

The file sink survives container recreation; `docker logs` does not — `docker compose up -d`
starts a new container and the previous one's output goes with it. Copy the file out before
rebuilding:

```bash
docker run --rm -v localchat_app_logs:/v -v "$(pwd)":/dest alpine   tar czf /dest/logs_$(date +%Y%m%d-%H%M).tar.gz -C /v .
```

---

## Ollama Model Management

Ollama model weights are stored inside the `ollama` container (or a named volume if you configured one).  They are large (2–30 GB each) and not backed up by the above procedures.

Re-pull models after a fresh deploy:

```bash
docker compose exec ollama ollama pull nomic-embed-text
docker compose exec ollama ollama pull llama3.2   # or your configured model
```

---

## Container Resource Limits

Every `docker-compose.yml` service declares a memory and CPU ceiling, so no
single container can exhaust the host. Kubernetes deployments get the
equivalent from your orchestrator's own resource settings and ignore these.

All values are `.env` overrides (see `.env.example`), sized by default for a
~16 GB host:

| Service | Memory | CPUs |
|---|---|---|
| `ollama` | `8g` | 12 |
| `app` | `3g` | 8 |
| `db` | `2g` | 4 |
| `redis` | `512m` | 2 |
| `mcp-*` | `512m` | 2 |

Limits are ceilings, not allocations — a container only uses what it needs.

**There is no way to guarantee a container its memory.** Docker's
`--memory-reservation` (Compose's `reservations.memory`) is a *soft limit*,
not a floor: under host pressure the kernel reclaims the container **toward**
that value, which would make PostgreSQL a likelier victim rather than a
protected one. What keeps the database alive is the ceiling on everything that
would otherwise crowd it out — `ollama` above all.

### Two things that are easy to get wrong

**A memory limit turns "slow" into "killed".** Without one, a model too large
for VRAM spills to CPU and runs slowly. With one, the OOM killer stops it
mid-generation instead. That is the intended trade — it protects PostgreSQL —
but set the limit generously so only genuine runaway reaches it.

**`OLLAMA_MEM_LIMIT` does not cap VRAM.** It caps host RAM. VRAM residency is
governed by `OLLAMA_MAX_LOADED_MODELS` and `OLLAMA_KEEP_ALIVE`, and the
per-model fit check lives in the application (`load_model_guard`). The three
protect against different failures; none substitutes for another.

### Redis evicts rather than dying

`REDIS_MAXMEMORY` (default `384mb`) sits deliberately below `REDIS_MEM_LIMIT`
(`512m`). Redis reaching its own limit evicts its coldest keys under
`allkeys-lru` and keeps serving; Redis reaching the *container* limit is
OOM-killed. Keep that ordering when tuning — this is a cache, so eviction is
the correct failure mode.

### Checking and tuning

```bash
# What the limits actually render to (catches .env typos)
docker compose config | grep -A4 'resources:'

# Live usage against those ceilings
docker stats --no-stream
```

If a container is repeatedly OOM-killed (`docker inspect <name> --format
'{{.State.OOMKilled}}'` returns `true`), raise that service's limit rather
than removing it — an unbounded container is what this section exists to
prevent.

On a smaller host, lower `OLLAMA_MEM_LIMIT` first: it is by far the largest
single ceiling.

---

## Routine Maintenance

### Vacuum and analyse PostgreSQL

Run periodically to reclaim space after document deletions:

```bash
docker compose exec db psql -U postgres -d rag_db \
  -c "VACUUM ANALYSE document_chunks;"
```

The HNSW index does not support online rebuilds — it is rebuilt automatically when the table is vacuumed after large bulk deletes.

### Check index health

```sql
SELECT indexname, idx_scan, idx_tup_read, idx_tup_fetch
FROM pg_stat_user_indexes
WHERE relname = 'document_chunks';
```

Low `idx_scan` on `document_chunks_embedding_hnsw_idx` after many queries suggests the planner is not using the index — check `hnsw.ef_search` and similarity threshold configuration.

### Rotate JWT secret

1. Set a new value for `JWT_SECRET_KEY` in `.env`.
2. Restart the app — all existing tokens are immediately invalidated.
3. Users must log in again.

No database migration is needed; tokens are stateless.
