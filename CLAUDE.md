# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Starting a new session?** Run `git log --oneline -5` and `git fetch origin` first — another agent may have pushed since your last session.

---

## What This Project Is

LocalChat is a production RAG (Retrieval-Augmented Generation) application built with Flask. Users upload documents (PDF, DOCX, TXT, MD), then chat with them using a locally-running LLM via Ollama. Documents are chunked, embedded, and stored in PostgreSQL with pgvector for hybrid semantic + BM25 search. The LLM supports function-calling (tools) and optional live web search.

**Runtime dependencies:** PostgreSQL with pgvector, Ollama (local LLM server), Redis (optional caching).

---

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

---

## Architecture

**Entry point:** root `app.py` → `create_app()` in `src/app_factory.py`. The factory initializes all services, registers blueprints, and returns a `LocalChatApp` instance. The WSGI entry point for gunicorn is `create_gunicorn_app()` in root `app.py`.

**Request flow:**
1. `src/routes/` blueprints handle routing (api, documents, models, memory, longterm_memory, settings, auth_users, connectors, feedback, workspaces, oauth, web)
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
- `doc_type.py` — `DocType` enum, `DocTypeClassifier`, `ChunkerRegistry` (extension → loader/chunker mapping)
- `planner.py` — `QueryPlanner`: decomposes query into `QueryPlan` (intent + sub-questions) before retrieval

`src/db/` — PostgreSQL/pgvector layer:
- `connection.py` — psycopg3 connection pool, pgvector HNSW index setup
- `documents.py` — document/chunk CRUD and vector similarity search
- `conversations.py` — persistent multi-turn conversation history
- `entities.py` — `EntitiesMixin` — knowledge-graph entity/relation CRUD (GraphRAG)
- `memories.py` — `MemoriesMixin` — long-term memory CRUD + vector search (`memories` table)

`src/graph/` — GraphRAG knowledge graph:
- `extractor.py` — spaCy-based named entity extraction from document chunks
- `expander.py` — `QueryExpander`: expands BM25 terms via 1-hop entity co-occurrences

`src/memory/` — Long-term memory across sessions:
- `extractor.py` — extracts memorable facts from conversation turns
- `retriever.py` — `MemoryRetriever`: vector-searches memories and injects top-K into the LLM prompt

`src/performance/` — Performance utilities:
- `batch_processor.py` — `BatchEmbeddingProcessor`: parallel batch embedding with configurable batch size

`src/tools/` — LLM function-calling system:
- `registry.py` — tool registration with JSON schemas
- `executor.py` — manages the Ollama tool-call loop (multi-turn until final response)
- `builtin.py` — built-in tools: document search, calculator, datetime
- `plugin_loader.py` — loads `.py` tool plugins from the `plugins/` directory at startup

`src/cache/` — multi-backend caching (Redis or in-memory) with TTLs for embeddings and query results.

`src/gpu_monitor.py` — standalone `GpuMonitor` class. Detects NVIDIA GPUs via `nvidia-smi` and AMD via `rocm-smi`, TTL-caches results (30 s). Injected into `OllamaClient` via `self._gpu_monitor`; not coupled to the HTTP client.

`src/llm_client.py` — `LiteLLMClient` (cloud fallback via LiteLLM, lazy import); `ModelClient` Protocol. Active when `CLOUD_FALLBACK_ENABLED=true`.

`src/api_docs.py` — Swagger UI / OpenAPI spec configuration; serves interactive docs at `/api/docs/`.

`src/types.py` — `LocalChatApp` typed Flask subclass; silences Pyright attribute-access warnings without `# type: ignore`.

**Config** (`src/config.py`): all parameters loaded from `.env`. Key RAG defaults: `CHUNK_SIZE=1200`, `TOP_K_RESULTS=20`, `MIN_SIMILARITY_THRESHOLD=0.30`, `SEMANTIC_WEIGHT=0.70`. Key Ollama vars: `OLLAMA_BASE_URL` (default `http://localhost:11434`), `OLLAMA_NUM_GPU` (-1 = all layers), `OLLAMA_NUM_CTX` (8192 tokens — also used as the context character budget via `MAX_CONTEXT_LENGTH`).

