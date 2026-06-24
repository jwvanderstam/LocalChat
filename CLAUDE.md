# CLAUDE.md

> **Starting a new session?** Run `git log --oneline -5` and `git fetch origin` first — another agent may have pushed since your last session.

---

## What This Project Is

LocalChat is a production RAG application. Users upload documents (PDF, DOCX, TXT, MD) and chat with them using a locally-running LLM via Ollama. Documents are chunked, embedded, and stored in PostgreSQL with pgvector for hybrid semantic + BM25 search. The LLM supports tool/function-calling and optional live web search.

**Runtime deps:** PostgreSQL + pgvector, Ollama (local LLM server), Redis (optional caching).

---

## Tech Stack

| Layer | Tech |
|-------|------|
| Web framework | FastAPI + Uvicorn |
| Database | PostgreSQL 15 + pgvector (psycopg3 pool) |
| LLM | Ollama (local); LiteLLM cloud fallback |
| HTTP client | httpx — `httpx.Client` (sync admin/embedding); `httpx.AsyncClient` (async inference) |
| Validation | Pydantic v2 |
| Auth / security | python-jose (JWT), slowapi (rate limiting), Starlette CORSMiddleware |
| Caching | Redis or in-memory fallback |
| ML / NLP | spaCy (GraphRAG), cross-encoder reranker (optional) |
| Linter | `ruff` |
| Tests | pytest + pytest-asyncio (`asyncio_mode = "auto"`) + pytest-cov |

---

## Architecture

**Entry point:** `app.py` → `create_app()` in `src/app_fastapi.py` → FastAPI instance wired with all routers. `create_uvicorn_app()` is used both in dev (`python app.py`) and production (Docker / Uvicorn).

**Request flow:**
1. `APIRouter` in `src/routes_fastapi/` — thin handler, no business logic
2. Pydantic model in `src/models.py` validates; `src/utils/sanitization.py` cleans
3. `src/security_fastapi.py` — JWT (`python-jose`), rate limiting (`slowapi`), CORS
4. Service packages handle business logic
5. Chat and upload responses stream via `StreamingResponse` (async SSE)

**Packages:**

| Package | What it does |
|---------|-------------|
| `src/rag/` | Ingest pipeline, hybrid retrieval, reranker, query planning |
| `src/db/` | All SQL — mixin classes per domain |
| `src/agent/` | Model routing, parallel tool dispatch, result tracing |
| `src/tools/` | Function-calling loop, tool registry, built-ins, plugin loader |
| `src/graph/` | GraphRAG: entity extraction, 1-hop query expansion |
| `src/memory/` | Long-term memory extraction + vector retrieval |
| `src/connectors/` | Document sources: local, S3, SharePoint, OneDrive, webhook |
| `src/cache/` | Multi-backend caching with TTLs |
| `src/mcp_client.py` | MCP HTTP client + circuit breaker |
| `mcp_servers/` | Domain MCP servers (docs :5001, web :5002, connectors :5003) |

Full module index: [`.claude/rules/file-map.md`](.claude/rules/file-map.md)

**Config** (`src/config.py`): all parameters from `.env`. Key RAG defaults: `CHUNK_SIZE=1200`, `TOP_K_RESULTS=20`, `MIN_SIMILARITY_THRESHOLD=0.30`, `SEMANTIC_WEIGHT=0.70`.

---

## Coding Standards

Full rules across 4 files in `.claude/rules/` — short version here.

**Architecture** → [`.claude/rules/architecture.md`](.claude/rules/architecture.md)
- Routes are thin: parse → service → respond. No SQL, no LLM calls in blueprints.
- All SQL in `src/db/` mixins. Never elsewhere.
- All config in `src/config.py`. No `os.getenv` outside it.
- All input through a Pydantic model. Validate once at the boundary; trust internally.

**Python** → [`.claude/rules/python.md`](.claude/rules/python.md)
- Full type hints on all public functions. No untyped `Any`.
- No bare `except:`. Catch specific exceptions; log when catching `Exception`.
- Comments explain *why*. Dead code gets deleted, not commented out.

**Testing** → [`.claude/rules/testing.md`](.claude/rules/testing.md)
- New modules and non-trivial functions need unit tests. Coverage must not drop.
- FastAPI routes: use `TestClient` from `fastapi.testclient` with a minimal mounted app.
- MCP server routes (Flask): create a bare `Flask(__name__)` app in the test; `src/app_factory.py` is gone.

**File map** → [`.claude/rules/file-map.md`](.claude/rules/file-map.md)
- Full module index. Update it in the same commit when adding or removing a file.

---

## Data Integrity: Clark-Wilson Pattern

LocalChat applies the Clark-Wilson integrity model to all persistent data. The core rule: **no Transformation Procedure (TP) may leave a Constrained Data Item (CDI) in a state that fails an Integrity Verification Procedure (IVP).**

**CDIs in this codebase** — any entity referenced by ID from other data:
`documents`, `document_chunks`, `conversations`, `messages`, `users`, `workspaces`, `memories`, `annotations`, `connectors`

**The rule: state transitions, not destruction**

Hard-deleting a CDI while other data still holds its ID breaks IVPs — citations reference missing chunks, conversations reference deleted users. Instead:

