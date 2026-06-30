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
| **Routes** | |
| `src/routes_fastapi/api_routes.py` | Chat (SSE), status — HTTP plumbing only; delegates business logic to `src/services/chat.py` |
| `src/services/chat.py` | Chat business logic: context retrieval, RAG, planning, memory, model routing, message persistence |
| `src/routes_fastapi/document_routes.py` | Document upload, delete, list; SSE progress stream |
| `src/routes_fastapi/model_routes.py` | Ollama model list, pull, delete, active-model management |
| `src/routes_fastapi/memory_routes.py` | Conversation CRUD, export, document-filter endpoints |
| `src/routes_fastapi/longterm_memory_routes.py` | Long-term memory CRUD and manual trigger endpoints |
| `src/routes_fastapi/settings_routes.py` | Settings, admin ops; `/api/health`, `/api/metrics`, `/api/metrics.json` |
| `src/routes_fastapi/workspace_routes.py` | `GET/POST /api/workspaces`, `GET/PUT/DELETE /api/workspaces/{id}`, active, switch |
| `src/routes_fastapi/feedback_routes.py` | `POST /api/feedback`, `GET /api/feedback/stats` |
| `src/routes_fastapi/connector_routes.py` | Connector REST API + webhook receiver; `GET /api/connectors/available` |
| `src/routes_fastapi/auth_routes.py` | User management (admin) + self-service password change |
| `src/routes_fastapi/oauth_routes.py` | OAuth2 flows for Microsoft (`/api/oauth/microsoft/*`) and Google (`/api/oauth/google/*`) |
| `src/routes_fastapi/annotation_routes.py` | Annotation CRUD (`POST /api/annotations`, `GET /api/chunks/{id}/annotations`, `DELETE /api/annotations/{id}`) |
| `src/routes_fastapi/web_routes.py` | Serves the frontend SPA and static assets |
| `src/routes_fastapi/_request_state.py` | Per-request state helpers (request ID, workspace ID) |
| **RAG** | |
| `src/rag/processor.py` | Ingest orchestration: load → chunk → embed → store |
| `src/rag/retrieval.py` | Hybrid search (semantic + BM25); `retrieve_context(filename_filter=)` |
| `src/rag/chunking.py` | Overlapping chunking, preserves table structure |
| `src/rag/loaders.py` | Multi-format document loading |
| `src/rag/active_learning.py` | `suggest_documents()` — knowledge-gap topic suggestions from low-confidence queries |
| `src/rag/planner.py` | `QueryPlanner` — decomposes query into `QueryPlan` |
| `src/rag/doc_type.py` | `DocType` enum, `DocTypeClassifier`, `ChunkerRegistry` |
| `src/rag/reranker.py` | `RerankerModel` singleton; fine-tuned cross-encoder with base fallback |
| `src/rag/feedback_pipeline.py` | Weekly export + cross-encoder fine-tune; `promote_model`, `rollback_model` |
| `src/rag/scoring.py` | BM25 implementation |
| `src/rag/cache.py` | Embedding vector cache |
| `src/rag/web_search.py` | Optional DuckDuckGo integration |
| **Database** | |
| `src/db/connection.py` | psycopg3 pool, pgvector HNSW index, `_init_schema()`, additive migrations |
| `src/db/documents.py` | Document/chunk CRUD; `search_similar_chunks(filename_filter=)` |
| `src/db/conversations.py` | Persistent conversation history; `get/set_conversation_document_filter` |
| `src/db/entities.py` | `EntitiesMixin` — GraphRAG entity/relation CRUD |
| `src/db/memories.py` | `MemoriesMixin` — long-term memory CRUD + vector search |
| `src/db/feedback.py` | `FeedbackMixin` — `answer_feedback` + `chunk_stats` CRUD |
| `src/db/workspaces.py` | `WorkspacesMixin` — workspace CRUD with doc/conversation counts |
| `src/db/connectors.py` | `ConnectorsMixin` — connector CRUD, sync log, `delete_document_by_filename` |
| `src/db/users.py` | `UsersMixin` — user CRUD, PBKDF2 password hashing |
| `src/db/oauth_tokens.py` | `OAuthTokensMixin` — Fernet-encrypted OAuth token storage |
| `src/db/tokens.py` | `TokensMixin` — JWT revocation deny-list (`revoked_tokens` table) |
| **Migrations** | |
| `alembic.ini` | Alembic configuration — script_location, logging |
| `migrations/env.py` | Alembic environment — builds SQLAlchemy URL from `src.config`, runs `upgrade head` |
| `migrations/versions/0001_baseline.py` | Empty baseline migration (initial `_init_schema()` state) |
| `migrations/versions/0002_early_additive_columns.py` | Adds conversations/documents/messages early columns |
| `migrations/versions/0003_workspace_columns.py` | Adds workspace_id FK to documents, conversations, memories, answer_feedback |
| `migrations/versions/0004_documents_language_ingest_source.py` | Adds documents.language, last_ingested_at, source_id |
| `migrations/versions/0005_document_soft_delete.py` | CW-1: adds documents.deleted_at, deleted_by; document_chunks.deleted_at |
| `migrations/versions/0006_cw2a_conversations_soft_delete.py` | CW-2a: adds conversations.deleted_at, deleted_by |
| `migrations/versions/0007_cw2b_users_soft_delete.py` | CW-2b: adds users.deleted_at, deleted_by |
| `docs/MIGRATIONS.md` | Migration docs — how to apply, write, and roll back |
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
| **Graph / Memory / Performance** | |
| `src/graph/store.py` | `GraphStore` ABC + `PostgresGraphStore` (default) + `KuzuGraphStore` (optional); `create_graph_store(db)` factory |
| `src/graph/extractor.py` | spaCy entity extraction from document chunks; accepts `graph_store` injection |
| `src/graph/expander.py` | `QueryExpander` — 1-hop BM25 term expansion via entity co-occurrences; accepts `graph_store` injection |
| `src/memory/extractor.py` | Extracts memorable facts from conversation turns |
| `src/memory/retriever.py` | `MemoryRetriever` — vector-searches memories, injects top-K into LLM prompt |
| `src/performance/batch_processor.py` | `BatchEmbeddingProcessor` — parallel batch embedding |
| **Connectors** | |
| `src/connectors/base.py` | `BaseConnector` ABC + `DocumentSource`, `DocumentEvent`, `EventType` |
| `src/connectors/local_folder.py` | Stat-based folder watcher |
| `src/connectors/s3_connector.py` | S3/MinIO/R2 via boto3 (optional dep) |
| `src/connectors/webhook.py` | Receives push events via HTTP POST |
| `src/connectors/sharepoint_connector.py` | SharePoint connector — Graph API delta queries |
| `src/connectors/onedrive_connector.py` | OneDrive connector — Graph API delta queries |
| `src/db/annotations.py` | `AnnotationsMixin` — annotation CRUD |
| `src/connectors/microsoft_auth.py` | `get_valid_access_token` — checks expiry, refreshes via Graph |
| `src/connectors/google_drive_connector.py` | Google Drive connector — Drive API v3 changes feed |
| `src/connectors/google_auth.py` | `get_valid_google_access_token` — checks expiry, refreshes via Google OAuth2 |
| `src/connectors/confluence_connector.py` | Confluence Cloud connector — CQL `lastModified` polling, Basic auth |
| `src/connectors/registry.py` | `ConnectorRegistry` singleton |
| `src/connectors/worker.py` | `SyncWorker` daemon — polls connectors, ingests changes |
| **MCP servers** | |
| `mcp_servers/base.py` | `MCPServer` base — JSON-RPC 2.0 dispatcher |
| `mcp_servers/local_docs/server.py` | Local-docs MCP server; gunicorn port 5001 |
| `mcp_servers/web_search/server.py` | Web-search MCP server; gunicorn port 5002 |
| `mcp_servers/cloud_connectors/server.py` | Cloud-connectors MCP server; gunicorn port 5003 |
| **Utils** | |
| `src/utils/logging_config.py` | `JsonFormatter` + `RequestIdFilter`; `LOG_FORMAT=json` |
| `src/utils/request_id.py` | X-Request-ID middleware + per-request access log |
| `src/utils/file_validation.py` | Magic-byte + ZIP content validation for uploaded files; prevents content-type spoofing |
| `src/utils/sanitization.py` | HTML/injection cleaning |
| `src/utils/encryption.py` | Canonical Fernet `encrypt()`/`decrypt()` for sensitive text columns at rest |
| `src/utils/export.py` | Conversation export: DOCX (python-docx) and PDF (reportlab, optional) |
| `src/utils/workspace.py` | `get_workspace_id()` — reads `X-Workspace-ID` header (or `workspace_id` query param); single source of truth for workspace scoping per-request |
| **Infra / Config** | |
| `pyproject.toml` | Tool config — `[tool.ruff]`, `[tool.pytest.ini_options]`, `[tool.coverage.*]` |
| `docker-compose.yml` | Full stack: app + PostgreSQL + Redis + Ollama; `--profile mcp` adds MCP servers |
| `helm/localchat/` | Full Helm chart: app + PostgreSQL + Redis StatefulSets + MCP Deployments |
| `docs/DEPLOYMENT.md` | Helm install/upgrade/rollback guide, secrets management |
| `docs/grafana-dashboard.json` | Importable Grafana dashboard (uid `localchat-rag-v1`, 7 panels) |
| `tests/conftest.py` | Shared pytest fixtures |
| `.github/dependabot.yml` | Weekly pip + Actions updates; auto-assigned, labels `dependencies`/`ci` |
| `.github/workflows/codeql.yml` | CodeQL `security-extended` on push/PR to main + weekly scan |
| `.github/workflows/tests.yml` | CI: `unit-tests` (ruff + pytest unit) + `integration-tests` (postgres:pg16 service + pytest integration, excludes ollama) |
| `docs/INTEGRATION_TESTS.md` | How to run integration tests locally and CI setup instructions |
| `docker-compose.nginx.yml` | Nginx TLS overlay — compose with `docker-compose.yml` to add HTTPS termination |
| `nginx/nginx.conf` | Nginx config template — replace `YOUR_DOMAIN` and mount certs before use |
| `tests/e2e/test_smoke.py` | Playwright smoke tests (`@pytest.mark.e2e`); require a live server + `pytest-playwright` |
| **Frontend** | |
| `static/js/ui.js` | Pure rendering helpers (no state): `escapeHtml`, `formatMessageText`, `buildSourcesPanel`, etc. |
| `static/js/conversation.js` | Conversation state + sidebar + message DOM mutations; exports `getChatHistory`, `sendMessage` helpers |
| `static/js/streaming.js` | SSE event loop and `sendMessage()`; owns `isStreaming` flag |
| `static/js/chat.js` | Slim orchestrator (~90 lines) — wires event listeners to the three modules above |
