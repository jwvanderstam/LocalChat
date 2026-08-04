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

LocalChat has **two** role tiers, and the distinction is the whole initiative:

| Tier | Column | Vocabulary | Answers | Enforced by |
|---|---|---|---|---|
| Global | `users.role` | `admin`, `user` | "what may you do to the system?" | `require_admin_dep` — 23 call sites |
| Per-workspace | `workspace_members.role` | `viewer`, `editor`, `owner` | "what may you do *in this workspace*?" | `check_workspace_access` — 5 call sites (BUG-3) |

Read-only access is a **workspace** concern, so it is the workspace tier that needs enforcing. The global tier stays `admin`/`user` and is not extended.

---

### RBAC-1 — Enforce the workspace role tier

> **Rewritten 2026-08-04.** The original ticket proposed adding `viewer` as a third `users.role` plus a new `require_role_dep`. That is superseded: a workspace-scoped `viewer`/`editor`/`owner` tier already exists — table, DB mixin, member-management routes, `_ROLE_LEVELS` hierarchy, and a correct enforcement dependency. Building a global `viewer` alongside it would have created two different roles with the same name at different tiers. This ticket adopts what exists instead of duplicating it. The original text is in git history at `961d0bd`.

**Scope decisions (confirmed 2026-08-04):**

1. **Adopt the workspace tier.** No global `viewer`; `users.role` stays `admin`/`user`. RBAC-1 wires the existing mechanism into routes rather than inventing a parallel one.
2. **A viewer sees every document in workspaces they belong to.** Membership is the boundary. No per-document ACL, no sharing concept — retrieval already filters on `workspace_id` alone, and adding an ACL check inside the hot RAG query is not warranted.
3. **A viewer may export conversations they participated in.** *(Assumption, not yet confirmed — flip this one row if wrong.)* Export reformats content the viewer can already read on screen, so blocking it restricts the format rather than the access. **Re-review trigger:** if a workspace is ever shared with someone outside the organisation — an external client, an auditor — revisit whether export is a capability separate from read.

**Permission matrix — workspace tier**

Global `admin` short-circuits all of these, as it already does in `check_workspace_access`.

| Capability | owner | editor | viewer |
|---|---|---|---|
| Chat / query the workspace | ✓ | ✓ | ✓ |
| View document list and all workspace documents | ✓ | ✓ | ✓ |
| View own conversation history | ✓ | ✓ | ✓ |
| Export own conversations | ✓ | ✓ | ✓ |
| List workspace members | ✓ | ✓ | ✓ |
| Upload documents | ✓ | ✓ | — |
| Delete (soft) documents | ✓ | ✓ | — |
| Manage own conversations | ✓ | ✓ | — |
| Annotate chunks | ✓ | ✓ | — |
| Edit workspace settings / system prompt | ✓ | — | — |
| Add / remove / re-role members | ✓ | — | — |
| Delete the workspace | ✓ | — | — |
| Contribute to the GKB (GKB-2) | ✓ | — | — |

Global-tier capabilities are unchanged and remain `admin`-only: system settings, RAG parameters, user management, purge of any CDI, reranker training.

---

**Blocking prerequisite — today nobody is a member of anything.**

Verified 2026-08-04: `create_workspace` (`src/db/workspaces.py:30`) inserts into `workspaces` and returns; it never writes a `workspace_members` row, and the route (`workspace_routes.py:67`) does not either. The auto-created `Default` workspace (`src/db/connection.py:473`) has no members by construction. `add_workspace_member` is reachable only through the member routes.

So enforcing membership across the route surface — which is precisely what this ticket does — **locks every non-admin user out of every workspace**. This is not a backfill footnote; it is a code defect that must land first or in the same change:

- `create_workspace` must record its creator as `owner`. Needs the caller's identity threaded into the route, which currently does not resolve it at all.
- Existing workspaces and users need a backfill: decide per workspace who becomes `owner`, and whether all existing users get `editor` or `viewer` on `Default`.
- **Clark-Wilson interaction:** `purge_user` (`src/db/users.py:191`) refuses to purge any user holding a membership row. A blanket backfill therefore makes every user unpurgeable until their memberships are removed. Decide deliberately whether that is the intended precondition or whether purge should ignore membership.

