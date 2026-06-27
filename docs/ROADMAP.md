# ROADMAP — v3.0

> **Status:** Active
> **Predecessor:** v2.0 completed May 2026 (dual-stack migration, JWT revocation, Alembic migrations, CI integration tests, chat.js ES modules).

v3.0 targets six workstreams: **repository hygiene & single-framework consolidation** (a clean, remnant-free codebase on one web framework, FastAPI), **data integrity hardening** (Clark-Wilson compliance), **role-based access control** (admin / user / viewer), **two-tier knowledge architecture** (Global Knowledge Base + workspace-scoped projects), **environment-aware model management** (only offer models that fit the hardware), and **a plugin contract** that lets plugins extend the application without destabilising the core.

The guiding constraint across all of them: **the core stays stable and clean.** Plugins may request services and hooks; they may never define core interfaces or become a dependency the core cannot build without. See the "Plugin Contract" section in `CLAUDE.md` and [`.claude/rules/plugins.md`](.claude/rules/plugins.md).

---

## Initiative 1 — Repository Hygiene and Web-Stack Coherence

Make the repository clean, professional, and free of migration-era remnants, and finish consolidating onto a single web framework (FastAPI). Sequenced first: one fix (the `.claude/` ignore rule) blocks the Plugin Contract initiative, and clearing the ground keeps every later diff reviewable.

> **Status legend:** ✅ done this session · 🔬 needs investigation before acting · ⬜ not started. Items marked ✅ are merged to `main`.

---

### HK-1 — Tutorial-era remnant removal ✅ (done, committed)

Verified by inspection and fixed on `chore/repo-hygiene`:
- Stripped `# WEEK n` / `Phase 4.5` markers from `.env.example` and five test docstrings; removed the orphaned ASCII underlines left behind.
- `.gitignore`: replaced the wholesale `.claude/` ignore with a precise rule — track `.claude/rules/`, keep `worktrees/` and `settings.local.json` ignored. **This unblocks the Plugin Contract work** (Initiative 6).
- Added `.claude/rules/plugins.md` (the plugin contract) and `.claude/rules/python.md` (was untracked); added the Plugin Contract section to `CLAUDE.md`.

> Reality check: the repo was already in good shape. No stray `.DS_Store`, no `_old`/`_backup` files, no leaked `.env`, no tracked build artefacts. The original "shabby / full of garbage" concern was mostly unfounded — the genuine remnants were the WEEK markers and the items below.

---

### HK-2 — Commit hygiene ✅ (verified — no action needed)

The originally-flagged "shabby commit messages" concern did not survive inspection. `git log` shows consistent Conventional Commits with scopes (`fix(security)`, `docs(roadmap)`, `deps`), clean Dependabot handling, and an already-done dead-doc cleanup (`734d103`). 

- **Going forward only:** keep the existing convention; optionally add a commit-message lint to CI (see HK-3).
- **Never rewrite `main` history** — it is good, and rewriting shared history is destructive.

---

### HK-3 — Config consolidation ✅ (done, committed)

`ruff.toml` and `pytest.ini` absorbed into `pyproject.toml` (`[tool.ruff]`, `[tool.pytest.ini_options]`, `[tool.coverage.*]`). `sonar-project.properties` left at root (SonarCloud expects it there). Dependencies remain in `requirements.txt`; PEP 621 metadata deferred — adding it would require a full package restructure with no current benefit.

Doc files moved to `docs/`: `MIGRATIONS.md`, `INTEGRATION_TESTS.md`, `ROADMAP.md`. Root now holds only entrypoints, tooling config, and container/infra files.

---

### HK-4 — Single-framework consolidation: eliminate Flask ✅ (done, merged #105)

> **Outcome:** Flask removed from all of `src/` and `requirements.txt`. The dead `init_monitoring`/`init_request_id` were not blindly deleted — metrics and request-id were **ported** to FastAPI middleware (`MetricsMiddleware`, `RequestIdMiddleware`), filling the observability gap the migration had left. MCP servers already on FastAPI from the earlier port.

The dual-stack migration (Flask → FastAPI) stalled mid-way. The goal is one framework. Progress and remaining work:

**Done this session (committed on `refactor/mcp-servers-fastapi`):**
- Ported the three MCP domain servers (`local_docs`, `web_search`, `cloud_connectors`) and their shared `mcp_servers/base.py` from Flask/WSGI to FastAPI/ASGI. JSON-RPC 2.0 contract preserved and verified in-container (health, tools/list, tools/call, unknown tool/method, malformed body, error-leak guard all behave identically). `docker-compose.yml` switched from gunicorn to uvicorn for all three.

**Remaining — and this needs investigation first, not blind deletion:** 🔬

Four `src/` files still import Flask: `monitoring.py`, `utils/request_id.py`, `utils/logging_config.py`, `utils/workspace.py`. Call-site analysis shows `init_monitoring()` and `init_request_id()` have **no live caller** — they were wired into the deleted `app_factory.py`. **But** the current FastAPI app (`app_fastapi.py`) has only a security middleware — **no Prometheus metrics and no request-id middleware**. 

