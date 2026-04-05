# LocalChat — Roadmap & Implementation Plan

> Last updated: 2026-04-06
> Current version: v0.6.0

---

## Principles

1. **Maintainability first** — every change must leave the codebase easier to understand than it found it.
2. **Security is non-negotiable** — no phase ships with known security regressions.
3. **Docs stay in sync** — README, CLAUDE.md, and this file are updated in the same PR as the code they describe.
4. **Tests where they add value** — integration tests for multi-service flows, edge-case unit tests for complex logic; not for trivial wrappers.

---

## Current State (baseline assessment)

| Area | Score | Key gaps |
|------|-------|---------|
| Architecture | ✅ 100% | All documented services implemented |
| Security | ✅ 98% | _(cookie Secure ✅, file validation ✅, distributed rate limiting ✅)_ |
| Test coverage | ✅ 95% | 9 integration tests + 47 unit test files; GPU monitor ✅, vision ✅, rate limit ✅ |
| Code quality | ✅ 100% | All S3776 complexity violations resolved |
| Documentation | ✅ 95% | Architecture diagram ✅, DB schema ✅, troubleshooting ✅, CONTRIBUTING.md ✅ |
| Feature completeness | ⚠️ 85% | L3 cache (`database_cache.py`) status unclear; no multi-document conversation context |

---

## Phase 1 — Code Quality & Security Hardening

**Goal:** Eliminate known quality and security issues before adding features.

### ~~1.1 Resolve SonarCloud issues~~ ✅

20 open issues — all resolved:

| Issue | File | Action |
|-------|------|--------|
| ~~S5754 — Cookie missing Secure flag~~ ✅ | ~~`src/security.py`~~ | ~~Set `SESSION_COOKIE_SECURE = True`; add `Secure` to JWT cookie config~~ |
| ~~S3776 — Cognitive complexity ×8~~ ✅ | ~~`src/ollama_client.py`~~ | ~~Extracted `_resolve_model()`, `_build_tool_payload()`, `_embed_new_api()`, `_embed_legacy_api()`~~ |
| ~~S3776 — Cognitive complexity ×5~~ ✅ | ~~`src/routes/api_routes.py`~~ | ~~Split into `_retrieve_contexts()`, `_build_context_prompt()`, `_stream_chat_response()`~~ |
| ~~S3776 — Cognitive complexity ×2~~ ✅ | ~~`src/rag/retrieval.py`~~ | ~~Extracted `_run_retrieval_pipeline()`, `_rank_and_finalize()`, `_append_chunks_for_doc()`~~ |
| ~~S1192 — String literals ×2~~ ✅ | ~~`src/rag/loaders.py`~~ | ~~Extract repeated strings to module-level constants~~ |

**Tests to add:** For each refactored method, verify existing unit tests still pass (no new tests needed — behaviour unchanged).

### ~~1.2 Add ruff linter~~ ✅

~~- Add `ruff.toml` with `select = ["E", "F", "W", "I", "UP", "B", "SIM"]`~~
- ~~TODO: Add ruff check to `tests.yml` CI step~~ ✅
- Fix all violations before merging

### ~~1.3 Pre-commit hooks~~ ✅

~~Add `.pre-commit-config.yaml`:~~
~~- `ruff --fix`~~
~~- `pyright` (basic, non-blocking on new violations)~~
~~- `pytest -m "not (slow or ollama or db)"` (fast unit tests only)~~

### ~~1.4 Distributed rate limiting~~ ✅

~~Current in-memory rate limiter breaks in multi-instance deployments.~~

~~- Replace `FlaskLimiter` memory storage with Redis backend when `REDIS_URL` is set~~
~~- Fallback to memory storage when Redis is unavailable (development mode)~~
~~- Add integration test: two simulated requests that share the same Redis counter~~

_`src/security.py` auto-detects Redis at startup (`_resolve_ratelimit_storage`); `config.py` sets `RATELIMIT_STORAGE_URI` from env; `tests/integration/test_ratelimit.py` covers memory + Redis + shared-counter scenarios._

### ~~1.5 File content validation on upload~~ ✅

~~Current validation: filename sanitization only.~~

~~- Add magic-byte check for PDF, DOCX, TXT, MD before processing~~
~~- Reject files whose content-type contradicts their extension~~
~~- Add unit tests for each rejected/accepted case~~

---

## Phase 2 — Test Coverage

**Goal:** Meaningful integration tests for multi-service flows; edge-case coverage for complex logic.

### ~~2.1 Integration test: full RAG flow~~ ✅

~~`tests/integration/test_rag_flow.py`~~