---

**Implementation:**
- Wire `check_workspace_access` (or `require_workspace_role_dep` where the route has no path `workspace_id`) into every workspace-scoped route, at the minimum role from the matrix above.
- **Mind the binding trap:** a dependency that declares its own `workspace_id` parameter has it bound as a *query* parameter, so a route with `workspace_id` in its **path** must pass the value explicitly. BUG-3 documents this; it is the reason `check_workspace_access` takes the id as an argument.
- Fix `create_workspace` to assign creator-ownership; add the backfill migration.
- Delete any remaining ad-hoc role comparisons so there is one mechanism.
- UI: hide upload, delete, annotate, and workspace-settings controls for a `viewer` session; the member list stays visible.

> **Note for the plugin contract:** the `identity` service that plugins consume (`require_role(min_role)`, `.claude/rules/plugins.md`) is backed by the **workspace** dependency, not a global one — a plugin declaring `PLUGIN_MIN_ROLE = "viewer"` means viewer *in the active workspace*. PC-1 exposes it as a service; plugins never read JWT claims directly.

**Files:** `src/security_fastapi.py`, `src/db/workspaces.py`, `src/routes_fastapi/*.py`, a backfill migration under `migrations/versions/`, `static/js/`

**Tests required:**
- Unit: each workspace-scoped route rejects a caller below its matrix role, and accepts at or above it
- Unit: `create_workspace` records the creator as `owner`
- Unit: global `admin` passes every workspace check without a membership row
- Unit: a viewer may export a conversation; an editor may upload; a viewer may not
- Integration: a freshly created workspace is immediately usable by its creator — the regression that the missing membership row would cause
- Migration: backfill produces exactly one `owner` per existing workspace

**Out of scope:** the global tier (`users.role` gains no values); per-document ACLs; the full route-surface audit (that is RBAC-2).

---

### RBAC-2 — Route permission audit

A systematic pass over every route — not just workspace-scoped ones — to assign the correct minimum role at the correct tier, and to document the result as a permission matrix in `docs/`.

Two inputs from BUG-3 that this ticket exists to generalise: routes had *coverage* without having *authorisation* (the whole suite runs with the RBAC bypass on, so tests passed through checks that never ran), and a correct enforcement dependency sat with zero call sites while the routes it was written for kept their own broken checks. The audit must therefore check that each route has a check **and** that a test exercises it with the bypass off.

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

### MM-1 — Vendor-neutral, environment-aware model availability ✅ (done, merged #120)

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

### MM-2 — Runtime resource isolation ✅ (done, merged #210)

> **Status (2026-08-03):** both halves are now done. The Ollama-lifecycle bullet landed in `d548f4d` — `OLLAMA_MAX_LOADED_MODELS` and `OLLAMA_KEEP_ALIVE`, live in `docker-compose.yml` (the limit was subsequently raised from 1 to 2). The container-limits bullet landed in `#210`, though not via the `mem_limit`/`cpus` keys this ticket proposed: limits are set as `deploy.resources.limits.memory` + `cpus` on all nine services, each overridable per-environment (`DB_MEM_LIMIT`, `OLLAMA_CPU_LIMIT`, `APP_MEM_LIMIT`, …). That places them *inside* the existing `deploy:` blocks rather than beside them — Ollama's GPU `reservations.devices` and its new `limits` now sit in one block, which is why the ticket's "the `deploy:` blocks are reservations, not limits" framing no longer describes the file.
>
> Memory *reservations* were tried and reverted within the PR (`13f037f`). `reservations.memory` maps to Docker's `--memory-reservation`, a soft floor the kernel reclaims toward under pressure — setting it on PostgreSQL would have made it a *likelier* eviction victim, the opposite of the intent. Postgres is instead protected by bounding the services that would crowd it out. The reasoning is recorded inline in `docker-compose.yml` so it isn't re-litigated.

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