This means the choice per capability is **port-or-delete, decided by evidence**:
- If a capability genuinely lost its home in the migration (likely the case for metrics and request-id tracing) → **port it to FastAPI middleware**, because deleting it silently drops observability the project used to have. This is filling a gap, not cleanup.
- If a capability is truly redundant (FastAPI already covers it elsewhere) → **delete the dead Flask version**.

**Steps:**
1. Confirm whether Prometheus metrics and request-id tracing exist anywhere in the live FastAPI path. (Preliminary finding: they do not.)
2. For each missing capability, port to FastAPI middleware (`@app.middleware("http")` for request-id; an ASGI metrics middleware or `prometheus-fastapi-instrumentator` for metrics).
3. For each genuinely redundant Flask helper, delete it and its dead tests.
4. Reconcile `utils/workspace.py` (the dual Flask/FastAPI helper) to FastAPI-only.
5. Once no `src/` file imports Flask: remove `Flask`, `Flask-JWT-Extended`, `Flask-Limiter`, `Flask-CORS` from `requirements.txt`, and delete the migration-era "remove once ported" comment. Confirm JWT/rate-limiting/CORS have FastAPI equivalents already in the live app before removing their Flask packages.

**Acceptance:** `git ls-files | xargs grep -l "import flask\|from flask"` returns nothing under `src/`; Flask packages gone from `requirements.txt`; metrics and request-id verified working on the FastAPI app; full test suite green.

> Why this is the right call: the Flask remnants are not a deliberate second-framework choice — they are dead wiring from an unfinished migration. The only real risk is deleting a capability that lost its home rather than porting it; step 1 exists precisely to catch that.

---

### HK-5 — Documentation rot: sync rules and overview with FastAPI reality ✅ (done, merged #105)

The dual-stack migration left several docs describing the old Flask structure (`src/routes/`, `src/app_factory.py` — both gone):
- `.claude/rules/architecture.md` — describes Flask blueprints, `app_factory.py`, Flask SSE. Rewrite to the real structure: `src/routes_fastapi/` router-per-domain, `create_app()` in `app_fastapi.py` + `bootstrap_app()` in `app_bootstrap.py`, and the subsystems the current doc omits entirely (`agent/`, `graph/`, `memory/`, `performance/`). **Done:** rewritten to the real structure (verified — `architecture.md` now describes `routes_fastapi/`, `app_fastapi.py`, and async generators; `overview.html` has no Flask references).
- `.claude/rules/testing.md` — remove/relabel the "Flask routes (legacy `src/routes/`)" block referencing `create_app(testing=True)`.
- `.claude/rules/file-map.md` and `CLAUDE.md` — fix stale `app_factory.py` / `src/routes/` references.
- `templates/overview.html` — user-facing page still shows "Flask App", "Flask App Factory: `src/app_factory.py`", and an Nginx→Flask architecture diagram. Highest-visibility rot (users see it). Update to FastAPI.
- `docs/DEPLOYMENT.md` — `SECRET_KEY` described as "Flask session signing key"; verify against the FastAPI app and correct.

Sequence HK-5 **after** HK-4 so the docs describe the post-consolidation reality, not a moving target.

---

### HK-6 — Regression guard (the hygiene IVP) ✅ (done, merged #105)

A `repo-hygiene` CI job, required on every PR to `main`, failing on:
- tracked files matching `.gitignore` patterns (artefacts that slipped in),
- presence of `.DS_Store`, `Thumbs.db`, `*.bak`, `*.swp`,
- a tracked `src/` file importing Flask (locks in the single-framework outcome of HK-4),
- (warning-level) commit messages not matching the Conventional Commits prefix.

This is the integrity-verification procedure for cleanliness and for single-framework: once clean, the job keeps it clean without relying on discipline.

**Out of scope:** rewriting `main` history; module renames or code moves (refactoring, kept in separate diffs).

**Files across HK:** `.gitignore` ✅, `.env.example` ✅, `.claude/rules/*` (✅ plugins/python; ⬜ architecture/testing/file-map), `CLAUDE.md` (✅ plugin section; ⬜ flask refs), `mcp_servers/*` ✅, `docker-compose.yml` ✅, `src/monitoring.py` + `src/utils/*` ⬜, `requirements.txt` ⬜, `templates/overview.html` ⬜, `docs/DEPLOYMENT.md` ⬜, new `pyproject.toml` ✅, `.github/workflows/` ⬜.

---

### Web-stack coherence: sync/async (HK-7 to HK-10)

Eliminating Flask (HK-4 ✅) gave one framework; it did not make the async/sync boundary coherent. FastAPI is async, but the two heaviest I/O paths are still sync (`psycopg`, `requests`), and handlers split ~32 async / ~66 sync by accident, not design. These tickets make the boundary deliberate and lay the cheap foundations that keep a future scale-up (sovereign RAG platform, many concurrent users) from becoming a codebase-wide rewrite.

**Framing — foundation, not premature optimisation.** The decision rule is *foundation or blockade at scale*, not *does it block measurably today*. A load test on a single GPU would mislead: the VRAM budget (MM-1) saturates after 1-2 concurrent generations, so the event-loop never becomes the visible bottleneck locally. That result would say "async doesn't matter" — true today, false the moment inference runs on shared/remote infrastructure. Measurement informs priority; it does not gate the work.

