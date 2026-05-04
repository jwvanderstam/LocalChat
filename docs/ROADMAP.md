# LocalChat Roadmap

LocalChat exists to be the gold standard for local, privacy-preserving knowledge management — an agentic RAG system that learns from every interaction and improves its own retrieval quality over time.

---

## What's in v1.0

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

### v1.1 — Quality & Reach
- Multi-language document support
- Confluence and Google Drive connectors
- Answer confidence scores surfaced in the UI
- Scheduled document re-ingestion for stale sources

### v1.2 — Collaboration
- Shared workspaces with real-time presence
- Annotation layer: highlight source chunks directly in documents
- Export: structured answers with citations to PDF/DOCX

### v1.3 — Intelligence
- Automatic ontology extraction per workspace (GraphRAG expansion)
- Active learning loop: model suggests which documents to ingest next
- Cross-workspace retrieval for shared knowledge bases

---

## Improvement Recommendations Audit

*Code review findings — May 2026*

The following three recommendations are drawn from a full review of the LocalChat repository (646 commits as of review date). Two are correctness/security concerns that currently pass silently; one addresses the largest accumulation of technical debt in the codebase.

| # | Recommendation | Type | Effort | Impact |
|---|---|---|---|---|
| 1 | Startup secret validation | Security | Low (1–2 hours) | High — eliminates JWT forgery risk |
| 2 | Idempotent admin user seeding | Correctness | Low (1 hour) | High — fixes production startup race |
| 3 | Decompose `app_factory.py` | Architecture | Medium (half day) | High — largest maintainability gain available |

### 1 — Startup Secret Validation

`config.py` loads `SECRET_KEY`, `JWT_SECRET_KEY`, and `ADMIN_PASSWORD` from environment variables with no entropy or length check. A deployment with a weak or placeholder key starts cleanly, passes all health checks, and serves traffic — but JWT tokens can be forged trivially. There is no log warning, no startup failure, no signal to the operator.

**Fix:** add a `validate_secrets()` call as the first step inside `create_app()` that enforces minimum key length (32 chars), rejects known placeholders (`"changeme"`, `"secret"`, `"dev"`, etc.), and calls `sys.exit(1)` in production mode for any violation.

### 2 — Idempotent Admin User Seeding

`_seed_admin_user()` in `app_factory.py` uses a check-then-insert pattern (`if count_users() == 0: create_user(...)`). Gunicorn starts multiple workers concurrently; two workers can both read `count_users() == 0` before either commits, resulting in a duplicate row or an unhandled startup exception. This race is dormant in single-worker development but active in every production deployment.

**Fix:** replace `create_user()` in the seeding path with a PostgreSQL upsert (`INSERT ... ON CONFLICT (username) DO NOTHING`), making the operation atomic and safe to call from any number of concurrent workers.

### 3 — Decompose `app_factory.py`

At 615 lines, `app_factory.py` conflates two concerns: wiring (Flask app, blueprints, security middleware) and bootstrapping (Ollama check, DB init, admin seeding, embedding warmup, plugin loading, connector startup, reranker scheduler). The `testing` flag threads through every private function to suppress bootstrapping side-effects. As roadmap features land, this file will grow further.

**Fix:** split into `src/app_factory.py` (pure wiring, ~200 lines, safe to call in tests with zero mocking) and `src/app_bootstrap.py` (all startup I/O, ~300 lines). The `testing` flag disappears; `bootstrap_app(app)` is called only from the production entry point.

---

## Design Principles

1. **Local first** — no data leaves the machine without explicit configuration
2. **Graceful degradation** — every optional dependency (Redis, reranker, cloud fallback) degrades silently
3. **Composable** — each MCP server is independently deployable; new connectors require zero changes to core retrieval
4. **Observable by default** — every request carries a trace ID; all slow paths are logged and metered
5. **Test everything** — no feature ships without unit tests; no integration path ships without an integration test