**Current foundation (do not rebuild from scratch).** The following already exists and works:
- `src/tools/registry.py` — `ToolRegistry` with `@register` decorator, JSON-schema export, execute-by-name, `unregister` for hot-reload.
- `src/tools/plugin_loader.py` — file-based loader: scans `plugins/*.py`, dynamic import, per-plugin load/unload/hot-reload, error isolation, `PLUGIN_META` dict support.
- `src/tools/builtin.py` — 4 built-in LLM tools (`search_documents`, `list_documents`, `get_current_datetime`, `calculate`) registered at import time.
- `GET /api/plugins`, `POST /api/plugins/reload` — already live admin endpoints.
- `plugins/example_plugin.py` — working demo (`word_count`, `reverse_text`).

PC-1 **extends** this foundation: it adds the manifest contract, service injection, and the `PluginServices` provider. It does not replace or rewrite what is already there.

**What it builds:** the inward-facing capability surface plugins request by name.

- A `PluginServices` provider assembled at startup, exposing handles: `retrieval` (wraps `retrieve_context` incl. `scope`), `llm` (wraps `OllamaClient`), `storage` (namespaced DB handle + optional Clark-Wilson helpers), `config` (validated access to declared keys), `identity` (wraps the workspace-tier check — `check_workspace_access` / `require_workspace_role_dep`; there is no global `require_role_dep`, see RBAC-1).
- Manifest reading in `src/tools/plugin_loader.py`: parse `PLUGIN_SCOPE`, `PLUGIN_MIN_ROLE`, `PLUGIN_CONTRIBUTES`, `PLUGIN_HOOKS`, `PLUGIN_CONFIG`; validate; register config keys; inject service handles.
- A malformed/failing manifest disables that plugin and logs; startup proceeds.

**Migration items bundled into PC-1:**
- `plugins/example_plugin.py` currently does `from src.tools.registry import tool_registry` directly — importing a core internal. When PC-1 lands, convert it to use the injected service handle and update `plugins/README.md` to reflect the new contract. Retire it when PC-3 delivers `plugins/_echo/`, which supersedes it as the canonical reference.
- `src/tools/builtin.py` — `search_documents` and `list_documents` do lazy singleton imports (`from ..rag import doc_processor`, `from ..db import db`) inside the function body. Migrate them to use the `retrieval` and `storage` service handles respectively so built-in tools follow the same contract as plugin tools.

**Files:** `src/tools/plugin_loader.py`, new `src/plugins/services.py`, `src/config.py` (dynamic key registration), `src/tools/builtin.py`, `plugins/example_plugin.py`, `plugins/README.md`

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
- **Retire `plugins/example_plugin.py`** in this same PR: it predates the contract and is superseded by `_echo/` as the canonical reference. Remove it and update `plugins/README.md` to point to `_echo/` instead.

**Files:** `plugins/_echo/`, `tests/plugins/test_echo_contract.py`, ~~`plugins/example_plugin.py`~~ (deleted)

---

### PC-4 — Plugin-absent CI gate (the architectural IVP)

**What it builds:** the enforcement that makes the whole initiative durable.

- New `core-without-plugins` job in `.github/workflows/tests.yml`: empties `plugins/` (echo fixture excepted) and removes private plugin paths, then runs the fast suite (`pytest -m "not (slow or ollama or db)"`) plus `ruff`.
- Required to pass on every PR to `main`. Red = a plugin dependency leaked into the core.

**Files:** `.github/workflows/tests.yml`

**Tests:** the job *is* the test. A deliberate temporary leak (core importing echo) must turn it red in CI verification, then be reverted.

---

## Initiative 7 — Pricing Plugin (first external consumer)

> **Status: Deferred** — not in scope for single-GPU self-hosted deployment. Design artefacts exist in the private Atos/Eviden repo (`LocalChat_PricingRAG_Design_v2.1.docx`). Revisit after PC-4 proves the plugin contract against a generic consumer. No timeline set.

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

## Initiative 8 — Bug Fixes (found during Discord bridge integration, 2026-07-27)

