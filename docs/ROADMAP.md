# LocalChat Roadmap

LocalChat exists to be the gold standard for local, privacy-preserving knowledge management — an agentic RAG system that learns from every interaction and improves its own retrieval quality over time.

---

## How to read this roadmap

Each planned item is tagged as **Functional** (user-visible behaviour) and/or **Technical** (stack, architecture, infrastructure). Items that affect both carry an explicit cross-domain impact note.

**Standing rule:** every proposed change to LocalChat — functional or technical — must be evaluated for cross-domain consequences before being accepted into the roadmap. This document is the record of those evaluations.

---

## What is in v1.0

| Capability | Details |
|---|---|
| RAG pipeline | Hybrid semantic + BM25 search, adaptive chunking, answer attribution |
| Vector store | PostgreSQL + pgvector (HNSW indexing) |
| LLM integration | Ollama with function-calling, multi-model routing, cloud fallback |
| Agentic layer | Aggregator agent, query planner, GraphRAG expansion, long-term memory |
| MCP architecture | Three independent MCP servers (local-docs, web-search, cloud-connectors) |
| Connectors | Local folder, S3/R2, SharePoint, OneDrive, webhook — live delta sync |
| Multi-user | JWT auth, workspace isolation, RBAC (viewer/editor/owner), Microsoft OAuth2 |
| Reranker | Cross-encoder re-ranking with optional weekly fine-tune on user feedback |
| Observability | Prometheus metrics, GPU monitoring, admin dashboard, Grafana dashboard |
| Deployment | Docker Compose, Helm chart (PostgreSQL + Redis StatefulSets, MCP servers) |
| Excel ingest | Per-sheet markdown-table serialisation via openpyxl; empty sheets skipped |
| Cloud fallback gate | `CLOUD_FALLBACK_ENABLED` defaults to `false`; explicit opt-in required before any query reaches a cloud endpoint |

---

## Shipped

### v1.1 — Quality and Reach ✓
**Functional**
- **Structured document ingest** — layout-aware PDF parsing via pdfplumber; heading-hierarchy preservation in DOCX; Excel per-sheet ingestion via openpyxl.
- Multi-language document support (language detection at ingest; CJK character-count chunking)
- Confluence and Google Drive connectors
- Answer confidence scores surfaced in `done` SSE event
- Scheduled document re-ingestion for stale sources (`REINGEST_ENABLED`)

**Technical**
- **Redis / in-memory fallback** — `REDIS_ENABLED=true` with no Redis running now raises at startup (no silent fallback). `REDIS_ENABLED=false` uses MemoryCache exclusively.
- **Worker concurrency** — resolved permanently by the FastAPI + Uvicorn migration below.

### v1.2 — Collaboration ✓
**Functional**
- Shared workspaces with role enforcement (owner / editor / viewer)
- Annotation layer: highlight and annotate source chunks (`src/db/annotations.py`, `src/routes_fastapi/annotation_routes.py`)
- Export: structured answers with citations to PDF/DOCX (`src/utils/export.py`)

### v1.3 — Intelligence ✓
**Functional**
- Automatic ontology extraction per workspace (`GET /api/workspaces/<id>/ontology`)
- Active learning loop: `suggest_documents()` in `src/rag/active_learning.py` surfaces knowledge gaps
- Cross-workspace retrieval: `retrieve_context()` accepts multiple workspace IDs

**Technical**
- **Graph store** — `GraphStore` ABC with `PostgresGraphStore` (default) and `KuzuGraphStore` (optional, Cypher-compatible). Controlled by `GRAPH_BACKEND` env var. See `src/graph/store.py`.

### v1.4 — Security ✓
**Functional / Technical**
- **Encryption at rest** — `src/utils/encryption.py` provides canonical Fernet `encrypt()`/`decrypt()`. Sensitive text columns (document content, messages, memories, OAuth tokens) are encrypted at the DB layer.
- **FastAPI + Uvicorn migration** — all 13 route modules ported to `src/routes_fastapi/`. JWT via python-jose, rate limiting via slowapi, CORS via Starlette CORSMiddleware. Entry point: `create_uvicorn_app()` in `app.py`. Flask retained only for MCP domain servers.

