# Architecture Rules

## Route blueprints

Handlers in `src/routes_fastapi/` do exactly three things:
1. Parse and validate the request (Pydantic model from `src/models.py`)
2. Call the appropriate service or DB function
3. Return the response

No SQL, no LLM calls, no business logic inside route functions. If you find yourself reaching for `psycopg` or `OllamaClient` inside a route, it belongs in a service or `src/db/`.

## Database access

- All SQL lives in `src/db/`. An aggregate QP-4 has moved is a repository class (`UsersRepository`, `WorkspacesRepository`, …) held as an attribute of `Database` (`db.users`, `db.tokens`, `db.workspaces`, `db.members`, `db.api_keys`, `db.documents`, `db.conversations`, `db.memories`, `db.connectors`, `db.oauth_tokens`); the rest are still mixins (`FeedbackMixin`, `AnnotationsMixin`, …) until their PR.
- Never write raw SQL in routes, services, or tools.
- The `Database` class in `src/db/__init__.py` composes the remaining mixins and holds the repositories. A new aggregate is a repository, not a mixin (ADR-7).
- A route reaches a moved aggregate through its service, requested with `Depends(...)` from `src/routes_fastapi/_services.py`; it never reads `app.state.db` for it.
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

`OllamaClient`, `ConnectorRegistry`, `MCPClientRegistry`, and `ModelRegistry` are singletons initialized once in `create_app()`. Don't instantiate them elsewhere. Access via `app.state` or pass them as constructor arguments from the factory.

## MCP servers

- Domain servers live in `mcp_servers/` and run as separate **uvicorn** processes.
  (HK-4 ported them from Flask/WSGI to FastAPI/ASGI and switched `docker-compose.yml`
  from gunicorn to uvicorn; this line kept saying gunicorn until 2026-08-27.)
- All three implement the `MCPServer` base class from `mcp_servers/base.py` (JSON-RPC 2.0).
- The main app communicates through `src/mcp_client.py` only — never by direct import of `mcp_servers/`.

## Adding a new feature

Checklist:
- New Pydantic models in `src/models.py`
- New DB operations in a mixin in `src/db/`
- New route in `src/routes_fastapi/` — thin handler only
- Router registered in `src/app_fastapi.py`
- Unit tests for business logic, integration test for the endpoint
- Update [file-map.md](file-map.md) with new files
