# File Map

Full module index for LocalChat. **Keep this current** — update in the same commit when adding or removing a file.

| File | Role |
|------|------|
| `app.py` | Entry point; `main()` + `create_uvicorn_app()` for dev/prod (FastAPI + Uvicorn) |
| `src/app_fastapi.py` | `create_app()` — FastAPI factory, pure wiring only (no I/O); safe to call in tests |
| `src/app_bootstrap.py` | `bootstrap_app(app)` — all startup I/O (Ollama, DB, caching, plugins, connectors, reranker); called from `app.py` only |
| `src/config.py` | All configuration constants, loads `.env` |
| `src/models.py` | Pydantic request/response models |
| `src/security_fastapi.py` | JWT (`python-jose`), rate limiting (`slowapi`), CORS (Starlette middleware) |
| `src/monitoring.py` | `MetricsCollector`, `export_prometheus_metrics`, `get_metrics`; `MetricsMiddleware` (ASGI) for request timing |
| `src/ollama_client.py` | `OllamaClient` singleton — chat (stream + non-stream), embedding, model CRUD, vision, GPU info; `estimate_model_footprint()`, `load_model_guard()`; TTL-cached model list (60 s) and running models (5 s) |
| `src/llm_client.py` | `LiteLLMClient` cloud-fallback adapter; `ModelClient` Protocol |
| `src/gpu/__init__.py` | GPU package — re-exports `GpuBackend`, `detect`, and backend classes |
| `src/gpu/backends.py` | `GpuBackend` Protocol + `NvidiaBackend`, `AmdBackend` (stub), `AppleBackend`, `CpuBackend`; `detect(force)` factory (MM-1) |
| `src/gpu_monitor.py` | `GpuMonitor` — NVIDIA/AMD detection via `nvidia-smi`/`rocm-smi`, TTL 30 s (per-GPU detail for admin dashboard) |
| `src/mcp_client.py` | MCP HTTP client; `MCPClientRegistry` singleton + per-server `CircuitBreaker` |
| `src/exceptions.py` | `LocalChatException` hierarchy (`OllamaConnectionError`, `DatabaseConnectionError`, `DocNotFoundError`, etc.) + `EXCEPTION_STATUS_CODES` |
| **Routes** | |
| `src/routes_fastapi/api_routes.py` | Chat (SSE), status — HTTP plumbing only; delegates business logic to `src/services/chat.py` |
| `src/services/chat.py` | Chat business logic: context retrieval, RAG, planning, memory, model routing, message persistence |
| `src/services/logs.py` | Reads the tail of the log file back for the admin log viewer; parses both JSON and text lines |
| `src/routes_fastapi/document_routes.py` | Document upload, delete, list; SSE progress stream |
| `src/routes_fastapi/model_routes.py` | Ollama model list, pull, delete, active-model management |
| `src/routes_fastapi/memory_routes.py` | Conversation CRUD, export, document-filter endpoints |
| `src/routes_fastapi/longterm_memory_routes.py` | Long-term memory CRUD and manual trigger endpoints |
| `src/routes_fastapi/settings_routes.py` | Settings, admin ops; `/api/health`, `/api/metrics`, `/api/metrics.json`, `/api/logs` (admin log viewer) |
| `src/routes_fastapi/workspace_routes.py` | `GET/POST /api/workspaces`, `GET/PUT/DELETE /api/workspaces/{id}`, active, switch |
| `src/routes_fastapi/feedback_routes.py` | `POST /api/feedback`, `GET /api/feedback/stats` |
| `src/routes_fastapi/connector_routes.py` | Connector REST API + webhook receiver; `GET /api/connectors/available` |
| `src/routes_fastapi/auth_routes.py` | `POST /api/auth/login` (issues the session cookie), logout, user management incl. per-user workspace membership (admin), self-service: `GET /api/users/me`, password change |
| `src/routes_fastapi/oauth_routes.py` | OAuth2 flows for Microsoft (`/api/oauth/microsoft/*`) and Google (`/api/oauth/google/*`) |
| `src/routes_fastapi/annotation_routes.py` | Annotation CRUD (`POST /api/annotations`, `GET /api/chunks/{id}/annotations`, `DELETE /api/annotations/{id}`) |
| `src/routes_fastapi/docs_routes.py` | Repo-docs API: `GET /api/repo-docs`, `GET /api/repo-docs/{slug}`, `GET /api/repo-docs/{slug}/fragments/{fragment_slug}` — serves `DocsService` (`src/docs/service.py`) |
| `src/routes_fastapi/web_routes.py` | Serves the frontend SPA and static assets |
| `src/routes_fastapi/_request_state.py` | Per-request state helpers (request ID, workspace ID) |
| `src/routes_fastapi/_authz.py` | `deny()` — wraps `check_workspace_access` in the route layer's JSON envelope; shared by every workspace-scoped router |
| **RAG** | |
| `src/rag/processor.py` | Ingest orchestration: load → chunk → embed → store |
| `src/rag/retrieval.py` | Hybrid search — independent semantic (pgvector) + lexical (Postgres tsvector/GIN) arms, weighted blend; `retrieve_context(filename_filter=)` |
| `src/rag/chunking.py` | Overlapping chunking, preserves table structure |
| `src/rag/loaders.py` | Multi-format document loading |
| `src/rag/active_learning.py` | `suggest_documents()` — knowledge-gap topic suggestions from low-confidence queries |
| `src/rag/planner.py` | `QueryPlanner` — decomposes query into `QueryPlan` |
| `src/rag/doc_type.py` | `DocType` enum, `DocTypeClassifier`, `ChunkerRegistry` |
| `src/rag/reranker.py` | `RerankerModel` singleton; fine-tuned cross-encoder with base fallback |
| `src/rag/feedback_pipeline.py` | Weekly export + cross-encoder fine-tune; `promote_model`, `rollback_model` |
| `src/rag/cache.py` | Embedding vector cache |
| `src/rag/web_search.py` | Optional DuckDuckGo integration |
| **Database** | |
| `src/db/connection.py` | psycopg3 pool, pgvector HNSW index, `_ensure_extensions_and_tables()`, additive migrations |
| `src/db/documents.py` | Document/chunk CRUD; `search_similar_chunks(filename_filter=)` |
| `src/db/conversations.py` | Persistent conversation history; `count_conversations` (paging); `get/set_conversation_document_filter` |
| `src/db/entities.py` | `EntitiesMixin` — GraphRAG entity/relation CRUD |
| `src/db/memories.py` | `MemoriesMixin` — long-term memory CRUD + vector search |
| `src/db/feedback.py` | `FeedbackMixin` — `answer_feedback` + `chunk_stats` CRUD |
| `src/db/workspace_keys.py` | `WorkspaceKeysMixin` — workspace API keys: create/resolve/list/revoke; sha256-hashed, prefix-indexed |
| `src/db/workspaces.py` | `WorkspacesMixin` — workspace CRUD with doc/conversation counts |
| `src/db/connectors.py` | `ConnectorsMixin` — connector CRUD, sync log, `delete_document_by_filename` |
| `src/db/users.py` | `UsersMixin` — user CRUD, PBKDF2 password hashing |
| `src/db/oauth_tokens.py` | `OAuthTokensMixin` — Fernet-encrypted OAuth token storage |
| `src/db/tokens.py` | `TokensMixin` — JWT revocation deny-list (`revoked_tokens` table) |
| `src/db/annotations.py` | `AnnotationsMixin` — annotation CRUD |
| **Migrations** | |
| `alembic.ini` | Alembic configuration — script_location, logging |
| `migrations/env.py` | Alembic environment — builds SQLAlchemy URL from `src.config`, runs `upgrade head` |
| `migrations/versions/0001_baseline.py` | Empty baseline migration (initial `_ensure_extensions_and_tables()` state) |
| `migrations/versions/0002_early_additive_columns.py` | Adds conversations/documents/messages early columns |
| `migrations/versions/0003_workspace_columns.py` | Adds workspace_id FK to documents, conversations, memories, answer_feedback |
| `migrations/versions/0004_documents_language_ingest_source.py` | Adds documents.language, last_ingested_at, source_id |
| `migrations/versions/0005_document_soft_delete.py` | CW-1: adds documents.deleted_at, deleted_by; document_chunks.deleted_at |
| `migrations/versions/0006_cw2a_conversations_soft_delete.py` | CW-2a: adds conversations.deleted_at, deleted_by |
| `migrations/versions/0007_cw2b_users_soft_delete.py` | CW-2b: adds users.deleted_at, deleted_by |
| `migrations/versions/0008_cw2c_workspaces_soft_delete.py` | CW-2c: adds workspaces.deleted_at, deleted_by |
| `migrations/versions/0009_cw2d_memories_soft_delete.py` | CW-2d: adds memories.deleted_at, deleted_by |
| `migrations/versions/0010_cw2e_annotations_soft_delete.py` | CW-2e: adds annotations.deleted_at, deleted_by |
| `migrations/versions/0011_cw2f_connectors_soft_delete.py` | CW-2f: adds connectors.deleted_at, deleted_by |
| `migrations/versions/0012_hybrid_search_tsvector.py` | Adds the tsvector column + GIN index backing the lexical arm of hybrid search |
| `migrations/versions/0013_documents_unique_filename_workspace.py` | Enforces one live document per (filename, workspace_id) |
| `migrations/versions/0014_rbac1_backfill_workspace_members.py` | RBAC-1: backfills workspace_members — admins own every live workspace, other users get editor on the default one |
| `migrations/versions/0015_workspace_api_keys.py` | Adds workspace_api_keys — scoped, revocable credentials for programmatic workspace access |
| `migrations/versions/0016_connectors_created_by.py` | BUG-4: adds connectors.created_by — the only source of the identity whose OAuth token a connector may spend |
| `docs/README.md` | Documentation index — Diátaxis quadrants; the map every other doc is reached from |
| `docs/CONFIGURATION.md` | Configuration reference — every env var, default and effect (lifted out of README) |
| `docs/MIGRATIONS.md` | Migration docs — how to apply, write, and roll back |
| `tests/integration/test_migrations_apply.py` | TQ-5b — the migration chain applies against a real database, lands on the single head, and a second run does nothing |
| `docs/OPERATIONS.md` | Backup/restore/maintenance runbook |
| `docs/ROADMAP.md` | Living initiative/ticket plan (current: v3.0 — hygiene, Clark-Wilson, RBAC, GKB, model management, plugin contract) |
| `docs/WORKSPACE_API_KEYS.md` | How to give a chatbot/n8n bridge scoped access to one workspace — create, use, revoke, and why the scope cannot be overridden |
| `docs/n8n-discord-setup.md` | Werkende n8n → LocalChat → Discord opzet: Header Auth, SSE-respons als tekst parsen, valkuilen |
| `docs/bugreport-n8n-localchat.md` | Bevindingen bij het opzetten van die koppeling — 2 opgelost, 1 open (`conversation_id` → 500) |
| `docs/AUTH_PLAN.md` | Authentication build plan — AUTH-1..4: local login, Users screen, OIDC (Entra/Google), then deleting the bypasses |
| `docs/PRODUCTION_PLAN.md` | Production-hardening plan from the 2026-08-04 external audit — TQ/SEC tickets and the exit criteria ROADMAP Sprints 8–12 queue behind |
| `docs/localchat_scaleway_deployment_plan.md` | Scaleway test-stack deployment plan — per-service mapping of the compose stack, the Ollama/GPU decision, and the pgvector `SET` caveat; planning only, nothing built |
| `docs/ADR.md` | Architecture Decision Records — ADR-1 (single-node appliance) and ADR-2 (sync DB layer), each with the condition that would reopen it |
| `docs/PERMISSIONS.md` | Route permission matrix (RBAC-2) — every route's minimum role, read from source, plus the public allowlist with reasons |
| `docs/SCHEMA.md` | Database schema reference + ER diagram |
| `docs/TROUBLESHOOTING.md` | Common issues and fixes |
| `docs/LESSONS_LEARNED.md` | Chronological architecture/decision history, built from `git log` + `docs/ROADMAP.md` |
| `docs/SETTINGS.md` | Per-RAG-parameter descriptions — source of truth for `templates/settings.html`'s help text via `DocsService` |
| **Agent** | |
| `src/agent/router.py` | `ModelRouter` — rule-based classifier (VISION/CODE/LARGE/FAST/BASE); <1 ms |
| `src/agent/aggregator.py` | `AggregatorAgent` — parallel tool dispatch, retry, dedup |
| `src/agent/tool_router.py` | `ToolRouter` — maps tool names to MCP or direct handlers |
| `src/agent/result.py` | `AgentResult`, `ToolCall` dataclasses; `to_trace_dict()` |
| `src/agent/models.py` | `ModelRegistry` — env-driven model class → Ollama ID mapping |
| **Tools** | |
| `src/tools/executor.py` | Ollama tool-call loop (multi-turn until final response) |
| `src/tools/registry.py` | Tool registration with JSON schemas |
| `src/tools/builtin.py` | Built-in tools: document search, calculator, datetime |
| `src/tools/plugin_loader.py` | Loads `.py` plugins from `plugins/` at startup |
| `plugins/example_plugin.py` | Reference plugin demo (`word_count`, `reverse_text` tools) |
| `plugins/README.md` | Plugin authoring guide |
| **Graph / Memory / Performance** | |
| `src/graph/store.py` | `GraphStore` ABC + `PostgresGraphStore` (default) + `KuzuGraphStore` (optional); `create_graph_store(db)` factory |
| `src/graph/extractor.py` | spaCy entity extraction from document chunks; accepts `graph_store` injection |
| `src/graph/expander.py` | `QueryExpander` — 1-hop lexical term expansion via entity co-occurrences, feeding both the embedding and the tsvector lexical arm; accepts `graph_store` injection |
| `src/memory/extractor.py` | Extracts memorable facts from conversation turns |
| `src/memory/retriever.py` | `MemoryRetriever` — vector-searches memories, injects top-K into LLM prompt |
| `src/performance/batch_processor.py` | `BatchEmbeddingProcessor` — parallel batch embedding |
| **Cache** | |
| `src/cache/__init__.py` | `CacheBackend` ABC, `MemoryCache`, `RedisCache`, `create_cache_backend()` factory |
| `src/cache/managers.py` | Cache manager selecting Redis/in-memory backend by config |
| **Docs** | |
| `src/docs/service.py` | `DocsService` — loads a fixed catalogue of repo markdown files (`CLAUDE.md`, `.claude/rules/*.md`, `docs/*.md`, `README.md`, `SECURITY.md`), splits into heading-keyed fragments, renders to HTML; backs the `/docs` viewer and `templates/settings.html`'s per-parameter help text |
| **Connectors** | |
| `src/connectors/base.py` | `BaseConnector` ABC + `DocumentSource`, `DocumentEvent`, `EventType` |
| `src/connectors/local_folder.py` | Stat-based folder watcher |
| `src/connectors/s3_connector.py` | S3/MinIO/R2 via boto3 (optional dep) |
| `src/connectors/webhook.py` | Receives push events via HTTP POST |
| `src/connectors/sharepoint_connector.py` | SharePoint connector — Graph API delta queries |
| `src/connectors/onedrive_connector.py` | OneDrive connector — Graph API delta queries |
| `src/connectors/microsoft_auth.py` | `get_valid_access_token` — checks expiry, refreshes via Graph |
| `src/connectors/google_drive_connector.py` | Google Drive connector — Drive API v3 changes feed |
| `src/connectors/google_auth.py` | `get_valid_google_access_token` — checks expiry, refreshes via Google OAuth2 |
| `src/connectors/registry.py` | `ConnectorRegistry` singleton |
| `src/connectors/worker.py` | `SyncWorker` daemon — polls connectors, ingests changes |
| **MCP servers** | |
| `mcp_servers/base.py` | `MCPServer` base — JSON-RPC 2.0 dispatcher |
| `mcp_servers/local_docs/server.py` | Local-docs MCP server; gunicorn port 5001 |
| `mcp_servers/web_search/server.py` | Web-search MCP server; gunicorn port 5002 |
| `mcp_servers/cloud_connectors/server.py` | Cloud-connectors MCP server; gunicorn port 5003 |
| **Utils** | |
| `src/utils/logging_config.py` | `JsonFormatter` + `RequestIdFilter`; `LOG_FORMAT=json`; configurable sinks (`console`/`file`/`syslog`) with bounded rotation, degrading rather than failing when a sink cannot be built; startup buffer that replays records logged before `setup_logging()` |
| `src/utils/request_id.py` | X-Request-ID middleware + per-request access log |
| `src/utils/file_validation.py` | Magic-byte + ZIP content validation for uploaded files; prevents content-type spoofing |
| `src/utils/sanitization.py` | HTML/injection cleaning |
| `src/utils/encryption.py` | Canonical Fernet `encrypt()`/`decrypt()` for sensitive text columns at rest |
| `src/utils/export.py` | Conversation export: DOCX (python-docx) and PDF (reportlab, optional) |
| `src/utils/workspace.py` | `get_workspace_id()` — reads `X-Workspace-ID` header (or `workspace_id` query param); single source of truth for workspace scoping per-request |
| **Infra / Config** | |
| `pyproject.toml` | Tool config — `[tool.ruff]`, `[tool.pytest.ini_options]`, `[tool.coverage.*]` |
| `docker-compose.yml` | Full stack: app + PostgreSQL + Redis + Ollama; `--profile mcp` adds MCP servers |
| `Dockerfile` | Multi-stage build on Docker Hardened Images — `dhi.io/python:3.12-dev` builds the venv, `dhi.io/python:3.12` runs it as uid 65532 with no shell or package manager |
| `docker-entrypoint.py` | Container entrypoint — expands `SERVER_PORT`/`UVICORN_WORKERS`/`UVICORN_TIMEOUT` (the hardened base has no shell to do it) and `exec`s uvicorn so it stays PID 1 |
| `docs/DEPLOYMENT.md` | Docker Compose deployment: secrets, resource limits, upgrade/rollback, TLS, security checklist |
| `docs/grafana-dashboard.json` | Importable Grafana dashboard (uid `localchat-rag-v1`, 16 panels) |
| `tests/conftest.py` | Shared pytest fixtures |
| `tests/utils/` | Shared test helpers (`helpers.py`, `mocks.py`) used across unit/integration suites |
| `tests/unit/test_oauth_routes_identity.py` | BUG-4 — the OAuth callbacks store a token against a real user or refuse; no `"admin"` string fallback |
| `tests/unit/test_purge_preconditions.py` | The Clark-Wilson purge TPs — a cited conversation or a user with memberships is refused before any DELETE |
| `tests/unit/test_processor_entity_extraction.py` | `_extract_entities` — GraphRAG is best-effort; a failure there never fails an ingest |
| `tests/utils/js_harness.py` | `run_js()` — executes a real `static/js` file under node with stubbed browser globals; runs ES modules that import their siblings (`chat.js`) as well as standalone scripts; how frontend branch logic is tested |
| `tests/utils/auth.py` | `auth_headers()`, `authorise_db()`, `authenticated_state()` — how a test authenticates for real; replaced the `app.state.testing` bypass (TQ-1b) |
| `tests/utils/fake_ollama.py` | TQ-2 stub for Ollama — bag-of-words embeddings (deterministic, and meaningful so ranking assertions are real) plus a canned chat stream |
| `tests/e2e/conftest.py` | Starts a real LocalChat (uvicorn subprocess + CI's Postgres + TQ-2's fake Ollama) and points Playwright's `base_url` at it; `server_env` lets a suite override the server's environment |
| `tests/perf/conftest.py` | Reuses `live_server`, raising `RATELIMIT_CHAT` — at its 10/min default a concurrency run measures slowapi, not the event loop |
| `tests/perf/test_concurrency_canary.py` | PERF-2 — `/api/health` stays answerable while concurrent SSE streams run; prints the canary spread every run |
| `tests/e2e/test_golden_path.py` | TQ-4 — sign in, upload, ask, and the answer cites the uploaded file; the whole frontend test strategy |
| `scripts/session-status.sh` | `git session-status` alias target — flags orphaned branches, sync drift, open PRs |
| `scripts/bench_concurrency.py` | PERF-2 — concurrent SSE load against `/api/chat`; p50/p95 TTFT plus an `/api/health` canary that exposes a blocked event loop; `--max-canary-ms` is the CI gate |
| `tests/unit/test_bench_concurrency.py` | PERF-2 — the canary gate's verdict: fails on the worst probe, and treats an empty sample as a failure rather than a pass |
| `.github/dependabot.yml` | Weekly pip + Actions updates; auto-assigned, labels `dependencies`/`ci` |
| `tests/unit/test_security_contract.py` | TQ-3 — the auth layer's observable contract, written against named surviving mutants |
| `tests/unit/test_workspace_access_contract.py` | TQ-3 — the workspace authorisation path, same method |
| `scripts/mutation_gate.py` | TQ-3 — runs `mutmut<3` over the isolation-critical modules, screens the result for a broken harness, fails under the agreed kill rate |
| `.github/workflows/mutation.yml` | Nightly mutation gate (`workflow_dispatch` takes a threshold); not in the ruleset |
| `.github/workflows/codeql.yml` | CodeQL `security-extended` on push/PR to main + weekly scan |
| `.github/workflows/tests.yml` | CI: `unit-tests` (ruff + mypy + bandit + pip-audit + pytest unit) + `integration-tests` (postgres:pg16 service + pytest integration, excludes ollama) + `docker-smoke` (builds the hardened image, asserts uid 65532 / no shell / native imports / catalogued docs present, boots it against postgres on a non-default port) + `repo-hygiene` (tracked-artifact/gitignore check, Flask-import ban, Conventional Commits warning) |
| `.github/workflows/sonarcloud.yml` | SonarCloud quality-gate scan on push/PR to main |
| `.github/workflows/gitleaks.yml` | Secret-scanning on push/PR to main |
| `.github/workflows/docker-publish.yml` | Builds and publishes the app's Docker image |
| `docs/INTEGRATION_TESTS.md` | How to run integration tests locally and CI setup instructions |
| `docs/TEST_QUALITY_AUDIT.md` | Mutation-testing (mutmut) methodology + per-module test-quality findings; environment setup notes (Docker, isolated worktree, mutmut 2.x vs 3.x) |
| `docker-compose.nginx.yml` | Nginx TLS overlay — compose with `docker-compose.yml` to add HTTPS termination |
| `nginx/nginx.conf` | Nginx config template — replace `YOUR_DOMAIN` and mount certs before use |
| **Frontend** | |
| `static/js/ui.js` | Pure rendering helpers (no state): `escapeHtml`, `formatMessageText`, `buildSourcesPanel`, etc. |
| `static/js/conversation.js` | Conversation state + sidebar + message DOM mutations; exports `getChatHistory`, `sendMessage` helpers |
| `static/js/streaming.js` | SSE event loop and `sendMessage()`; owns `isStreaming` flag |
| `static/js/chat.js` | Slim orchestrator (~90 lines) — wires event listeners to the three modules above |
| `static/js/ingestion.js` | Document upload progress (SSE) on `templates/documents.html` |
| `static/js/settings.js` | Theme picker + appearance settings on `templates/settings.html` |
| `static/js/workspace.js` | Workspace switcher dropdown + create-workspace modal, wired into `templates/base.html` |
| `static/js/logs.js` | Logs tab in Settings — admin-only; level/search filter over `/api/logs`, escapes every field before it reaches the DOM |
| `static/js/users.js` | Users tab in Settings — admin-only; user cards with workspace access, create/grant modals, role change, retire, purge; Integrations section for workspace API keys (create, list, revoke) |
| `static/js/confirm.js` | `window.localchatConfirm()` — the in-app confirmation modal every destructive action uses; native `confirm()` is banned in `repo-hygiene` |
| `static/js/auth.js` | Session handling — wraps `fetch` to redirect to `/login` on 401, drives the login form, exposes `localchatLogout()` |
| `templates/login.html` | Login page — the one template that renders without a session |
| `static/js/docs.js` | Documentation viewer (`templates/docs.html`) — fetches `/api/repo-docs`, renders nav + selected doc HTML |
| `static/js/bootstrap.bundle.min.js` | Vendored Bootstrap 5 JS bundle |
| `templates/docs.html` | Documentation viewer shell — nav list + content pane, populated client-side by `docs.js` |
