# Troubleshooting Guide

Common issues and their solutions when running LocalChat.

---

## Ollama

### "Connection refused" / Ollama not responding

**Symptom:** API calls return `ConnectionRefusedError` or the UI shows "Ollama unavailable".

**Check:**
```bash
curl http://localhost:11434/api/tags
```

**Fixes:**
1. Ensure Ollama is running: `docker compose up -d ollama` (the supported way), or
   `ollama serve` if you run it natively.
2. Check `OLLAMA_BASE_URL` — `http://ollama:11434` inside Docker, `http://localhost:11434`
   outside. **Inside Docker this does not come from `.env`:** `docker-compose.yml` sets it
   in the service's `environment:`, which overrides `.env`, so editing `.env` will not
   repoint a containerised app. Change it in the compose file or an override.
3. Inside Docker, the container name must match the service name in `docker-compose.yml` (`ollama`).
4. From the host, `curl` above hits the **published** port. If it refuses, either the
   service is down or the port moved — `OLLAMA_BIND_PORT` sets it (default 11434, bound to
   `127.0.0.1`). Confirm with `docker compose ps ollama`, which prints the mapping.

### Required model not found

**Symptom:** Embedding or generation fails with "model not found".

**Fix:**
```bash
ollama pull nomic-embed-text   # embedding model
ollama pull llama3.2           # or whichever LLM you configured
```

Set `OLLAMA_MODEL` and `OLLAMA_EMBED_MODEL` in `.env` to match what you pulled.

### Slow responses / GPU not used

**Symptom:** Generation is slow; `nvidia-smi` shows 0% GPU utilisation.

**Fix:**
1. Confirm Ollama sees your GPU: `ollama run llama3.2 "hello"` — watch `nvidia-smi`.
2. Set `OLLAMA_NUM_GPU=-1` in `.env` to use all layers on GPU.
3. For AMD: ensure ROCm drivers are installed; Ollama detects via `rocm-smi`.

---

## PostgreSQL / pgvector

### Connections take exactly 5 seconds, or the pool times out

**Symptom:** `PoolTimeout: couldn't get a connection after 5.00 sec` when running the
app or the `db`-marked tests from the host, while `psql` connects instantly. Each
individual connection succeeds but takes ~5 s.

**Cause:** `PG_HOST=localhost` resolves to IPv6 (`::1`) first, and `docker-compose.yml`
publishes the port on `127.0.0.1` only. Every connection waits for the IPv6 attempt to
time out before falling back to IPv4. The pool opens `DB_POOL_MIN_CONN` connections
with a 5 s budget, so it never finishes. Common on Windows.

**Fix:** use the address rather than the name.

```bash
PG_HOST=127.0.0.1
```

Nothing is wrong in the container: this affects host processes only. Inside Docker,
service names resolve directly.

### `pgvector` extension missing

**Symptom:** `ERROR: type "vector" does not exist` on startup.

**Fix:**
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```
Or use the official Docker image: `pgvector/pgvector:pg16`.  The `docker-compose.yml` already uses this image.

### Connection pool exhausted

**Symptom:** Requests hang; logs show "connection pool timeout".

**Fix:**
1. Increase `DB_POOL_MAX` in `.env` (default 10).
2. Check for long-running transactions blocking pool slots: `SELECT * FROM pg_stat_activity WHERE state = 'idle in transaction';`
3. Restart the app if connections leaked after a crash.

### Embedding dimension mismatch after model change

**Symptom:** `ERROR: different vector dimensions` when inserting chunks.

**Cause:** The `embedding` column is fixed at `vector(768)`.  Switching to a model with different output dimensions (e.g. 1024) breaks inserts.

**Fix:** Run a migration to drop and recreate the column and index:
```sql
ALTER TABLE document_chunks DROP COLUMN embedding;
ALTER TABLE document_chunks ADD COLUMN embedding vector(<new_dim>);
CREATE INDEX document_chunks_embedding_hnsw_idx
  ON document_chunks USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
```
Then re-ingest all documents so embeddings are regenerated.

### "No documents found" after upload

**Symptom:** Upload succeeds but `/api/documents/list` returns empty.

**Check:**
```bash
psql -U postgres -d rag_db -c "SELECT id, filename FROM documents;"
```

If rows exist in DB but API returns empty, check that `PG_DB` in `.env` matches the database you're looking at.

---

## Redis

### "Redis connection refused" on startup

**Symptom:** Log line `Redis unreachable for rate limiting (...), falling back to memory://`.

**This is not an error** — rate limiting falls back to in-process memory automatically.

If you want Redis-backed rate limiting in production:
1. Ensure Redis is running: `docker compose up redis` or `redis-server`.
2. Set `REDIS_HOST`, `REDIS_PORT` in `.env`.
3. The app will auto-detect Redis on startup and switch to Redis storage.

### Cache not persisting between restarts

**Symptom:** Embeddings are recomputed on every restart.

**Fix:** Ensure Redis is running and `REDIS_HOST` is set.  Without Redis, the app uses an in-memory LRU cache that is lost on restart.

---

## Authentication / JWT

### "Authentication required" on every request

**Symptom:** All admin endpoints return 401.

**Check:**
1. Is `ADMIN_PASSWORD` set in `.env`?  Without it, all logins are rejected.
2. Is `JWT_SECRET_KEY` set?  Without it, tokens cannot be signed.
3. Is `DEMO_MODE=true`?  In demo mode, auth is disabled entirely.