> **Sequencing within Initiative 1:** HK-4 (remove Flask) is done. HK-7, HK-8, HK-9 are cheap and act on the remaining FastAPI stack; HK-10 is deferred behind an explicit scale trigger.

---

### HK-7 — Seal the data-access boundary ✅ (done, merged #116)

The real insurance against async's contagion. Async is "colour": making the DB async forces every caller up the stack to become async too, and that call-graph **grows with the codebase** — so deferring the conversion makes it *more* expensive over time, not less. The fix is not "go async now" but to ensure all DB access already flows through the `db/` layer, so the async choice lives behind one boundary instead of every call-site.

Full coupling audit completed (#116):
- Confirmed all route handlers and RAG code reach the DB exclusively through `src/db/` mixins — no stray connection calls outside the layer.
- `DocumentProcessor` and `retrieve_context` now receive `db` and `ollama_client` by constructor injection rather than importing module-level singletons, making them independently testable.
- `ConnectorRegistry` access in `connector_routes.py` moved to `request.app.state.connector_registry` (was a direct module import).
- `RetrievalResult` named tuple replaces bare tuples returned by `retrieve_context()` — typed, readable, future-proof.
- `AppState` I/O extracted behind a `state_file` parameter — test runs skip all file I/O; production path unchanged.
- `ChatService` extracted from `api_routes.py` into `src/services/chat.py` — route handlers are now thin HTTP plumbing; all business logic in the service layer.
- Ollama liveness check and running-models cache made non-blocking: background daemon threads own all live HTTP; request path reads only cached values, eliminating head-of-line blocking when Ollama is loading a model.

---

### HK-8 — Port the Ollama client to async ✅ (done, merged)

`requests.Session` → `httpx.Client` (sync admin/embedding) + `httpx.AsyncClient` (async inference). The three inference methods (`generate_chat_response`, `generate_chat_completion`, `test_model`) are now `async def`. `describe_image` kept sync to avoid async contagion into the document ingest pipeline (`rag/loaders.py` → `rag/processor.py`), which must remain synchronous.

Async contagion cascaded up through `ToolExecutor.execute`, `QueryPlanner.plan`, `MemoryExtractor.extract/_call_llm`, and all route handlers that call them (`api_routes.py`, `model_routes.py`, `longterm_memory_routes.py`). `pytest-asyncio` added (`asyncio_mode = "auto"` in `pyproject.toml`) so `async def` test functions run without explicit markers. All affected unit and integration tests updated to use `AsyncMock` for awaitable mocks and async generator helpers for streaming mocks.

---

### HK-9 — Make the handler boundary intentional ✅ (done, merged)

The async contagion from HK-8 established a clean, deliberate boundary. Chat SSE handlers (`_generate_sse`, `_retrieve_plan_and_memory`, `_stream_chunks_with_fallback`), model testing (`test_model` route), and long-term memory extraction are `async def` — they genuinely await `OllamaClient` calls. Admin/sync handlers that don't do async I/O remain `def` (FastAPI runs them in a threadpool). No `async def` handler makes a direct blocking call.

---

### HK-10 — Database async ⬜ 🔬 (deferred; scale-triggered; largest/riskiest)

Explicitly **not now**. Verified still sync (`psycopg` + `ConnectionPool`). Because HK-7 seals the boundary, this becomes a one-layer change whenever it triggers — regardless of how much the app has grown.

- **Trigger (not a date):** real multi-user adoption **and** inference running off the local GPU, so the event-loop becomes the actual bottleneck. *Make this concrete before relying on it — e.g. "more than N concurrent users" or "inference moved to separate infra" — or it becomes a wish that never fires.*
- `psycopg` async mode (`AsyncConnection`/`AsyncConnectionPool`) or evaluate `asyncpg`; convert the hot read path (retrieval, chat) only — admin/CRUD stays sync.
- **Acceptance:** retrieval no longer blocks the event-loop under load; tests green.

**Out of scope:** blanket "everything async" (rejected — async added only where it earns its place); `ThreadPoolExecutor` fan-out and streaming SSE (already correct, untouched).

---

## Initiative 2 — Clark-Wilson Compliance

The Clark-Wilson integrity model requires that no delete operation leaves referentially-linked data in an inconsistent state. The current codebase has ~12 hard-delete operations across CDI tables. All of them will be converted to soft-delete state transitions.

**CDIs in scope:** `documents`, `document_chunks`, `conversations`, `messages`, `users`, `workspaces`, `memories`, `annotations`, `connectors`

---

### CW-1 — Document soft-delete (pilot ticket)

**Why first:** Documents are the highest-integrity CDI. Chunk IDs are embedded in citation references inside conversation history. A hard-deleted document currently produces ghost citations — the conversation record references a chunk that no longer exists, and no IVP can repair it.

**Schema changes (Alembic migration):**
```sql
ALTER TABLE documents        ADD COLUMN deleted_at  TIMESTAMPTZ;
ALTER TABLE documents        ADD COLUMN deleted_by  UUID REFERENCES users(id);
ALTER TABLE document_chunks  ADD COLUMN deleted_at  TIMESTAMPTZ;
```

**Behaviour changes:**
- `DELETE /api/documents/{id}` → sets `deleted_at`, `deleted_by`; does not touch chunks immediately
- All document SELECT queries → add `WHERE deleted_at IS NULL`
- Chunk retrieval in RAG → add `WHERE deleted_at IS NULL` to similarity search
- Citations → resolve against all chunks (including soft-deleted) so existing conversation history remains valid; UI can surface a "source retired" indicator
- New admin endpoint `DELETE /api/documents/{id}/purge` → hard-deletes only if no conversation cites any chunk from this document; returns 409 otherwise
- File on disk → moved to a `uploads/retired/` sub-directory on soft-delete; physically removed only on purge

**Tests required:**
- Unit: `delete_document` sets `deleted_at`, does not remove rows
- Unit: `purge_document` raises precondition error when citations exist, succeeds when none
- Integration: upload → chat (creates citation) → soft-delete → confirm RAG excludes it → confirm citation still resolves → purge blocked by citation
- Integration: upload → soft-delete → purge succeeds when no citations

**Files:** `src/db/documents.py`, `src/routes_fastapi/document_routes.py`, `src/rag/retrieval.py`, Alembic migration

---

### CW-2 — Full CDI soft-delete sweep

Apply the same pattern to all remaining CDIs. Each sub-item is one migration + one mixin change + route update.

| Sub-ticket | Table(s) | Hard-delete locations today |
|---|---|---|
| CW-2a | `conversations`, `messages` | `db/conversations.py` — `delete_conversation`, `clear_conversations` |
| CW-2b | `users` | `db/users.py` — `delete_user` |
| CW-2c | `workspaces` | `db/workspaces.py` — `delete_workspace` |
| CW-2d | `memories` | `db/memories.py` — `delete_memory`, `clear_memories` |
| CW-2e | `annotations` | `db/annotations.py` — `delete_annotation` |
| CW-2f | `connectors` | `db/connectors.py` — `delete_connector`, `delete_document_by_filename` |

**Shared pattern for each sub-ticket:**
1. Alembic migration: add `deleted_at TIMESTAMPTZ`, `deleted_by UUID` columns
2. Mixin: replace `DELETE FROM` with `UPDATE ... SET deleted_at = NOW(), deleted_by = %s`
3. All SELECT queries in that mixin: add `WHERE deleted_at IS NULL`
4. Route: delete endpoint soft-deletes; purge endpoint (admin-only) hard-deletes with precondition
5. Unit tests for both operations

**Cross-cutting concern — purge preconditions:**

| CDI | Purge blocked when... |
|---|---|
| conversation | conversation is shared across workspaces or cited in a memory |
| user | user owns documents, workspaces, or has active conversations |
| workspace | workspace contains documents or conversations |
| memory | memory is referenced in a conversation context |
| annotation | annotation is included in an export |
| connector | connector has synced documents that are active |

---

### CW-3 — Audit log

Once soft-delete is in place everywhere, a single `audit_log` table can record all CDI state transitions (create, update, retire, purge) with actor, timestamp, and before/after state snapshot. This is the IVP layer — a query over `audit_log` can reconstruct the integrity state at any point in time.

**This ticket is a stretch goal for v3.0 and may slip to v4.0.**

---

## Initiative 3 — Role-Based Access Control

The current system has two application-level roles: `admin` and `user`. A `viewer` role is needed for read-only access — consumers of the knowledge base who should not be able to modify it.

---

### RBAC-1 — Viewer role definition and enforcement

**Proposed role matrix** *(scope to be confirmed before implementation)*

| Capability | admin | user | viewer |
|---|---|---|---|
| Chat / query the knowledge base | ✓ | ✓ | ✓ |
| View document list | ✓ | ✓ | ✓ |
| View own conversation history | ✓ | ✓ | ✓ |
| Upload documents | ✓ | ✓ | — |
| Delete (soft) own documents | ✓ | ✓ | — |
| Manage own conversations | ✓ | ✓ | — |
| Change own password | ✓ | ✓ | — |
| Create / manage workspaces | ✓ | ✓ | — |
| View system settings | ✓ | — | — |
| Change RAG parameters | ✓ | — | — |
| User management | ✓ | — | — |
| Purge (hard-delete) any CDI | ✓ | — | — |
| Trigger reranker training | ✓ | — | — |

**Key design decisions to confirm:**
- Can a viewer see *all* documents in a workspace, or only documents uploaded by others that are explicitly shared?
- Can a viewer export conversations they participated in?
- Is the viewer role workspace-scoped (a user can be a viewer in workspace A and a user in workspace B) or global?

**Implementation:**
- Add `"viewer"` as valid role value in `src/db/users.py` `create_user` and `update_user`
- Add `require_role_dep(min_role: Literal["viewer", "user", "admin"])` to `src/security_fastapi.py`
- Audit every route handler and replace `require_admin_dep` / open access with the appropriate `require_role_dep` call
- Update `POST /api/users` validation: accept `"viewer"` in addition to `"admin"` and `"user"`
- Update JWT claims: `role` claim carries the user's global role
- UI: hide upload, delete, and settings controls for viewer-role sessions

> **Note for the plugin contract:** `require_role_dep` is the mechanism behind the `identity` service that plugins consume (`require_role(min_role)`). RBAC-1 builds it for core routes; the plugin contract (PC-1) exposes it as a service. Plugins never read JWT claims directly.

**Files:** `src/security_fastapi.py`, `src/db/users.py`, `src/routes_fastapi/auth_routes.py`, all route modules, `static/js/`

**Tests required:**
- Unit: `require_role_dep("user")` rejects viewer token
- Unit: `require_role_dep("viewer")` accepts viewer, user, and admin tokens
- Integration: viewer can call `GET /api/chat` but receives 403 on `POST /api/documents/upload`
- Integration: admin can promote a user to viewer and back

---

### RBAC-2 — Route permission audit

A systematic pass over every route to assign the correct minimum role. This is separate from RBAC-1 (which adds the mechanism) — this ticket applies it consistently and documents the result in a permission matrix in `docs/`.

---

## Initiative 4 — Global Knowledge Base (GKB)

### Background

Workspaces are project containers — isolated knowledge silos scoped to a team and a deliverable. But certain plugins (pricing, competitive intelligence, risk scoring) need to learn from patterns that emerge *across* all projects, not just within one. A single-tier workspace model cannot serve both needs.

**The two-tier pattern:**

```
┌─────────────────────────────────────────────────┐
│           GLOBAL KNOWLEDGE BASE (GKB)           │
│  Narrative knowledge contributed from projects.  │
│  No workspace_id. Readable by all plugins.       │
└────────────────┬────────────────────────────────┘
                 │ contributes on close ↑
                 │ global context on query ↓
    ┌────────────┴──────┐   ┌───────────────────┐
    │   Project A        │   │   Project B        │
    │   (Workspace)      │   │   (Workspace)      │
    └───────────────────┘   └───────────────────┘
```

- **GKB** — `document_chunks` rows with `workspace_id = NULL`. Same pgvector infrastructure; no schema invention.
- **Contribution** — a deliberate human act by the workspace owner. Not automatic. Not a pipeline.
- **Knowledge form** — fuzzy narrative (retrospectives, lessons learned), not structured facts. Vector retrieval handles fuzziness natively.

> **Decoupling note:** GKB-1 delivers a generic, plugin-agnostic capability — `scope="hybrid"` in `retrieve_context()`. It is "done" when a generic hybrid query works, proven by a test that has nothing to do with any plugin. No GKB core ticket references pricing. Pricing consumes this capability later (PR-1) as one of several possible consumers; if pricing slips or is abandoned, GKB is unaffected.

---

### GKB-1 — Schema and two-tier retrieval

**Schema changes (Alembic migration):**
- `document_chunks.workspace_id` is already nullable in practice — confirm the column allows NULL; add index on `workspace_id IS NULL` for global-tier queries.
- Add `contributed_at TIMESTAMPTZ`, `contributed_by UUID`, `archived_at TIMESTAMPTZ` to `document_chunks` for GKB-tier rows. This supports staleness management without polluting project chunks.
- Add `source_project_id UUID` (references `workspaces.id`, nullable) — provenance for contributed chunks.
- Add `outcome VARCHAR(32)` and `sector VARCHAR(128)` metadata columns on contributed chunks (structured envelope around fuzzy content).

**Retrieval changes (`src/rag/retrieval.py`):**
- Add `scope: Literal["local", "global", "hybrid"] = "local"` parameter to `retrieve_context()`.
- `local` — existing behaviour, `WHERE workspace_id = %s`.
- `global` — `WHERE workspace_id IS NULL AND archived_at IS NULL`.
- `hybrid` — run both queries, merge results, deduplicate, re-rank. The existing reranker handles merged result sets naturally.

**Tests:** unit tests for each scope mode; integration test confirming hybrid merge returns results from both tiers — **using seeded generic chunks, no plugin involved.**

---

### GKB-2 — Contribution workflow

A workspace owner (or admin) marks a project as contributing to the GKB. They select which documents cross the project boundary and approve a contribution narrative before ingestion.

**Backend:**
- `POST /api/workspaces/{id}/contribute` — accepts a list of `document_ids` and an optional `narrative` (free text). Ingests selected documents into the GKB tier (`workspace_id = NULL`) with contribution metadata. The narrative, if provided, is ingested as an additional chunk.
- `DELETE /api/workspaces/{id}/contributions` — archives all GKB chunks contributed from this workspace (`SET archived_at = NOW()`). Does not hard-delete (Clark-Wilson).
- `GET /api/gkb/chunks` — admin endpoint; lists all GKB chunks with provenance and metadata.

**UI:**
- "Contribute to Global Knowledge" action on the workspace settings page (owner-only).
- Document selector with optional narrative text area.
- Review screen showing what will be contributed before confirmation.

**Guardrails:**
- Contribution requires workspace `owner` role (not `editor` or `viewer`).
- Admin can revoke a contribution (archive) without deleting the workspace.
- Contributed documents are tagged in the workspace document list as "shared globally."

---

## Initiative 5 — Model Management: Environment-Aware Availability

A small but real constraint: the deployment hardware has a finite memory budget for models, and the main LLM, the embedding model, and the cross-encoder reranker all compete for it. Model management must treat "fits in the environment" as a hard limit, not a runtime surprise. Because LocalChat is self-hosted across heterogeneous hardware (NVIDIA, AMD, Apple, CPU-only), this must be vendor-neutral.

---

### MM-1 — Vendor-neutral, environment-aware model availability

**Why:** A model selected without regard to the memory budget causes a hard OOM at load, a runtime error mid-inference, or silent CPU-offload that destroys throughput. Today nothing prevents this. Only models that fit — at the configured quantisation and context length, after reserving headroom for embeddings, reranker, and KV-cache — should be selectable.

**Two memory models, not four backends.** The key design decision: hardware splits into two memory models, and the abstraction is built around them rather than around vendors.

| Memory model | Meaning | Backends |
|---|---|---|
| **Dedicated pool** | A separate VRAM pool the model owns; budget is a hard, queryable number | NVIDIA, AMD |
| **Shared pool** | Model memory is a fraction of system RAM shared with the OS; budget = total minus an OS reservation | Apple (unified memory), CPU-only |

Everything downstream of detection — footprint estimation, the selection filter, the load guard, the UI — is a single shared codepath. VRAM is VRAM regardless of who made the card. Only **detection** and **container passthrough** are hardware-specific. This is the same inward-only discipline as the plugin contract: the budget logic does not depend on what GPU sits underneath.

**The `GpuBackend` interface.** One job: report `(backend_name, memory_model, total_mb, free_mb)`. Concrete implementations:

| Backend | Status | Detection | Container access |
|---|---|---|---|
| NVIDIA | **Built + tested** (RTX 5070) | `nvidia-smi --query-gpu=memory.total,memory.free`, or NVML | NVIDIA Container Toolkit (`--gpus`) |
| Apple (Metal) | **Built + tested** | Unified memory via `sysctl`; reserve OS fraction | n/a |
| CPU-only | **Built + tested** | Budget = configured fraction of system RAM | n/a |
| AMD | **Interface defined, implementation open** | `rocm-smi --showmeminfo vram` or `amdsmi` — *community-contributed, untested against real ROCm hardware* | ROCm passthrough (`--device=/dev/kfd --device=/dev/dri`) |

NVIDIA and Apple together validate the abstraction: they exercise both memory models (dedicated vs. shared). An AMD contributor supplies only the detection parser; the dedicated-pool budget behaviour is inherited from the NVIDIA-tested path, keeping the open contribution small and low-risk.

**Detection order at startup:** probe NVIDIA → AMD → Apple → CPU; first that responds wins. The selected backend and memory model are logged once. `GPU_BACKEND` (default `auto`) lets an admin force one; forcing `amd` without the implementation returns a clear error, never a silent failure.

**Implementation:**
- Footprint per Ollama model: weights at active quantisation + KV-cache sized to context length. Vendor-independent, single codepath.
- Reserved overhead: embedding model + reranker + `MODEL_VRAM_HEADROOM_MB` (default ~1500).
- For the shared-pool model, additionally subtract an OS reservation (`SHARED_POOL_OS_RESERVE_MB`, default ~3000) so the model never starves the host.
- Selection API / UI dropdown lists only models where `footprint + overhead <= budget`. Oversized models are greyed-out with a backend-named reason ("requires ~X GB, Y GB available on <backend>"), never silently hidden.
- Hard load guard: a direct oversized load is rejected with a clear error rather than allowing OOM/offload, unless `MODEL_ALLOW_OVERSIZED=true`.

**Config keys:**
- `GPU_BACKEND` (default `auto`) — `auto | nvidia | amd | apple | cpu`
- `MODEL_VRAM_HEADROOM_MB` (default 1500) — safety margin above computed footprint
- `SHARED_POOL_OS_RESERVE_MB` (default 3000) — OS reservation for shared-pool backends
- `MODEL_ALLOW_OVERSIZED` (default false) — escape hatch permitting offload loads with a logged warning

**Tests required:**
- Unit: each built backend parser (NVIDIA, Apple, CPU) handles its tool's real output and a "tool absent" case without crashing
- Unit: `detect()` falls through the probe order correctly when earlier probes return nothing (mocked)
- Unit: dedicated-pool vs. shared-pool budget computation (shared subtracts OS reserve)
- Unit: footprint estimator returns sane values for a known model at a given quantisation + context length
- Unit: selection filter excludes oversized, includes fitting — identical assertion across both memory models
- Unit: direct oversized load raises when `MODEL_ALLOW_OVERSIZED=false`, warns when `true`
- Unit: forcing `GPU_BACKEND=amd` returns a clear not-implemented error
- Integration: with a mocked constrained budget, the model-list endpoint returns only fitting models, each oversized one carrying a backend-named reason

**Files:** new `src/gpu/backends.py` (the `GpuBackend` interface + NVIDIA/Apple/CPU implementations + AMD stub), `src/gpu_monitor.py` (refactor existing NVIDIA-specific detection onto the abstraction), `src/ollama_client.py` (footprint estimation, load guard), model selection route, `static/js/` (greyed-out dropdown with backend-aware reason).

**Note for later:** footprint estimation is a heuristic — quantisation schemes and KV-cache growth vary, and vary the same way across vendors, so the estimator stays single-codepath. Start conservative on headroom; calibrate against real readings (`nvidia-smi` on the RTX 5070, Activity Monitor on the Mac). The AMD parser must be verified on real ROCm hardware before its stub is promoted from "untested."

---

### MM-2 — Runtime resource isolation ⬜

MM-1 stops you selecting a model too large to *load*. MM-2 stops a *running* model from starving the rest of the stack. Distinct risk: an Ollama generation that consumes all memory can take down PostgreSQL or the ingestion worker on the same host. MM-1 is about fit-at-load; MM-2 is about isolation-at-runtime.

- **Container limits:** set `mem_limit` and `cpus` per service in `docker-compose.yml` so no single container (Ollama especially) can exhaust the host. Reserve headroom for the DB and worker.
- **Ollama model lifecycle:** set `OLLAMA_MAX_LOADED_MODELS` and `OLLAMA_KEEP_ALIVE` so the inference server doesn't hold multiple models in VRAM simultaneously or pin one indefinitely — directly complements the MM-1 VRAM budget.
- **Acceptance:** under a deliberate memory-pressure test, a heavy inference does not crash or starve the DB/worker; limits documented in `docker-compose.yml`.

> Scope note: this is deployment/infrastructure config, not application code — low risk, high resilience value. Pairs naturally with MM-1 (fit-at-load + isolation-at-runtime = complete resource story).

---

## Initiative 6 — Plugin Contract

The mechanism that lets plugins extend LocalChat without the core ever depending on them. This initiative builds the catalogue of services and hooks, the manifest loader, the reference echo plugin, and the enforcing CI gate. It is **pricing-free** — pricing is not mentioned in any PC ticket. Pricing is the first external consumer (Initiative 7), validated *against* this contract.

> **Sequencing:** PC tickets build the contract against a trivial reference plugin. The contract is proven generic before any domain plugin consumes it. This inverts the earlier plan where pricing was the reference implementation — the reference is now core-owned and domain-free.

---

### PC-1 — Service catalogue and manifest loader

**What it builds:** the inward-facing capability surface plugins request by name.

- A `PluginServices` provider assembled at startup, exposing handles: `retrieval` (wraps `retrieve_context` incl. `scope`), `llm` (wraps `OllamaClient`), `storage` (namespaced DB handle + optional Clark-Wilson helpers), `config` (validated access to declared keys), `identity` (wraps `require_role_dep`).
- Manifest reading in `src/tools/plugin_loader.py`: parse `PLUGIN_SCOPE`, `PLUGIN_MIN_ROLE`, `PLUGIN_CONTRIBUTES`, `PLUGIN_HOOKS`, `PLUGIN_CONFIG`; validate; register config keys; inject service handles.
- A malformed/failing manifest disables that plugin and logs; startup proceeds.

**Files:** `src/tools/plugin_loader.py`, new `src/plugins/services.py`, `src/config.py` (dynamic key registration)

**Tests:** unit per service handle (mock backend); unit for manifest validation (good + malformed); manifest config keys land in config service with defaults.

---

### PC-2 — Hook bus and core scheduler

**What it builds:** the core-to-plugin event surface, and the generic scheduler that replaces ad-hoc timers.

- A lightweight hook bus: `emit(hook_name, payload)` in core code; subscribers registered from manifests. A raising subscriber is logged and skipped.
- Hooks wired: `on_document_ingested` (emit from `SyncWorker._handle_event()` and `rag/processor.py`), `on_tool_invocation` (via `src/agent/tool_router.py`), `on_route_mount` (app assembly in `src/app_fastapi.py`).
- A single core scheduler emitting `on_scheduler_tick`, replacing the bespoke `threading.Timer` in `_init_reranker_scheduler`. The reranker becomes the first tick subscriber — proving the generic scheduler against an existing core consumer, not a plugin.

**Files:** new `src/plugins/hooks.py`, `src/connectors/worker.py`, `src/rag/processor.py`, `src/agent/tool_router.py`, `src/app_fastapi.py`, `src/app_bootstrap.py`

**Tests:** unit for emit-with-no-subscribers (no-op); unit for raising-subscriber-is-isolated; integration confirming reranker still fine-tunes as a tick subscriber.

---

### PC-3 — Reference echo plugin

**What it builds:** the core's own fixture that exercises every service and hook with no domain logic.

- `plugins/_echo/` — declares a manifest using all hooks, requests every service, and does nothing but echo. Lives in-core as a test fixture, not a private plugin.
- Each service and hook gets a generic test driven by echo.

**Files:** `plugins/_echo/`, `tests/plugins/test_echo_contract.py`

---

### PC-4 — Plugin-absent CI gate (the architectural IVP)

**What it builds:** the enforcement that makes the whole initiative durable.

- New `core-without-plugins` job in `.github/workflows/tests.yml`: empties `plugins/` (echo fixture excepted) and removes private plugin paths, then runs the fast suite (`pytest -m "not (slow or ollama or db)"`) plus `ruff`.
- Required to pass on every PR to `main`. Red = a plugin dependency leaked into the core.

**Files:** `.github/workflows/tests.yml`

**Tests:** the job *is* the test. A deliberate temporary leak (core importing echo) must turn it red in CI verification, then be reverted.

---

## Initiative 7 — Pricing Plugin (first external consumer)

The pricing plugin is the **first consumer** of the plugin contract — not its reference implementation, and not part of the core. It lives in a private Atos/Eviden repository as a directory overlay. The core neither imports it nor tests against it; the `core-without-plugins` gate proves this on every PR.

Full design: `LocalChat_PricingRAG_Design_v2.1.docx` (private repo).

---

### PR-1 — Pricing plugin against the contract

**What it builds:** price-to-win analysis for an active project, entirely through consumed capabilities.

- Manifest: `PLUGIN_SCOPE = "hybrid"`, `PLUGIN_MIN_ROLE = "viewer"`, `PLUGIN_CONTRIBUTES = False`.
- Query flow: extract context from question + active workspace → `retrieval.retrieve(scope="hybrid")` for cross-project patterns and project specifics → `llm.complete()` for the price-to-win narrative.
- Structured pricing tables created via the `storage` service (namespaced; Clark-Wilson soft-delete helpers applied; no core→plugin FKs).
- Pricing tools registered via `on_tool_invocation`; structured extraction via `on_document_ingested`; feedback evaluation via `on_scheduler_tick`; pricing routes via `on_route_mount`.
- No worldview engine and no private cross-project table: cross-project intelligence is GKB retrieval (`scope="hybrid"`) plus the human-curated contribution workflow (GKB-2).

**Depends on:** PC-1..PC-4 (contract), GKB-1 (hybrid retrieval), RBAC-1 (identity service).

**Tests (private repo):** consumer-side only; the core's gate is unaffected by their presence or absence.

---

## Sprint Plan

| Sprint | Tickets | Est. duration |
|---|---|---|
| 1 | HK-1..HK-6 ✅ done & merged (#105): hygiene, config consolidation, Flask eliminated, docs synced, CI gate | — |
| 1b | HK-7 ✅ (data-access boundary sealed, #116) + HK-8 ✅ (Ollama async/httpx) + HK-9 ✅ (handler boundary) — all done & merged | — |
| 2 | 🚧 CW-1 (document soft-delete pilot) | 1 week |
| 3 | CW-2a + CW-2b (conversations, users) | 1 week |
| 4 | CW-2c + CW-2d + CW-2e + CW-2f (workspaces, memories, annotations, connectors) | 1 week |
| 5 | RBAC-1 (viewer role) — pending scope confirmation | 1 week |
| 6 | RBAC-2 (route permission audit) + CW-3 (audit log, stretch) | 1 week |
| 7 | MM-1 (environment-aware model availability) — independent, can run in parallel | 1 week |
| 8 | GKB-1 (schema + two-tier retrieval) | 1 week |
| 9 | GKB-2 (contribution workflow) | 1 week |
| 10 | PC-1 + PC-2 (services, hooks, scheduler) | 1 week |
| 11 | PC-3 + PC-4 (echo plugin, CI gate) | 1 week |
| 12 | PR-1 (pricing plugin — private repo) | 1–2 weeks |
| **Total** | | **~13–14 weeks** |

> **Sprint 1 complete:** HK-1..HK-6 merged in `#105` (hygiene, config consolidation, Flask eliminated, docs synced, CI gate). Sprint 1b complete: HK-7 (coupling audit + data-access boundary, #116), HK-8 (Ollama async/httpx), HK-9 (handler boundary). HK-10 (database async) deliberately deferred — see its ticket for the scale trigger.
> MM-1 is independent of the CW/RBAC/GKB/PC chain — it touches only `src/gpu/`, `gpu_monitor.py`, `ollama_client.py`, and the model route. Shown at Sprint 7 but can run in parallel with any earlier sprint if a second hand is available.
> The core is fully shippable at the end of Sprint 11. PR-1 lives in the private repo and cannot affect core stability — the worst case for a pricing failure is that one private directory does not ship.

---

## What This Does Not Cover

| Item | Decision |
|---|---|
| Multi-tenancy / SaaS isolation | Out of scope — LocalChat is self-hosted |
| OAuth / SSO for viewer-only access | Defer to v4.0 |
| Row-level security in PostgreSQL | Defer — application-level RBAC sufficient for self-hosted deployment |
| Purge scheduler (auto-purge after N days) | Defer — manual purge is sufficient; scheduled purge is a separate feature |
| Automatic signal extraction pipeline | Defer — human-curated retrospectives are the contribution model; ML extraction is v4.0 |
| GKB staleness / decay scoring | Defer — `archived_at` column reserved; active staleness weighting is a future retrieval improvement |
| Speculative plugin services/hooks | Not built ahead of need — catalogue grows on demand per `.claude/rules/plugins.md` |
| AMD GPU backend (MM-1) | Interface defined; implementation left as a community contribution — cannot be tested without ROCm hardware |
| Pricing plugin in core repo or core tests | Never — pricing is private and the `core-without-plugins` gate forbids the dependency |
