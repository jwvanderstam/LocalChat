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

## Planned

### v1.1 — Quality and Reach
**Functional**
- **Structured document ingest** *(medium priority)* — pdfplumber and DOCX table extraction already ship. Remaining gap: layout-aware PDF parsing for column-heavy and multi-column documents (pymupdf4llm or docling); better heading-hierarchy preservation in DOCX.
- Multi-language document support
- Confluence and Google Drive connectors
- Answer confidence scores surfaced in the UI
- Scheduled document re-ingestion for stale sources

**Technical**
- **Resolve Redis / in-memory fallback ambiguity** *(high priority)* — `REDIS_ENABLED` controls the primary path, but `cache/__init__.py create_cache_backend()` still silently falls back to `MemoryCache` on any Redis failure, and Flask-Limiter falls back to `memory://`. This means rate limit state is per-worker, does not survive restarts, and is inconsistent across Gunicorn workers. Decision required: commit to Redis as a hard dependency with a startup health check and no silent fallback, or commit to in-memory only and remove Redis from the stack. Do not maintain both paths silently. Affects every component that touches caching or rate limiting.
- **Gunicorn worker concurrency** — `sync` workers block for the full duration of a streaming SSE response (LLM inference), so two concurrent chat streams exhaust all workers and queue every other request. Fix: switch to `gthread` worker class with `--threads 4` (8 concurrent slots vs. 2, no extra dependencies). Change is docker-compose and Helm only — no application code required. Resolved permanently by the FastAPI + Uvicorn migration (v1.4).

### v1.2 — Collaboration
**Functional**
- Shared workspaces with real-time presence
- Annotation layer: highlight source chunks directly in documents
- Export: structured answers with citations to PDF/DOCX

### v1.3 — Intelligence
**Functional**
- Automatic ontology extraction per workspace (GraphRAG expansion)
- Active learning loop: model suggests which documents to ingest next
- Cross-workspace retrieval for shared knowledge bases

**Technical**
- **Graph store for real GraphRAG** — spaCy handles entity extraction and entities/relations are persisted in flat PostgreSQL tables (`entities`, `entity_relations`). However, only 1-hop co-occurrence lookups are supported; there is no graph traversal, no depth control, and no Cypher queries. True GraphRAG requires a persistent graph store. Recommended starting point: Kuzu (embedded, persistent, Cypher-compatible, no ops overhead). Upgrade path to Neo4j if scale requires it. Entity extraction already runs at ingest time; migration scope is the storage and query layer only.

### v1.4 — Security
**Functional / Technical**
- Encryption at rest
- **Flask to FastAPI migration** — Flask 3 + Gunicorn is synchronous. LLM inference, streaming responses, and MCP integrations are inherently async. FastAPI + Uvicorn is the correct fit for this workload. Migration scope: all route handlers, middleware (JWT, CORS, rate limiting), Pydantic v2 models. Flask-JWT-Extended to fastapi-jwt; Flask-Limiter to slowapi; Flask-CORS to FastAPI built-in. Execute in one branch, not incrementally across releases. Zero direct user-facing change but required before any further agentic scale-out.

### v1.5 — Chat UX and Document Sources
**Functional**
- **Drag-and-drop upload** — drop files directly onto the chat interface; no separate upload screen required
- **Connect information stores** — link OneDrive, SharePoint, S3, or other configured connectors directly from the chat UI (backends already exist in src/connectors/)
- **Multi-source selection** — activate and deactivate multiple document sources per conversation; retrieval scoped to the active selection

---

## Tech Stack: Current vs. Target

| Layer | Current | Target | Version |
|-------|---------|--------|---------|
| Web framework | Flask 3 + Gunicorn | FastAPI + Uvicorn | v1.4 |
| Caching / rate limit backend | Redis or in-memory (silent fallback) | Explicit Redis or in-memory only, no silent path | v1.1 |
| Graph store | spaCy NER + flat PostgreSQL relation table | Kuzu (embedded, Cypher-compatible) | v1.3 |

---

## Improvement Recommendations Audit

*Code review findings — May 2026*

The following three recommendations are drawn from a full review of the LocalChat repository (646 commits as of review date). Two are correctness/security concerns that currently pass silently; one addresses the largest accumulation of technical debt in the codebase.

| # | Recommendation | Type | Effort | Impact | Status |
|---|---|---|---|---|---|
| 1 | Startup secret validation | Security | Low (1-2 hours) | High — eliminates JWT forgery risk | Done |
| 2 | Idempotent admin user seeding | Correctness | Low (1 hour) | High — fixes production startup race | Done |
| 3 | Decompose app_factory.py | Architecture | Medium (half day) | High — largest maintainability gain available | Open |

### 1 — Startup Secret Validation ✓

config.py loads SECRET_KEY, JWT_SECRET_KEY, and ADMIN_PASSWORD from environment variables. Without validation, a deployment with a weak or placeholder key would start cleanly and serve traffic with forgeable JWT tokens.

**Shipped:** `validate_secrets()` in `src/config.py` enforces minimum key length (32 chars), rejects known placeholders (`changeme`, `secret`, `dev`, etc.), and calls `sys.exit(1)` in production mode on any violation. Called as the first step in `create_app()`.

### 2 — Idempotent Admin User Seeding ✓

`_seed_admin_user()` in `app_factory.py` previously used a check-then-insert pattern. Gunicorn starts multiple workers concurrently; two workers could both read `count_users() == 0` before either committed, resulting in a duplicate row or unhandled startup exception.

**Shipped:** `_seed_admin_user()` now uses a PostgreSQL upsert (`INSERT ... ON CONFLICT (username) DO NOTHING`), making the operation atomic and safe to call from any number of concurrent workers.

### 3 — Decompose app_factory.py

At 618 lines, `app_factory.py` conflates two concerns: wiring (Flask app, blueprints, security middleware) and bootstrapping (Ollama check, DB init, admin seeding, embedding warmup, plugin loading, connector startup, reranker scheduler). The `testing` flag threads through every private function to suppress bootstrapping side-effects.

**Fix:** split into `src/app_factory.py` (pure wiring, ~200 lines, safe to call in tests with zero mocking) and `src/app_bootstrap.py` (all startup I/O, ~300 lines). The `testing` flag disappears; `bootstrap_app(app)` is called only from the production entry point.

---

## Design Principles

1. **Local first** — no data leaves the machine without explicit configuration
2. **Graceful degradation** — every optional dependency (Redis, reranker, cloud fallback) degrades gracefully with explicit operator visibility
3. **Composable** — each MCP server is independently deployable; new connectors require zero changes to core retrieval
4. **Observable by default** — every request carries a trace ID; all slow paths are logged and metered
5. **Test everything** — no feature ships without unit tests; no integration path ships without an integration test
6. **Cross-domain awareness** — every roadmap change is evaluated for functional and technical consequences before acceptance