Two concrete bugs surfaced while wiring an external Discord bot to `/api/chat` via n8n. Both confirmed by code inspection plus a live curl test against the running instance, not just symptom reports.

**Scheduled as Sprint 5 (re-evaluated 2026-08-01); both shipped 2026-08-02.** Both were originally queued in Sprint 6 behind RBAC-1, a ticket blocked on an open scope question. Neither bug depended on that question, and both affected answers users were getting then — one silently crossed a workspace boundary, the other dropped attribution. They ran first, and the re-evaluation was borne out: each turned out to have a second, undescribed half (see the outcome notes below) that would have kept growing behind an unrelated gate.

---

### BUG-1 — Long-term memory is not scoped to workspace ✅ (done, merged #208)

**Confirmed:** `MemoryRetriever.retrieve()` (`src/memory/retriever.py`) takes no `workspace_id` parameter at all, and is called from `chat.py`'s `retrieve_plan_and_memory()` with no workspace argument. This is asymmetric with document RAG: `get_rag_context()` / `doc_processor.retrieve_context()` correctly filter by `workspace_id` (verified live — a curl call scoped to the "Localchat" workspace with the `X-Workspace-ID` header returned only Localchat-tagged document sources, correctly excluding "Default"-workspace docs on the same instance). Long-term memory has no equivalent filter, so it is effectively database-global regardless of which workspace a request is scoped to.

**Effect:** a client scoped to one workspace (e.g. the Discord bridge, scoped to "Localchat") can have memories formed in a completely different workspace's conversations surface in `memory_context` and bleed into the answer.

**Fix:**
- Add `workspace_id` (and likely `additional_workspace_ids`, mirroring the doc-RAG signature) to `MemoryRetriever.retrieve()`.
- Thread it through from `retrieve_plan_and_memory()` (needs its own new `workspace_id` param) up to the `api_chat` call site in `api_routes.py`, where `workspace_id` is already resolved via `get_workspace_id(request)`.
- Check whether the `memories` table already has a `workspace_id` column; if not, this is a migration, not just a query change — follow the CW-2 soft-delete migration pattern for consistency.

