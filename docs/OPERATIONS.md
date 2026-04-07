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

## Ollama Model Management

Ollama model weights are stored inside the `ollama` container (or a named volume if you configured one).  They are large (2–30 GB each) and not backed up by the above procedures.

Re-pull models after a fresh deploy:

```bash
docker compose exec ollama ollama pull nomic-embed-text
docker compose exec ollama ollama pull llama3.2   # or your configured model
```

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