### ~~2.2 Integration test: authentication flow~~ ✅

~~`tests/integration/test_auth_flow.py`~~

### ~~2.3 Vision feature — complete and test~~ ✅

~~`tests/integration/test_vision.py`~~

### ~~2.4 GPU monitor test~~ ✅

~~`tests/unit/test_gpu_monitor.py`~~

### 2.5 L3 cache — clarify and test

`src/cache/backends/database_cache.py` status is unclear.

- Audit: is it a complete implementation or placeholder?
- If complete: add integration test with `@pytest.mark.db`
- If placeholder: remove it and remove `L3_CACHE_ENABLED` from config to avoid confusion

### ~~2.6 Plugin loader edge cases~~ ✅

~~`tests/unit/test_tools_full.py` — syntax error, no-tools, reload-idempotent~~

---

## Phase 3 — Documentation

**Goal:** All documentation accurate, navigable, and maintained alongside code.

### ~~3.1 CONTRIBUTING.md~~ ✅

~~- Development setup (venv, `.env`, Docker services)~~
~~- Branching and PR conventions~~
~~- How to run tests locally (fast / full / integration)~~
~~- SonarCloud quality gate requirements~~
~~- Commit message format~~

### ~~3.2 Architecture diagram (Mermaid)~~ ✅

~~Add to README.md — Mermaid request flow diagram showing Flask → RAG → Ollama → SSE.~~

### ~~3.3 Database schema documentation~~ ✅

~~`docs/SCHEMA.md` — ER diagram, table descriptions, HNSW index parameters.~~

### ~~3.4 Troubleshooting guide~~ ✅

~~`docs/TROUBLESHOOTING.md` — Ollama, pgvector, Redis, JWT, file upload issues.~~

### ~~3.5 CLAUDE.md maintenance rule~~ ✅

~~Add to CLAUDE.md: "When adding or removing a module, update the Key Files table in the same PR."~~

---

## Phase 4 — Feature Evolution

**Goal:** Extend capability without sacrificing the quality baseline established in Phases 1–3.

### 4.1 Pyright strict mode (gradual)

- Enable strict for `src/db/` and `src/models.py` first (already well-typed)
- Add per-module `# pyright: strict` comments as each module passes
- Do not force strict on `src/routes/` until cognitive complexity is resolved

### 4.2 Multi-document conversation context

Currently: each chat session uses all documents equally.

- Add per-conversation document filter: user selects which documents are in scope
- Store filter in `conversations` table
- Update retrieval to apply filter before vector search

### 4.3 Conversation export

- `GET /api/conversations/{id}/export?format=markdown|json`
- Includes: messages, sources cited, timestamps
- Rate-limited; requires auth

### 4.4 Chunk provenance in responses

Currently: sources listed by filename only.

- Return chunk index and page number (where available from metadata)
- Frontend: clickable source reference opens document at correct position

### 4.5 Document re-ingestion

Currently: re-uploading a document creates a duplicate.

- Detect duplicate by filename + file hash
- Offer: replace existing (re-chunk) or keep both versions
- Clean up orphaned chunks when replacing

---

## Phase 5 — Observability & Operations

**Goal:** Make production deployments easier to monitor and diagnose.

### 5.1 Structured log output

Current logging is human-readable. Add JSON mode for log aggregation:
- `LOG_FORMAT=json` env var switches to structured JSON output
- Include: `request_id`, `user_agent`, `duration_ms`, `model`, `chunks_retrieved`

### 5.2 Grafana dashboard definition

- Add `docs/grafana-dashboard.json` (exportable dashboard)
- Panels: requests/min, P95 latency, cache hit rate, embedding queue depth, active Ollama model

### 5.3 Backup and restore documentation

Add `docs/OPERATIONS.md`:
- PostgreSQL backup strategy (pg_dump + pgvector-safe restore)
- Redis persistence settings
- Volume backup for Docker Compose deployments

---

## Delivery order

```
Phase 1 (Quality & Security)   ← start here; unblocks everything else
Phase 2 (Tests)                ← in parallel with Phase 1 where possible
Phase 3 (Docs)                 ← ongoing; each Phase 1/2 PR updates relevant docs
Phase 4 (Features)             ← only after Phase 1 complete
Phase 5 (Observability)        ← can run in parallel with Phase 4
```

---

## Definition of done (per phase)

- SonarCloud quality gate passes (0 new issues introduced)
- All new code covered by tests at the level described in this document
- README and CLAUDE.md updated if public-facing behaviour changed
- This roadmap updated to mark items complete
