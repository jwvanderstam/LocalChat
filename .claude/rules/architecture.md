# Architecture Rules

## Route blueprints

Handlers in `src/routes_fastapi/` do exactly three things:
1. Parse and validate the request (Pydantic model from `src/models.py`)
2. Call the appropriate service or DB function
3. Return the response

No SQL, no LLM calls, no business logic inside route functions. If you find yourself reaching for `psycopg` or `OllamaClient` inside a route, it belongs in a service or `src/db/`.

## Database access

- All SQL lives in `src/db/` mixin classes. One mixin per domain (`DocumentsMixin`, `ConversationsMixin`, `WorkspacesMixin`, etc.).
- Never write raw SQL in routes, services, or tools.
- The `Database` class in `src/db/connection.py` composes all mixins — add a new mixin there when you add a new `src/db/*.py` file.
- Schema and index creation belongs in `_init_schema()` in `src/db/connection.py`.
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

- Domain servers live in `mcp_servers/` and run as separate gunicorn processes.
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