> **Outcome (#208):** the fix was larger than this ticket described, in a way worth recording. The roadmap framed BUG-1 as a *read*-path problem, but `insert_memory` never wrote `workspace_id` at all — the column has existed since migration `0003` and was always NULL. Adding the read filter alone would have "fixed" the leak by making every memory invisible, so both directions had to move together: the write path now records the workspace, `is_duplicate_memory` is scoped to it (unscoped, a memory in one workspace suppressed creating the same one in another — the write-side face of the same isolation failure), and `get_unextracted_conversations` returns it so an extracted memory inherits its conversation's workspace. `get_all_memories` needed the filter too; the management listing leaked the same rows.
>
> No migration was required — the column already existed and the instance holds zero memories (the feature is off by default), so nothing to backfill. Memories with no workspace stay invisible to a scoped query because `ANY(...)` never matches NULL, which follows from construction rather than an added clause. Unscoped callers still see everything, matching `documents.py`'s existing convention rather than inventing a stricter one. 22 new tests, 18 of which fail against the pre-fix code.

---

### BUG-2 — Enhanced web search (DuckDuckGo) results never reach citations ✅ (done, merged #209)

**Confirmed:** `WebSearchProvider.search()` (`src/rag/web_search.py`) returns `WebSearchResult` objects carrying full `title` / `url` / `snippet` metadata. But `get_web_context()` (`src/services/chat.py`) discards that structure — it calls `format_web_context()` and returns only a formatted text blob for the LLM prompt. `retrieve_contexts()` populates the `sources` list solely from `get_rag_context()` (local documents); no equivalent source entries are ever created for web results.

**Effect:** in "enhance" mode, the model's answer is genuinely grounded in fetched web content (the data does reach the prompt), but the citation/source list returned to the client never reflects the web sources used — content without attribution.

**Fix:** extend `retrieve_contexts()` so that when `fields["enhance"]` is true, it appends web-derived entries (title, url) to `sources`, shaped closely enough to the existing local-doc source dicts that the frontend citation renderer can handle both without a special case.

> **Outcome (#209):** done as described, plus a second occurrence this ticket missed. The same omission existed independently in the aggregator path — `ToolRouter._web_search()` hardcoded `"sources": []` on both its MCP and direct branches. Fixing only `retrieve_contexts()` would have left the bug reachable by turning `AGGREGATOR_AGENT_ENABLED` on. Telling detail: `AggregatorAgent._dedup_sources` already carried a branch for sources without a `chunk_id`, commented "(e.g. web results)" — the consumer had been written for data the producer never sent.
>
> Both call sites now share `to_source_dict()` in `src/rag/web_search.py`, placed next to `WebSearchResult` so neither consumer imports the other's internals. A web result is shaped like a document source: `filename` carries the title (url as fallback) so the existing grouping key works, and `chunk_id` is null so the panel doesn't offer a chunk-context link that only exists for ingested documents. `ui.js` renders a source carrying a url as a link, making a web citation verifiable rather than just named. 20 new tests (15 initially, 5 more after SonarCloud's new-code gate correctly caught that every existing test set `MCP_ENABLED=False`, leaving the MCP branch — the one parsing the structured `results` array — entirely uncovered).

---

### BUG-3 — Workspace member routes had no authorisation ⬜

**Found 2026-08-04** while confirming RBAC-1's scope. Five workspace routes were reachable without membership. Confirmed by probing the pre-fix code directly, not by inspection alone:

| Route | Pre-fix behaviour |
|---|---|
| `POST /api/workspaces/{id}/members`, no token | **200** — member written |
| `GET /api/workspaces/{id}/members`, no token | **200** — members disclosed |
| `DELETE /api/workspaces/{id}`, authenticated non-member | **500** |
| `PUT`/`DELETE /api/workspaces/{id}/members/{uid}`, authenticated non-member | **500** |

Two distinct defects, and the second masked the first:

1. **No check at all** on the two `/members` routes. `POST` is a privilege-escalation primitive — an unauthenticated caller adds themselves as `owner`, then legitimately passes every later owner check. Neither route declared a `Depends`, and no router- or app-level auth dependency backs them up.
2. **Fail-open role check** on the other three: `if role is not None and role != "owner"`. A non-member gets `role is None`, skips the branch, and proceeds. Unreachable in practice, because `get_current_user_id(request)` — called directly rather than via `Depends` — hit `credentials.credentials` on an unresolved `Depends` sentinel and raised `AttributeError` first. So those three routes never worked at all outside demo/test mode.

**Why the tests never caught it:** the whole existing suite runs with `state.testing = True`, which trips `_is_rbac_bypassed` and short-circuits every check. The routes had coverage; none of it exercised authorisation.

**Fix:** a single `check_workspace_access(request, workspace_id, min_role)` in `src/security_fastapi.py`, called by all five routes. It denies on `role is None`, honours the bypass consistently with `require_admin_dep`, and takes `workspace_id` explicitly — a dependency declaring its own would have it bound as a *query* parameter and authorise against the wrong workspace. `_enforce_workspace_role` delegates to it so the dep RBAC-1 will adopt cannot drift from the fix.

> **Scope note:** deliberately narrow. It does not wire `require_workspace_role_dep` into routes or audit the rest of the surface — that is RBAC-1 and RBAC-2. The ad-hoc checks this deletes were going to be replaced anyway; closing a live hole two weeks earlier was worth the throwaway. The regression tests are not throwaway — they become the proof that RBAC-1 wired the dependency correctly.

---

## Sprint Plan

| Sprint | Tickets | Est. duration |
|---|---|---|
| 1 | HK-1..HK-6 ✅ done & merged (#105): hygiene, config consolidation, Flask eliminated, docs synced, CI gate | — |
| 1b | HK-7 ✅ (data-access boundary sealed, #116) + HK-8 ✅ (Ollama async/httpx) + HK-9 ✅ (handler boundary) — all done & merged | — |
| 2 | CW-1 (document soft-delete pilot) ✅ done & merged (#119) | — |
| 3 | CW-2a + CW-2b (conversations, users) ✅ done & merged (#124) | — |
| 4 | CW-2c + CW-2d + CW-2e + CW-2f (workspaces, memories, annotations, connectors) ✅ done & merged (#126) | — |
| 5 | BUG-1 + BUG-2 (memory workspace scoping, web citation loss) ✅ done & merged (#208, #209) | — |
| 5b | **BUG-3** (workspace member routes had no authorisation) — pulled forward 2026-08-04 | 1 day |
| 6 | **RBAC-1 (enforce the workspace role tier)** — scope confirmed, ticket rewritten 2026-08-04 | 1 week |
| 6b | RBAC-2 (route permission audit) + CW-3 (audit log, stretch) | 1 week |
| 7 | MM-1 (environment-aware model availability) ✅ done & merged (#120) + MM-2 (runtime resource isolation) ✅ done & merged (#210) | — |
| 8 | GKB-1 (schema + two-tier retrieval) | 1 week |
| 9 | GKB-2 (contribution workflow) | 1 week |
| 10 | PC-1 + PC-2 (services, hooks, scheduler) | 1 week |
| 11 | PC-3 + PC-4 (echo plugin, CI gate) | 1 week |
| 12 | PR-1 (pricing plugin — private repo) | 1–2 weeks |
| **Total** | | **~14 weeks** |

> **Sprint 1 complete:** HK-1..HK-6 merged in `#105` (hygiene, config consolidation, Flask eliminated, docs synced, CI gate). Sprint 1b complete: HK-7 (coupling audit + data-access boundary, #116), HK-8 (Ollama async/httpx), HK-9 (handler boundary). HK-10 (database async) deliberately deferred — see its ticket for the scale trigger.
> **Sprint 2 complete:** CW-1 (document soft-delete pilot, #119). **Sprint 7 complete:** MM-1 (environment-aware model availability, #120) — `src/gpu/backends.py`, `OllamaClient.estimate_model_footprint` / `load_model_guard`, enriched model list endpoint, frontend grey-out.
> **Sprint 3 complete:** CW-2a + CW-2b (conversations and users soft-delete, #124). **Sprint 4 complete:** CW-2c + CW-2d + CW-2e + CW-2f (workspaces, memories, annotations, connectors soft-delete, #126).
> **Also merged post-Sprint-7 (unplanned fixes):** model-management CPU memory budget + loaded-state fix (#146), cross-encoder reranker startup warm-up (#147).
> **Sprint 5 complete (2026-08-02):** BUG-1 (#208) and BUG-2 (#209). **MM-2 complete (2026-08-03, #210)** — its container-limits half, the part still open when MM-1 shipped.
> **Sprint 5b (2026-08-04):** BUG-3, found while confirming RBAC-1's scope — two workspace member routes had no authorisation check at all. Same precedent as Sprint 5: a confirmed defect does not queue behind a design question it has no dependency on. Also the same lesson as MM-2, one layer down — `require_workspace_role_dep` had been written, was correct, and had zero call sites, so the mechanism existed while the routes it was written for kept their own broken checks.
> **Sprint 6 (RBAC-1) — ungated 2026-08-04 and rewritten.** The three scope questions that had blocked this ticket since it was written are answered: adopt the existing workspace tier rather than adding a global `viewer`; membership is the document boundary; viewers may export (that last one an assumption, flagged in the ticket). Answering them shrank the ticket — the global role, `require_role_dep`, and the JWT-claim change are all gone — and surfaced a blocking prerequisite the original never anticipated: `create_workspace` writes no membership row, so enforcing membership today would lock every non-admin out of every workspace. That must land first.
> **Re-evaluated 2026-08-01 — bugs first.** BUG-1 and BUG-2 were sitting in Sprint 6 behind RBAC-1, which has been blocked on scope confirmation since it was written. Two confirmed defects were therefore queued behind an unanswered question they have no dependency on: BUG-1 leaked one workspace's memories into another's answers, and BUG-2 served web-grounded content with no attribution. Both were self-contained and neither needed a design decision, so neither had a reason to wait. They became Sprint 5; RBAC-1 moved to Sprint 6 and keeps its gate.
> **Sprint 6 additions (2026-07-27):** BUG-1 and BUG-2 were originally added here — both found and confirmed during Discord bridge integration testing; see Initiative 8.
> **Depth sprint declared (Sprints 3–4):** No new connectors or features until CW-2a, CW-2b (soft-delete: conversations + users) and RBAC-1 are end-to-end solid with full test coverage. Sprints 3–4 are now done; RBAC-1 (now Sprint 6) remains the gate before new-feature work resumes. Bug fixes are not new-feature work and do not wait on that gate — which is exactly why BUG-1, BUG-2 and BUG-3 all moved ahead of it.
> **MM-2 closed 2026-08-03 (#210), having never been in this table.** It had no sprint and never did, so it went unscheduled from the moment MM-1 shipped and was only caught by an audit of this document — it shipped despite the plan, not because of it. Both halves are now done (Ollama lifecycle in `d548f4d`, container `mem_limit`/`cpus` in `#210`); it is recorded against Sprint 7 above so it stops being invisible. The lesson is about this file, not the ticket: an item present in the initiatives but absent from the sprint table has no scheduled moment when anyone looks at it.
> **Unplanned work merged 2026-07-30/31 (not a sprint):** dependency-pipeline repair — grouped Dependabot updates, `requirements.lock.txt` removed, CI-required status checks on `main`, dependency-drift reporting. See LESSONS_LEARNED Ch. 11.
> The core is fully shippable at the end of Sprint 11. PR-1 lives in the private repo and cannot affect core stability — the worst case for a pricing failure is that one private directory does not ship.

---

## Known Accepted Debt

Findings from the 2026-07 external code-quality audit that are real but deliberately not fixed this round. Recorded here, in the style of SECURITY.md's ECDSA-CVE entry, so they're a documented decision rather than a rediscovered surprise.

- **Multi-instance concurrency** (`AppState`/`MetricsCollector` in-process state, the Alembic migration race, `SyncWorker`'s duplicate connector polling, the reranker's duplicate `threading.Timer` scheduler) — all are per-process state with no cross-process coordination; each races or silently diverges at >1 worker or >1 replica. **Why parked**: `UVICORN_WORKERS` now defaults to `1` (Dockerfile/docker-compose) and the Helm chart's `replicaCount` is fixed at `1` with no HPA — this app is single-instance by design today, so the defect class is unreachable, not fixed. **Re-review trigger**: before ever running >1 worker or >1 replica, this whole class needs a coordination layer (shared cache backend, a distributed lock for migrations/sync/scheduler, or a real metrics aggregator).

- **`Database` god object** (`src/db/connection.py` composes every domain `*Mixin`) — grows unbounded as domains are added. **Why parked**: works, is well-tested per-mixin, and splitting it is a pure refactor with real regression risk across every call site and no user-facing benefit. **Re-review trigger**: a new contributor consistently struggles to navigate it, or two mixins need genuinely different connection-pool behavior.

- **`OllamaClient` split** (chat, embedding, model CRUD, vision, GPU info all on one class) — same shape as the DB god object. **Why parked**: same reasoning — works, tested, no functional gap; splitting is cosmetic. **Re-review trigger**: same as above.

- **No FastAPI `lifespan` protocol — shutdown is `atexit` + `signal.signal(SIGINT/SIGTERM)` instead** (`src/app_bootstrap.py`). **Why parked**: correctly closes DB pools and stops background threads today, in the single-worker process this app actually runs as; migrating to `lifespan` is a framework-idiom cleanup, not a fix for an observed failure. **Re-review trigger**: an observed shutdown-ordering bug (a resource freed twice, or not at all), or a move to a process manager that doesn't deliver `SIGTERM` the way `atexit` expects.

- **`STATE_FILE` (`app_state.json`, `src/config.py`) resolves relative to the working directory, not to a guaranteed-writable path** — and, verified while writing this entry, the Helm chart's pod already sets `containers[].securityContext.readOnlyRootFilesystem: true` (`helm/localchat/templates/deployment.yaml`) with only `/app/logs`, `/app/uploads`, and `/tmp` mounted writable. `/app` itself is not writable, so on a real Helm deployment today, every `AppState.set_active_model()` / `set_rag_param()` write fails. `_save_state()` catches the exception and logs it rather than crashing, so the app stays up — but the setting silently reverts to its config default on the next pod restart. **Correction to an earlier assumption**: this was expected to be moot once the chart declared single-replica reality; it isn't — `readOnlyRootFilesystem` is a separate setting from replica count, and this round's Helm fix (see Sprint notes) didn't touch it. **Why parked anyway**: Helm isn't deployed anywhere yet (no production cluster depends on this today), and the failure mode is silent-degrade, not crash-loop.
  **The real fix is not a writable path.** An `emptyDir` volume mount (or reusing `uploads`) makes the write succeed, but `AppState` is *shared mutable config* — the same category of state that silently diverges across workers/replicas, documented as the first bullet in this section. A pod-local file gives persistence without coherence: two replicas would each keep their own `app_state.json`, disagreeing on the active model and RAG params exactly like the in-memory case does today. The correct destination is a small `app_settings` table in the Postgres this app already requires — reads/writes go through `src/db/`, same as every other piece of durable state. That one change closes `readOnlyRootFilesystem` (no local file), the multi-instance divergence (Postgres is the single source of truth), and the restart-loses-settings failure (survives pod recreation), instead of patching each symptom separately. **Re-review trigger**: before the Helm chart is used for a real deployment, replace `STATE_FILE`/`AppState`'s JSON-file persistence with an `app_settings` DB table rather than reaching for a volume mount.

- **Dual schema ownership** (`_ensure_extensions_and_tables()` in `src/db/connection.py` and Alembic migrations under `migrations/versions/`) — both can create the same tables/columns; staying in sync is manual discipline, not enforced by a single source of truth. **Why parked**: `_ensure_extensions_and_tables()` uses `IF NOT EXISTS` guards throughout, so drift between the two produces a no-op, not corruption; consolidating to Alembic-only is a larger migration-strategy change than this round's scope. **Re-review trigger**: the first time a schema change lands in one and is forgotten in the other and it actually causes an observed bug, not just a caught-in-review discrepancy.

- **Coverage exclusions, pytest side** (`pyproject.toml`'s `[tool.coverage.report] exclude_lines`) — reviewed line by line: `pragma: no cover`, `def __repr__`, `raise NotImplementedError`, `if TYPE_CHECKING:`, `@abstractmethod`, `if __name__ == "__main__":`. **Why parked**: every entry is standard defensive/boilerplate exclusion; none hides untested business logic. **Re-review trigger**: any new addition to this list without the same standard-boilerplate justification should be rejected in review.
- **Coverage exclusions, SonarCloud side** (`sonar-project.properties`' `sonar.coverage.exclusions`) — a distinct mechanism from the entry above; excludes whole files from SonarCloud's reported metric rather than specific lines from pytest's. Originally `src/db/**` wholesale, justified as "requires a live PostgreSQL instance." Checked against actual fast-suite coverage and found the justification stale for `documents.py` specifically — `tests/unit/test_db_operations.py`/`test_db.py` exercise it extensively via mocked connections, no live DB needed, right as it gained the new atomic-replace path. **Action taken**: narrowed the exclusion to name the other 12 files explicitly instead of the whole directory, so `documents.py` is now measured like any other unit-tested module. **Re-review trigger**: if another `src/db/*.py` file gains equivalent mock-based fast-suite coverage, narrow the list further rather than leaving it excluded by directory-membership alone.

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
| Pricing plugin implementation (Initiative 7) | Deferred — not in scope for self-hosted single-GPU deployment; design artefacts in private repo; revisit post-PC-4 |
