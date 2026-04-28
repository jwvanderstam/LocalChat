# CLAUDE.md

> **Starting a new session?** Run `git log --oneline -5` and `git fetch origin` first — another agent may have pushed since your last session.

---

## What This Project Is

LocalChat is a production RAG application built with Flask. Users upload documents (PDF, DOCX, TXT, MD) and chat with them using a locally-running LLM via Ollama. Documents are chunked, embedded, and stored in PostgreSQL with pgvector for hybrid semantic + BM25 search. The LLM supports tool/function-calling and optional live web search.

**Runtime deps:** PostgreSQL + pgvector, Ollama (local LLM server), Redis (optional caching).

---

## Tech Stack

| Layer | Tech |
|-------|------|
| Web framework | Flask 3 + Gunicorn |
| Database | PostgreSQL 15 + pgvector (psycopg3 pool) |
| LLM | Ollama (local); LiteLLM cloud fallback |
| Validation | Pydantic v2 |
| Auth / security | Flask-JWT-Extended, Flask-Limiter, Flask-CORS |
| Caching | Redis or in-memory fallback |
| ML / NLP | spaCy (GraphRAG), cross-encoder reranker (optional) |
| Linter | `ruff` |
| Tests | pytest + pytest-cov |

---

## Architecture

**Entry point:** `app.py` → `create_app()` in `src/app_factory.py` → `LocalChatApp` instance. Gunicorn entry: `create_gunicorn_app()`.

**Request flow:**
1. Blueprint in `src/routes/` — thin handler, no business logic
2. Pydantic model in `src/models.py` validates; `src/utils/sanitization.py` cleans
3. `src/security.py` — JWT, rate limiting, CORS
4. Service packages handle business logic
5. Chat and upload responses stream via SSE

**Packages:**

| Package | What it does |
|---------|-------------|
| `src/rag/` | Ingest pipeline, hybrid retrieval, reranker, query planning |
| `src/db/` | All SQL — mixin classes per domain |
| `src/agent/` | Model routing, parallel tool dispatch, result tracing |
| `src/tools/` | Function-calling loop, tool registry, built-ins, plugin loader |
| `src/graph/` | GraphRAG: entity extraction, 1-hop query expansion |
| `src/memory/` | Long-term memory extraction + vector retrieval |
| `src/connectors/` | Document sources: local, S3, SharePoint, OneDrive, webhook |
| `src/cache/` | Multi-backend caching with TTLs |
| `src/mcp_client.py` | MCP HTTP client + circuit breaker |
| `mcp_servers/` | Domain MCP servers (docs :5001, web :5002, connectors :5003) |

Full module index: [`.claude/rules/file-map.md`](.claude/rules/file-map.md)

**Config** (`src/config.py`): all parameters from `.env`. Key RAG defaults: `CHUNK_SIZE=1200`, `TOP_K_RESULTS=20`, `MIN_SIMILARITY_THRESHOLD=0.30`, `SEMANTIC_WEIGHT=0.70`.

---

## Coding Standards

Full rules across 4 files in `.claude/rules/` — short version here.

**Architecture** → [`.claude/rules/architecture.md`](.claude/rules/architecture.md)
- Routes are thin: parse → service → respond. No SQL, no LLM calls in blueprints.
- All SQL in `src/db/` mixins. Never elsewhere.
- All config in `src/config.py`. No `os.getenv` outside it.
- All input through a Pydantic model. Validate once at the boundary; trust internally.

**Python** → [`.claude/rules/python.md`](.claude/rules/python.md)
- Full type hints on all public functions. No untyped `Any`.
- No bare `except:`. Catch specific exceptions; log when catching `Exception`.
- Comments explain *why*. Dead code gets deleted, not commented out.

**Testing** → [`.claude/rules/testing.md`](.claude/rules/testing.md)
- New modules and non-trivial functions need unit tests. Coverage must not drop.
- Always use `create_app(testing=True)` from `src/app_factory.py`.

**File map** → [`.claude/rules/file-map.md`](.claude/rules/file-map.md)
- Full module index. Update it in the same commit when adding or removing a file.

---

## Quality Gates

Run both before every commit. Both must be clean.

```bash
ruff check src/ tests/                       # install once: pip install ruff
pytest -m "not (slow or ollama or db)"       # fast suite, no external services
```

Update [`.claude/rules/file-map.md`](.claude/rules/file-map.md) when adding or removing a module.

---

## Anti-patterns & Gotchas

- **Never put SQL outside `src/db/`** — raw queries in routes have caused subtle transaction bugs.
- **Never import `src/app.py`** — it doesn't export an app. Use `create_app()` from `src/app_factory.py`.
- **SSE generators must handle disconnect** — wrap in `try/finally`; Flask silently drops broken generators.
- **Don't mock `OllamaClient` at the wrong layer** — mock at the service boundary, not inside RAG internals.
- **Don't call `os.getenv` in business logic** — every value that skips `config.py` is invisible to config review.
- **Don't write destructive migrations** — schema changes use `ALTER TABLE IF NOT EXISTS`; `_init_schema()` owns the DDL.

---

## Commands

```bash
python app.py                               # dev server
gunicorn "app:create_gunicorn_app()"        # production
docker compose up -d                        # full stack
pytest                                      # all tests + coverage
pytest -m "not (slow or ollama or db)"     # fast only
pytest tests/unit/                          # unit only
pytest tests/integration/                   # integration only
```