---

## Test Structure

Tests use pytest with markers defined in `pytest.ini`:
- `unit` — fast, isolated, no external services
- `integration` — requires running services
- `db` — requires PostgreSQL
- `ollama` — requires Ollama
- `slow`, `rag`, `api`, `validation`, `sanitization`, `exceptions`

Shared fixtures are in `tests/conftest.py`. Test utilities in `tests/utils/`. All tests use `src/app_factory.py`'s `create_app(testing=True)` — never import from `src/app.py` directly (that file doesn't exist; the factory is the only app creation path).

---

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
| `src/ollama_client.py` | `OllamaClient` singleton — `/api/chat` (stream + non-stream), `/api/embed`+`/api/embeddings` fallback, model CRUD, vision (`describe_image`), GPU info; TTL-cached model list (60 s) and running-models (5 s); background cache refresh thread |
| `src/tools/executor.py` | LLM tool-call loop |
| `src/routes/api_routes.py` | Chat (SSE), status; sets `g.model`, `g.chunks_retrieved`; emits `sources` in `done` |
| `src/routes/memory_routes.py` | Conversation CRUD, export, document-filter endpoints |
| `src/routes/document_routes.py` | Document upload, delete, list; SSE progress stream |
| `src/routes/model_routes.py` | Ollama model list, pull, delete, active-model management |
| `src/routes/settings_routes.py` | Settings UI + admin ops dashboard (`/api/settings`, `/api/admin/stats`) |
| `src/routes/longterm_memory_routes.py` | Long-term memory CRUD and manual trigger endpoints |
| `src/routes/web_routes.py` | Serves the frontend SPA (`/`) and static assets |
| `src/routes/error_handlers.py` | Flask error handler registration (4xx / 5xx JSON responses) |
| `src/utils/logging_config.py` | `JsonFormatter` + `RequestIdFilter`; `LOG_FORMAT=json` for structured output |
| `src/utils/request_id.py` | X-Request-ID middleware; per-request access log via `_access_logger` |
| `src/security.py` | JWT, rate limiting, CORS |
| `src/models.py` | Pydantic request/response models |
| `src/types.py` | `LocalChatApp` typed Flask subclass for static-analysis clarity |
| `src/api_docs.py` | OpenAPI/Swagger UI configuration; docs served at `/api/docs/` |
| `src/llm_client.py` | `LiteLLMClient` cloud-fallback adapter; `ModelClient` Protocol |
| `src/agent/aggregator.py` | `AggregatorAgent` — parallel tool dispatch, retry, dedup; `run(query, plan, tools)` |
| `src/agent/tool_router.py` | `ToolRouter` — maps tool names to MCP or direct handlers; MCP-aware with fallback |
| `src/agent/result.py` | `AgentResult`, `ToolCall` dataclasses; `to_trace_dict()` for SSE + DB storage |
| `src/agent/models.py` | `ModelRegistry` — env-driven model class → Ollama ID mapping; `summary()` |
| `src/agent/router.py` | `ModelRouter` — rule-based classifier (VISION/CODE/LARGE/FAST/BASE); < 1 ms |
| `src/db/feedback.py` | `FeedbackMixin` — `answer_feedback` + `chunk_stats` CRUD; `get_feedback_stats()`, `export_feedback_pairs()` |
| `src/db/entities.py` | `EntitiesMixin` — knowledge-graph entity/relation CRUD (GraphRAG) |
| `src/db/memories.py` | `MemoriesMixin` — long-term memory CRUD + vector search (`memories` table) |
| `src/routes/feedback_routes.py` | `POST /api/feedback` (submit rating), `GET /api/feedback/stats` (admin metrics) |
| `src/db/workspaces.py` | `WorkspacesMixin` — workspace CRUD, `list_workspaces()` with doc/conversation counts |
| `src/routes/workspace_routes.py` | `GET/POST /api/workspaces`, `GET/PUT/DELETE /api/workspaces/<id>`, `GET /api/workspaces/active`, `POST /api/workspaces/switch` |
| `src/connectors/base.py` | `BaseConnector` ABC + `DocumentSource`, `DocumentEvent`, `EventType` dataclasses |
| `src/connectors/local_folder.py` | `LocalFolderConnector` — stat-based folder watcher, poll/fetch |
| `src/connectors/s3_connector.py` | `S3Connector` — S3/MinIO/R2 via boto3 (optional dep) |
| `src/connectors/webhook.py` | `WebhookConnector` — receives push events via HTTP POST |
| `src/connectors/registry.py` | `ConnectorRegistry` singleton — maps types to classes, manages live instances |
| `src/connectors/worker.py` | `SyncWorker` daemon thread — polls connectors, ingests changes, logs sync history |
| `src/db/connectors.py` | `ConnectorsMixin` — connector CRUD, sync log, `delete_document_by_filename` |
| `src/routes/connector_routes.py` | Connector REST API + webhook receiver endpoint |
| `src/rag/doc_type.py` | `DocType` enum, `DocTypeClassifier`, `ChunkerRegistry` (extension → loader/chunker) |
| `src/rag/planner.py` | `QueryPlanner` — decomposes query into `QueryPlan` (intent + sub-questions) |
| `src/rag/feedback_pipeline.py` | Weekly export + cross-encoder fine-tune; versioned output, `promote_model`, `rollback_model` |
| `src/rag/reranker.py` | `RerankerModel` singleton — loads fine-tuned cross-encoder, falls back to base model |
| `src/graph/extractor.py` | spaCy-based named entity extraction from document chunks |
| `src/graph/expander.py` | `QueryExpander` — 1-hop graph expansion of BM25 query terms |
| `src/memory/extractor.py` | Extracts memorable facts from conversation turns |
| `src/memory/retriever.py` | `MemoryRetriever` — vector-searches memories, injects top-K into LLM prompt |
| `src/performance/batch_processor.py` | `BatchEmbeddingProcessor` — parallel batch embedding, configurable batch size |
| `src/mcp_client.py` | MCP HTTP client; `MCPClientRegistry` singleton + per-server `CircuitBreaker` |
| `mcp_servers/base.py` | `MCPServer` base class — JSON-RPC 2.0 dispatcher (tools/list, tools/call, health) |
| `mcp_servers/local_docs/server.py` | Local-docs MCP server — wraps retrieval + `format_context_for_llm`; gunicorn port 5001 |
| `mcp_servers/web_search/server.py` | Web-search MCP server — wraps `WebSearchProvider`; gunicorn port 5002 |
| `mcp_servers/cloud_connectors/server.py` | Cloud-connectors MCP server — routes through live connector registry; gunicorn port 5003 |
| `src/db/users.py` | `UsersMixin` — user CRUD, PBKDF2 password hashing |
| `src/db/oauth_tokens.py` | `OAuthTokensMixin` — Fernet-encrypted OAuth token storage (upsert/get/delete) |
| `src/routes/auth_routes.py` | User management REST API (admin) + self-service password change |
| `src/routes/oauth_routes.py` | Microsoft OAuth2 authorization-code flow (`/api/oauth/microsoft/*`) |
| `src/connectors/microsoft_auth.py` | `get_valid_access_token` — checks expiry, refreshes via Graph token endpoint |
| `src/connectors/sharepoint_connector.py` | SharePoint document library connector — Graph API delta queries |
| `src/connectors/onedrive_connector.py` | OneDrive personal drive connector — Graph API delta queries |
| `helm/localchat/` | Full Helm chart: app + PostgreSQL + Redis StatefulSets + MCP server Deployments |
| `docs/DEPLOYMENT.md` | Helm install/upgrade/rollback guide, secrets management |
| `tests/conftest.py` | Shared pytest fixtures |
| `docker-compose.yml` | Full stack: app + PostgreSQL + Redis + Ollama; `--profile mcp` adds 3 domain servers |
| `.github/dependabot.yml` | Dependabot: weekly pip + GitHub Actions updates, auto-assigned to `jwvanderstam`, labels `dependencies`/`ci` |
| `docs/grafana-dashboard.json` | Importable Grafana dashboard (uid `localchat-rag-v1`, 7 panels) |

> **Maintenance rule:** When adding or removing a module, update the Key Files table above in the same PR.