- Every CDI table carries `deleted_at TIMESTAMPTZ` and `deleted_by UUID` columns.
- A "delete" TP sets `deleted_at`; it never issues `DELETE FROM` on a CDI.
- All SELECT queries on CDIs filter `WHERE deleted_at IS NULL`.
- A hard purge is a *separate, explicitly authorized TP* with a precondition: no active references exist. It is never the default operation.

**Audit trail** — state changes on CDIs must be traceable: who changed what, when. `deleted_at` + `deleted_by` is the minimum required.

**Separation of intent** — "Retire" (soft-delete, reversible) and "Destroy" (purge, irreversible, requires authorization) are distinct TPs. Never collapse them into one action.

**Applying this when writing new code:**
- Adding a new table that other tables will reference → add `deleted_at` + `deleted_by` from the start.
- Implementing a delete endpoint → it soft-deletes; expose a separate `/purge` endpoint (admin-only) if hard deletion is ever needed.
- Writing a query that reads CDI rows → always include `WHERE deleted_at IS NULL` unless the intent is explicitly to include retired records.

---

## Plugin Contract: Inward-Only Dependencies

LocalChat supports plugins (LLM tools, connectors, background work) that extend the application without modifying it. The core rule mirrors Clark-Wilson, applied to module boundaries instead of data: **a plugin may consume core capabilities; it may never define them.** Dependencies point inward only — the core knows nothing named after any plugin.

**The rule: the core owns the catalogue, plugins consume it**

- The core publishes a stable catalogue of **services** (retrieval, LLM, scoped storage, config, identity) that plugins request by name, and **hooks** (document ingested, scheduler tick, tool invocation, route mount) that plugins subscribe to.
- A plugin declares a manifest (scope, minimum role, hooks, config keys) and is wired up by the core. Everything it does flows through requested services and subscribed hooks. Nothing flows the other way.
- No core table holds a foreign key into a plugin table. No core module imports a plugin module. No core test depends on a plugin being present.
- When a plugin needs something the core does not expose, add a **general** capability to the catalogue — named for what it does, not for who asked. Test: *would this capability be reasonable if the requesting plugin vanished?* If not, it is a leak.

**The IVP: the plugin-absent CI gate**

A CI job verifies architectural integrity: the core builds, lints, and passes its full test suite **with the `plugins/` directory and all private plugin code absent.** If that job goes red, a plugin dependency has leaked into the core. This gate is the enforcing procedure.

Full rules -> [.claude/rules/plugins.md](.claude/rules/plugins.md)

---

## Quality Gates

Run both before every commit. Both must be clean.

```bash
ruff check src/ tests/                       # install once: pip install ruff
pytest -m "not (slow or ollama or db)"       # fast suite, no external services
```

Update [`.claude/rules/file-map.md`](.claude/rules/file-map.md) when adding or removing a module.

---

## Anti-patterns & Gotchas

- **Never put SQL outside `src/db/`** — raw queries in routes have caused subtle transaction bugs.
- **Never import `src/app.py`** — it doesn't export an app. Use `create_app()` from `src/app_fastapi.py`.
- **SSE generators must handle disconnect** — wrap `async def _generate()` in `try/finally`; FastAPI silently drops broken generators.
- **Register `/clear` before `/{id: int}` routes** — FastAPI matches path patterns in order; a literal `/clear` after `/{id}` is shadowed and returns 422.
- **Don't mock `OllamaClient` at the wrong layer** — mock at the service boundary, not inside RAG internals.
- **Don't call `os.getenv` in business logic** — every value that skips `config.py` is invisible to config review.
- **Don't write destructive migrations** — schema changes use `ALTER TABLE IF NOT EXISTS`; `_init_schema()` owns the DDL.

---

## Session Hygiene

Before treating any session as "done", run `git session-status` (alias defined in this repo; see Commands). It surfaces three things that silently break across multi-tool work (Claude Code, chat, Copilot, agents):

- **Branches with commits not in `main`.** Pushing to an already-merged branch lands the commit *nowhere* — there is no open PR to carry it. This is the trap that orphaned MM-2 once. The check flags it.
- **Sync drift** between local and remote `main`.
- **Open PRs** still awaiting merge.

Rules:
- Never delete a branch without first running `git log main..<branch>` to confirm it holds no unique work. `git branch -d` (safe, refuses unmerged) over `git branch -D` (force) unless you have verified.
- After pushing follow-up commits, confirm they belong to an *open* PR — a closed/merged PR will not pick them up.

## Commands
```bash
python app.py                                                          # dev server (FastAPI + Uvicorn)
uvicorn "app:create_uvicorn_app" --factory --host 0.0.0.0 --port 5000 # production (FastAPI + Uvicorn)
docker compose up -d                        # full stack
pytest                                      # all tests + coverage
pytest -m "not (slow or ollama or db)"     # fast only
pytest tests/unit/                          # unit only
pytest tests/integration/                   # integration only
git session-status                          # end-of-session: orphaned commits, sync drift, open PRs
# one-time setup (alias lives in local .git/config, not the repo):
#   git config alias.session-status '!bash scripts/session-status.sh'
```