### JWT secret rotation

To rotate the JWT secret (invalidates all existing tokens):
1. Set a new `JWT_SECRET_KEY` value in `.env`.
2. Restart the app — all users must log in again.

---

## File Upload

### "No supported files found" (400)

**Symptom:** Upload returns 400 even for a valid PDF.

**Check:**
1. File extension must be one of: `.pdf`, `.docx`, `.txt`, `.md`, `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`.
2. File content must match its extension (magic-byte check).  A `.pdf` file that is actually HTML will be rejected.
3. File size must be under `MAX_CONTENT_LENGTH` (default 16 MB).

### PDF extraction yields no text

**Symptom:** PDF is uploaded but returns 0 chunks / empty content.

**Cause:** The PDF is image-based (scanned) or password-protected.

**Fix:** For scanned PDFs, enable OCR by installing `pytesseract` and `pdf2image` (not included by default).  For password-protected PDFs, remove the password before uploading.

---

## General

### The app serves requests but logs nothing after startup

**Symptom:** the log stops partway through boot — typically just after the Alembic
banner — yet `/api/health` returns 200 and the container is healthy. No access logs,
no errors, no warnings, for as long as the process runs. It looks like a hang; it is
not. Only logging stopped.

**Confirm it:**
```bash
docker compose logs app --no-color | tail -20      # last line is alembic, then silence
curl.exe -s -o /dev/null -w "%{http_code}" http://localhost:5000/api/health   # 200
```

**Cause:** `logging.config.fileConfig()` damages logging in **two** independent ways,
and migrations run in-process at startup (`app_bootstrap._run_alembic_migrations`),
so both fire on every boot and last the whole life of the process:

1. It defaults to `disable_existing_loggers=True`, switching off every logger not
   named in the ini. `alembic.ini` declares only `root`, `sqlalchemy`, `alembic` — so
   all of `src.*`, `uvicorn.access` and the request log are disabled outright.
2. It rewrites the **root** logger: `alembic.ini` sets `[logger_root] level = WARN`
   and installs its own handler. Application loggers carry no handlers of their own
   and inherit that level, so `ERROR` still passes and `INFO` is dropped.

**Two distinct symptoms, so match yours before assuming which half is broken:**

| What you see | Which half |
|---|---|
| Nothing at all after the alembic banner — not even errors | 1 |
| Errors and `Uvicorn running` appear, but no `src.*` `INFO` lines | 2 (uvicorn owns its handlers, so it is unaffected) |

**Fix:** `migrations/env.py` passes `disable_existing_loggers=False`, and
`_preserve_root_logging()` in `src/app_bootstrap.py` restores root's level and
handlers around the upgrade call. Both are pinned by regression tests
(`tests/unit/test_alembic_env_logging.py`, `tests/unit/test_bootstrap_logging_preserved.py`).

**Confirming which half quickly**, inside the app container:
```bash
python -c "
import logging; from logging.config import fileConfig
l = logging.getLogger('src.app_bootstrap'); logging.basicConfig(level=logging.INFO)
fileConfig('/app/alembic.ini', disable_existing_loggers=False)
print('disabled:', l.disabled, '| INFO enabled:', l.isEnabledFor(logging.INFO))"
```
`disabled: True` means half 1; `INFO enabled: False` means half 2.

**Why it matters beyond the missing lines:** anything the app logs after migrations
is discarded, including its own failures. This masked a real
`MultipleHeads` migration error that was raised and logged on every boot for days.
An app that cannot report a failure looks identical to one that has none.

### App won't start: "SECRET_KEY must be at least 32 characters"

Set `SECRET_KEY` to a random 32+ character string in `.env`:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### High memory usage

**Cause:** In-memory embedding cache holding many vectors.

**Fix:** Reduce `EMBEDDING_CACHE_MAX_SIZE` (default 5000) or switch to Redis cache which uses less application memory.

### A container restarts or disappears mid-request

**Symptom:** Ollama dies during a long generation, or the app restarts while
ingesting a large document. Logs stop abruptly with no traceback — the process
was killed, so it never got to log anything.

**Confirm it:**
```bash
docker inspect localchat-ollama-1 --format '{{.State.OOMKilled}}'   # true = hit its limit
docker stats --no-stream                                            # usage vs. ceiling
```

**Cause:** every compose service now has a memory ceiling (see OPERATIONS.md,
"Container Resource Limits"). This is deliberate — before, an over-large model
could spill to CPU and grow until it took PostgreSQL down with it. The limit
converts that into one killed container instead of a downed stack.

**Fix:** raise that service's limit in `.env` rather than removing it, e.g.
`OLLAMA_MEM_LIMIT=10g`, then `docker compose up -d`. If Ollama is the one being
killed, the underlying cause is usually a model too large for VRAM spilling to
host RAM — check `docker exec localchat-ollama-1 ollama ps` for a CPU/GPU
split, and prefer a smaller model or a lower `OLLAMA_NUM_CTX`.

**Redis is the exception:** it should evict, not die. If Redis is being
OOM-killed, `REDIS_MAXMEMORY` is set at or above `REDIS_MEM_LIMIT` — lower it
so Redis hits its own limit first.

### `ruff check` fails in CI

Run locally before pushing:
```bash
ruff check .
ruff check --fix .   # auto-fix safe violations
```

Pre-commit hooks do this automatically if installed:
```bash
pre-commit install
```
