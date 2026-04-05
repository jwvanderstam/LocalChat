# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current Development Status

> **For any agent or coder starting a new session — read this first.**

Always run `git log --oneline -5` and `git fetch origin` before starting work.  Another agent may have pushed changes since your last session.  The canonical task list lives in [`docs/ROADMAP.md`](docs/ROADMAP.md).

**As of 2026-04-06 (commit feat: 4.5 dedup + 5.3 ops guide):**

| Phase | Status | Remaining work |
|-------|--------|---------------|
| 1 — Code Quality & Security | ✅ 100% | Complete |
| 2 — Test Coverage | ✅ 95% | 2.5 L3 cache audit (`src/cache/backends/database_cache.py`) — low priority |
| 3 — Documentation | ✅ 100% | Complete |
| 4 — Feature Evolution | ✅ 95% | 4.1 Pyright strict mode only |
| 5 — Observability | ✅ 100% | Complete |

**Recently completed:**
- **4.5** — Document re-ingestion dedup: SHA-256 hash stored in `documents.content_hash`; same hash → skip; different hash → replace (delete + re-ingest); `db.delete_document()` added; 8 unit tests.
- **5.3** — `docs/OPERATIONS.md`: pg_dump, pgvector restore, Redis persistence, Docker volume backup, VACUUM, JWT rotation.
- **4.2–4.4, 5.1–5.2** — Done by Copilot (multi-doc context, export, provenance, JSON logs, Grafana dashboard).

**Next priority:** Phase 4.1 Pyright strict — start with `src/db/` and `src/models.py`.

---

## What This Project Is

LocalChat is a local RAG (Retrieval-Augmented Generation) application built with Flask. Users upload documents (PDF, DOCX, TXT, MD), then chat with them using a locally-running LLM via Ollama. Documents are chunked, embedded, and stored in PostgreSQL with pgvector for hybrid semantic + BM25 search. The LLM can also call registered tools (function-calling) and perform live web search.

**Runtime dependencies:** PostgreSQL with pgvector, Ollama (local LLM server), Redis (optional caching).

## Commands

```bash
# Run the application (dev)
python app.py

# Run the application (production)
gunicorn "app:create_gunicorn_app()"

# Docker
docker compose up -d

# Run all tests (with coverage)
pytest

# Fast tests only — no DB, Ollama, or slow tests
pytest -m "not (slow or ollama or db)"

# Unit or integration tests only
pytest tests/unit/
pytest tests/integration/

# Single test file or function
pytest tests/unit/test_rag_comprehensive.py
pytest tests/unit/test_app_factory.py::TestAppCreation::test_create_app_returns_flask_app
```

## Architecture

**Entry point:** root `app.py` → `create_app()` in `src/app_factory.py`. The factory initializes all services, registers blueprints, and returns a `LocalChatApp` instance. The WSGI entry point for gunicorn is `create_gunicorn_app()` in root `app.py`.

**Request flow:**
1. `src/routes/` blueprints handle routing (api, documents, models, memory, admin, web)
2. Pydantic models in `src/models.py` validate input; `src/utils/sanitization.py` cleans it
3. `src/security.py` enforces JWT auth, rate limiting, CORS
4. Business logic in the service packages below
5. Responses stream via SSE for chat and document upload

**Key packages:**

`src/rag/` — The RAG pipeline:
- `loaders.py` — multi-format document loading
- `chunking.py` — intelligent overlapping chunking, preserves table structure
- `retrieval.py` — hybrid search: semantic (pgvector cosine) + BM25 keyword
- `scoring.py` — BM25 implementation
- `cache.py` — embedding vector cache
- `web_search.py` — optional DuckDuckGo integration
- `processor.py` — orchestrates ingest: load → chunk → embed → store

`src/db/` — PostgreSQL/pgvector layer:
- `connection.py` — psycopg3 connection pool, pgvector HNSW index setup
- `documents.py` — document/chunk CRUD and vector similarity search
- `conversations.py` — persistent multi-turn conversation history

`src/tools/` — LLM function-calling system:
- `registry.py` — tool registration with JSON schemas
- `executor.py` — manages the Ollama tool-call loop (multi-turn until final response)
- `builtin.py` — built-in tools: document search, calculator, datetime
- `plugin_loader.py` — loads `.py` tool plugins from the `plugins/` directory at startup

`src/cache/` — multi-backend caching (Redis or in-memory) with TTLs for embeddings and query results.

`src/gpu_monitor.py` — standalone `GpuMonitor` class. Detects NVIDIA GPUs via `nvidia-smi` and AMD via `rocm-smi`, TTL-caches results (30 s). Injected into `OllamaClient` via `self._gpu_monitor`; not coupled to the HTTP client.

**Config** (`src/config.py`): all parameters loaded from `.env`. Key RAG defaults: `CHUNK_SIZE=1200`, `TOP_K_RESULTS=20`, `MIN_SIMILARITY_THRESHOLD=0.30`, `SEMANTIC_WEIGHT=0.70`, `STREAM_RESPONSES=True`.

## Test Structure

Tests use pytest with markers defined in `pytest.ini`:
- `unit` — fast, isolated, no external services
- `integration` — requires running services
- `db` — requires PostgreSQL
- `ollama` — requires Ollama
- `slow`, `rag`, `api`, `validation`, `sanitization`, `exceptions`

Shared fixtures are in `tests/conftest.py`. Test utilities in `tests/utils/`. All tests use `src/app_factory.py`'s `create_app(testing=True)` — never import from `src/app.py` directly (that file doesn't exist; the factory is the only app creation path).

## Key Files

| File | Role |
|------|------|
| `app.py` | Entry point; `main()` for dev, `create_gunicorn_app()` for prod |
| `src/app_factory.py` | `create_app()` — Flask factory, wires everything together |
| `src/config.py` | All configuration constants, loads `.env` |
| `src/rag/processor.py` | Document ingestion orchestration |
| `src/rag/retrieval.py` | Hybrid search (semantic + BM25); `retrieve_context(filename_filter=)` |
| `src/db/connection.py` | PostgreSQL connection pool and schema init (incl. additive migrations) |
| `src/db/documents.py` | Document/chunk CRUD; `search_similar_chunks(filename_filter=)` |
| `src/db/conversations.py` | Persistent conversation history; `get/set_conversation_document_filter` |
| `src/tools/executor.py` | LLM tool-call loop |
| `src/routes/api_routes.py` | Chat (SSE), status; sets `g.model`, `g.chunks_retrieved`; emits `sources` in `done` |
| `src/routes/memory_routes.py` | Conversation CRUD, export, document-filter endpoints |
| `src/routes/` | All other blueprint handlers |
| `src/utils/logging_config.py` | `JsonFormatter` + `RequestIdFilter`; `LOG_FORMAT=json` for structured output |
| `src/utils/request_id.py` | X-Request-ID middleware; per-request access log via `_access_logger` |
| `src/security.py` | JWT, rate limiting, CORS |
| `src/models.py` | Pydantic request/response models |
| `tests/conftest.py` | Shared pytest fixtures |
| `docker-compose.yml` | Full stack: app + PostgreSQL + Redis + Ollama |
| `docs/grafana-dashboard.json` | Importable Grafana dashboard (uid `localchat-rag-v1`, 7 panels) |

> **Maintenance rule:** When adding or removing a module, update the Key Files table above in the same PR. This is a checked item in PR review, not a best-effort afterthought.
