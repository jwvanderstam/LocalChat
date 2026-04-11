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
1. Ensure Ollama is running: `ollama serve` (or `docker compose up ollama`).
2. Check `OLLAMA_BASE_URL` in your `.env` — default is `http://ollama:11434` inside Docker, `http://localhost:11434` outside.
3. Inside Docker, the container name must match the service name in `docker-compose.yml` (`ollama`).

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

### App won't start: "SECRET_KEY must be at least 32 characters"

Set `SECRET_KEY` to a random 32+ character string in `.env`:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### High memory usage

**Cause:** In-memory embedding cache holding many vectors.

**Fix:** Reduce `EMBEDDING_CACHE_MAX_SIZE` (default 5000) or switch to Redis cache which uses less application memory.

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
