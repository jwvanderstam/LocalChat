# Architecture Rules

## Route blueprints

Handlers in `src/routes_fastapi/` do exactly these things:
1. Parse and validate the request (Pydantic model from `src/models.py`)
2. Authorise the caller: `deny()` from `_authz.py` for a workspace-scoped route, or the admin dependency
3. Call a service, requested with `Depends(...)` from `_services.py`, passing the scope from `get_scope(request)`
4. Return the response

No SQL, no LLM calls, no business logic inside route functions, and no database: a ratchet holds route-level database access at zero. The yes-or-no on access stays in the route; the service decides only what depends on the caller beyond that (ADR-7, amended 2026-10-24).

## Database access

- All SQL lives in `src/db/`, in one repository class per aggregate (`UsersRepository`, `DocumentsRepository`, …) held as an attribute of `Database`: `db.users`, `db.tokens`, `db.workspaces`, `db.members`, `db.api_keys`, `db.documents`, `db.conversations`, `db.memories`, `db.connectors`, `db.oauth_tokens`, `db.feedback`, `db.annotations`, `db.entities`, `db.contributions`. QP-4 replaced every mixin; repositories carry no business rules.
- Never write raw SQL in routes, services, or tools.
- The `Database` class in `src/db/__init__.py` is the connection pool holding the repositories; it stays (ADR-7, amended 2026-10-25). A new aggregate is a new repository attribute (ADR-7).
- A route reaches the database only through a service, requested with `Depends(...)` from `src/routes_fastapi/_services.py`; it never reads `app.state.db`.

## Workspace scope

Row-level security is forced on the ten workspace tables (ADR-5, migration `0023`), so the database answers only what a transaction's scope admits.

- Every repository method that touches one of those tables takes `scope=` and opens its connection with `get_connection(scope=...)`. A ratchet holds unscoped methods at zero.
- The scope is the workspace the route authorised, from `get_scope(request)`. A repository never picks it.
- `ALL_WORKSPACES` is for installation-wide paths only, such as admin totals and the sync worker. Every use needs a reason that holds for every caller who can reach it. Both High findings of the QP-9 review were `ALL_WORKSPACES` paths that a workspace user could reach.
- An id that arrives in a body or a header is looked up in the caller's scope before it is used, just like an id in the path. A miss is a 404.
- A schema change is an Alembic migration in `migrations/versions/` — a new column, index, table, backfill or policy. `_ensure_extensions_and_tables()` in `src/db/connection.py` only creates the base schema a fresh database starts from. See [docs/MIGRATIONS.md](../../docs/MIGRATIONS.md). (This line said the opposite until 2026-10-06, eighteen migrations after it stopped being true.)
- Migrations are additive: `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. Never destructive.

## Configuration

- All tunables, thresholds, timeouts, and service URLs live in `src/config.py` as constants loaded from `.env`.
- Never call `os.environ` or `os.getenv` outside `src/config.py`. If a new setting is needed, add it there.
- Never hardcode values that differ between environments.

## Input validation

- Every external request goes through a Pydantic model defined in `src/models.py`.
- Validate once at the boundary. Inside the service layer, trust the data — no re-validation.
- `src/utils/sanitization.py` handles HTML/injection cleaning. Call it after Pydantic validation, not before.

## SSE streams

- Wrap `async def _generate()` in `try/finally` to handle client disconnect — FastAPI silently drops broken generators.
- Always yield a flush after each event; don't batch silently.
- Never let an unhandled exception silently break a stream. Yield an `error` event, then stop cleanly.
- Don't hold a DB connection open across the full stream lifetime. Fetch data upfront, stream the output.

## Singletons

`ollama_client`, `connector_registry`, `mcp_registry` and `model_registry` are module-level instances, created at import in their own modules. Import the instance and don't construct another. `create_app()` also puts `ollama_client` on `app.state`; `bootstrap_app()` does their startup I/O.

## MCP servers

- Domain servers live in `mcp_servers/` and run as separate **uvicorn** processes.
  (HK-4 ported them from Flask/WSGI to FastAPI/ASGI and switched `docker-compose.yml`
  from gunicorn to uvicorn; this line kept saying gunicorn until 2026-08-27.)
- All three implement the `MCPServer` base class from `mcp_servers/base.py` (JSON-RPC 2.0).
- The main app communicates through `src/mcp_client.py` only — never by direct import of `mcp_servers/`.

## Adding a new feature

Checklist:
- New Pydantic models in `src/models.py`
- New DB operations in the aggregate's repository in `src/db/`, each taking `scope=`; the rules in its service in `src/services/`
- New route in `src/routes_fastapi/` — thin handler only
- Router registered in `src/app_fastapi.py`
- Unit tests for business logic, integration test for the endpoint
- Update [file-map.md](file-map.md) with new files
