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

---

## Planned

### v1.1 — Quality and Reach
**Functional**
- **Structured document ingest** *(medium priority)* — Current loaders serialize everything as flat text, losing column-to-value relationships. PDF: upgrade to pymupdf4llm or docling for layout-aware parsing; DOCX: preserve headings and table structure.
- **Excel loader** *(medium priority)* — Per-sheet processing with explicit header preservation; each chunk serialized as a markdown table (N rows + header) with sheet/row-range metadata. Edge cases: multi-row headers, merged cells, numeric formatting. Replaces current flat-text row serialization.
- Multi-language document support
- Confluence and Google Drive connectors
- Answer confidence scores surfaced in the UI
- Scheduled document re-ingestion for stale sources

**Technical**
- **Resolve Redis / in-memory fallback ambiguity** *(high priority)* — The current silent Redis-or-in-memory fallback means Flask-Limiter rate limit state is per-worker, does not survive restarts, and is inconsistent across Gunicorn workers. Decision required: commit to Redis as a hard dependency with a startup health check, or commit to in-memory only and remove Redis from the stack. Do not maintain both paths silently. Affects every component that touches caching or rate limiting.
- **LiteLLM cloud fallback: explicit gate** *(high priority)* — LiteLLM is currently a silent fallback. In a local-first, privacy-oriented application this is a data-leakage risk. Audit and harden so no query reaches a cloud endpoint without explicit per-query user action. Implement in parallel with the UI opt-in.

  > Cross-domain note: if the implicit fallback is what makes the app usable on weak local hardware, removing it without a visible UI opt-in will break that user experience. Both changes must ship together.

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
- **Graph store for real GraphRAG** — spaCy handles entity extraction but GraphRAG requires a persistent graph store for entity/relation traversal. Without one, GraphRAG is NER on top of standard vector retrieval. Recommended starting point: Kuzu (embedded, persistent, Cypher-compatible, no ops overhead). Upgrade path to Neo4j if scale requires it. Entity extraction must run at ingest time, not query time.

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
| Caching / rate limit backend | Redis or in-memory (ambiguous) | Explicit Redis or in-memory only | v1.1 |
| Graph store | spaCy NER only, no persistence | Kuzu (embedded) | v1.3 |
| Cloud fallback | Silent (LiteLLM auto) | Explicit opt-in gate | v1.1 |

---

## Improvement Recommendations Audit

*Code review findings — May 2026*

The following three recommendations are drawn from a full review of the LocalChat repository (646 commits as of review date). Two are correctness/security concerns that currently pass silently; one addresses the largest accumulation of technical debt in the codebase.

| # | Recommendation | Type | Effort | Impact | Status |
|---|---|---|---|---|---|
| 1 | Startup secret validation | Security | Low (1-2 hours) | High — eliminates JWT forgery risk | Done |
| 2 | Idempotent admin user seeding | Correctness | Low (1 hour) | High — fixes production startup race | Done |
| 3 | Decompose app_factory.py | Architecture | Medium (half day) | High — largest maintainability gain available | Open |

### 1 — Startup Secret Validation

config.py loads SECRET_KEY, JWT_SECRET_KEY, and ADMIN_PASSWORD from environment variables with no entropy or length check. A deployment with a weak or placeholder key starts cleanly, passes all health checks, and serves traffic — but JWT tokens can be forged trivially. There is no log warning, no startup failure, no signal to the operator.

**Fix:** add a validate_secrets() call as the first step inside create_app() that enforces minimum key length (32 chars), rejects known placeholders (changeme, secret, dev, etc.), and calls sys.exit(1) in production mode for any violation.

### 2 — Idempotent Admin User Seeding

_seed_admin_user() in app_factory.py uses a check-then-insert pattern. Gunicorn starts multiple workers concurrently; two workers can both read count_users() == 0 before either commits, resulting in a duplicate row or an unhandled startup exception. This race is dormant in single-worker development but active in every production deployment.

**Fix:** replace create_user() in the seeding path with a PostgreSQL upsert (INSERT ... ON CONFLICT (username) DO NOTHING), making the operation atomic and safe to call from any number of concurrent workers.

### 3 — Decompose app_factory.py

At 615 lines, app_factory.py conflates two concerns: wiring (Flask app, blueprints, security middleware) and bootstrapping (Ollama check, DB init, admin seeding, embedding warmup, plugin loading, connector startup, reranker scheduler). The testing flag threads through every private function to suppress bootstrapping side-effects.

**Fix:** split into src/app_factory.py (pure wiring, ~200 lines, safe to call in tests with zero mocking) and src/app_bootstrap.py (all startup I/O, ~300 lines). The testing flag disappears; bootstrap_app(app) is called only from the production entry point.

---

## Design Principles

1. **Local first** — no data leaves the machine without explicit configuration
2. **Graceful degradation** — every optional dependency (Redis, reranker, cloud fallback) degrades gracefully with explicit operator visibility
3. **Composable** — each MCP server is independently deployable; new connectors require zero changes to core retrieval
4. **Observable by default** — every request carries a trace ID; all slow paths are logged and metered
5. **Test everything** — no feature ships without unit tests; no integration path ships without an integration test
6. **Cross-domain awareness** — every roadmap change is evaluated for functional and technical consequences before acceptance