### v1.5 — Chat UX and Document Sources (Planned)
**Functional**
- **Drag-and-drop upload** — drop files directly onto the chat interface; no separate upload screen required (backend `/api/documents/upload` already supports multipart; frontend work only)
- **Connect information stores** — link OneDrive, SharePoint, S3, or other configured connectors directly from the chat UI (backends already exist in `src/connectors/`)
- **Multi-source selection** — activate and deactivate multiple document sources per conversation; retrieval scoped to the active selection

---

## Tech Stack: Current

| Layer | Current | Notes |
|-------|---------|-------|
| Web framework | FastAPI + Uvicorn | Migrated from Flask 3 + Gunicorn in v1.4 |
| Caching / rate limit backend | Explicit Redis or in-memory, no silent fallback | Resolved in v1.1 |
| Graph store | `PostgresGraphStore` (default) or `KuzuGraphStore` | Kuzu opt-in via `GRAPH_BACKEND=kuzu` |

---

## Improvement Recommendations Audit

*Code review findings — May 2026*

The following three recommendations are drawn from a full review of the LocalChat repository (646 commits as of review date). Two are correctness/security concerns that currently pass silently; one addresses the largest accumulation of technical debt in the codebase.

| # | Recommendation | Type | Effort | Impact | Status |
|---|---|---|---|---|---|
| 1 | Startup secret validation | Security | Low (1-2 hours) | High — eliminates JWT forgery risk | Done |
| 2 | Idempotent admin user seeding | Correctness | Low (1 hour) | High — fixes production startup race | Done |
| 3 | Decompose app_factory.py | Architecture | Medium (half day) | High — largest maintainability gain available | Done |

### 1 — Startup Secret Validation ✓

config.py loads SECRET_KEY, JWT_SECRET_KEY, and ADMIN_PASSWORD from environment variables. Without validation, a deployment with a weak or placeholder key would start cleanly and serve traffic with forgeable JWT tokens.

**Shipped:** `validate_secrets()` in `src/config.py` enforces minimum key length (32 chars), rejects known placeholders (`changeme`, `secret`, `dev`, etc.), and calls `sys.exit(1)` in production mode on any violation. Called as the first step in `create_app()`.

### 2 — Idempotent Admin User Seeding ✓

`_seed_admin_user()` in `app_factory.py` previously used a check-then-insert pattern. Gunicorn starts multiple workers concurrently; two workers could both read `count_users() == 0` before either committed, resulting in a duplicate row or unhandled startup exception.

**Shipped:** `_seed_admin_user()` now uses a PostgreSQL upsert (`INSERT ... ON CONFLICT (username) DO NOTHING`), making the operation atomic and safe to call from any number of concurrent workers.

### 3 — Decompose app_factory.py

At 618 lines, `app_factory.py` conflates two concerns: wiring (Flask app, blueprints, security middleware) and bootstrapping (Ollama check, DB init, admin seeding, embedding warmup, plugin loading, connector startup, reranker scheduler). The `testing` flag threads through every private function to suppress bootstrapping side-effects.

**Shipped:** split into `src/app_factory.py` (pure wiring, safe to call in tests with zero mocking) and `src/app_bootstrap.py` (all startup I/O, ~300 lines). The `testing` flag is gone; `bootstrap_app(app)` is called only from the production entry point.

---

## Design Principles

1. **Local first** — no data leaves the machine without explicit configuration
2. **Graceful degradation** — every optional dependency (Redis, reranker, cloud fallback) degrades gracefully with explicit operator visibility
3. **Composable** — each MCP server is independently deployable; new connectors require zero changes to core retrieval
4. **Observable by default** — every request carries a trace ID; all slow paths are logged and metered
5. **Test everything** — no feature ships without unit tests; no integration path ships without an integration test
6. **Cross-domain awareness** — every roadmap change is evaluated for functional and technical consequences before acceptance
