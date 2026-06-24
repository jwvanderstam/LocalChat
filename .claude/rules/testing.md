# Testing Standards

## What requires a test

- New public functions and methods → unit test.
- New API endpoints → at least one integration test covering the happy path.
- Bug fix → regression test that would have caught the bug before the fix.
- New Pydantic models → validation tests for required fields, type coercion, and rejection of bad input.
- New DB mixin methods → unit test with a mocked connection or a `db`-marked test.

## Test markers

Pick the tightest marker that fits — it controls what runs in the fast suite.

| Marker | When to use |
|--------|-------------|
| `unit` | Fast, isolated, no I/O. Default for business logic and pure functions. |
| `integration` | Requires a running service (app + at least one backend). |
| `db` | Requires PostgreSQL. |
| `ollama` | Requires Ollama. |
| `slow` | Takes >1 second even without external services. |
| `rag`, `api`, `validation`, `sanitization`, `exceptions` | Domain tags — combine with the above. |

## App creation

**FastAPI routes** (preferred for new tests):
```python
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

app = FastAPI()
app.include_router(router, prefix="/api")
app.state = MagicMock()
app.state.testing = True
client = TestClient(app, raise_server_exceptions=True)
```

Never import from `src/app.py` — it doesn't export an app.

## Fixtures

- Shared fixtures live in `tests/conftest.py`. Add new shared ones there, not in individual test files.
- Utilities live in `tests/utils/`.
- Don't duplicate fixtures `conftest.py` already provides.

## Coverage

- The fast suite is the coverage baseline: `pytest -m "not (slow or ollama or db)"`.
- Coverage must not drop on any PR.
- Don't add `# pragma: no cover` to avoid covering real logic — cover it.

## Async tests

`asyncio_mode = "auto"` is set in `pyproject.toml`. Any `async def test_*` function runs automatically as an async test — no `@pytest.mark.asyncio` needed.

**Mock patterns for async code:**

```python
from unittest.mock import AsyncMock

# Awaitable method (generate_chat_completion, extract, plan, …)
client.generate_chat_completion = AsyncMock(return_value={"message": {"content": "ok"}})
client.generate_chat_completion = AsyncMock(side_effect=[response1, response2])

# Async generator (generate_chat_response streams chunks)
async def _gen(*args, **kwargs):
    for chunk in ["Hello", " world"]:
        yield chunk

client.generate_chat_response = _gen          # assign directly
mock.generate_chat_response.side_effect = _gen  # or via MagicMock.side_effect

# Collect async generator results
chunks = [c async for c in client.generate_chat_response(model, messages)]
```

**httpx stream context manager (OllamaClient._async_client.stream):**

```python
from unittest.mock import AsyncMock, Mock

cm = AsyncMock()
mock_resp = Mock()
mock_resp.status_code = 200
async def _lines():
    for line in ['{"message":{"content":"hi"},"done":false}', '{"done":true}']:
        yield line
mock_resp.aiter_lines = Mock(return_value=_lines())
cm.__aenter__ = AsyncMock(return_value=mock_resp)
cm.__aexit__ = AsyncMock(return_value=None)
client._async_client.stream = Mock(return_value=cm)
```

## Style

- Test names are descriptive sentences: `test_retrieve_context_returns_empty_list_when_no_documents_match`.
- One logical assertion per test — self-explaining failures.
- Test behaviour, not implementation. Don't assert on private state or internal call counts unless the side effect is the point.
- Keep test setup obvious. If the arrange block is getting long, extract a named fixture.
