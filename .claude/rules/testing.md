# Testing Standards

## Assertion-strength checklist

Mutation testing (`docs/TEST_QUALITY_AUDIT.md`) found that coverage percentage
hides weak tests — a line can execute inside a test with zero assertions on
its actual behavior and still count as "covered." Root cause: test-writing
sessions framed around a coverage-percentage target reward touching a line,
not verifying it. Every new test should satisfy one of these four rules,
matched to the failure mode it counters:

| Root-cause shape | Corrective rule |
|---|---|
| **WEAK-SMOKE** — asserts "no exception," "not None," a type, or a truthy substring instead of a value | **Assert the exact expected value/state**, not its existence or shape. |
| **Tautological assertion** — the check passes by construction regardless of correctness (a WEAK-SMOKE variant) | **Assert something that could only be true for the correct branch**, not something true for every branch. |
| **MISSING-NEGATIVE-SPACE** — only one member of a set/boundary/branch is ever exercised, and it usually happens to equal the code's own fallback/default | **Add the case where the explicit value diverges from the fallback**, plus the untested side of every boundary and every set member. |
| **Indistinguishable accumulation** — a loop/incremental build is only ever driven with one iteration, so `x += y` and `x = y` look identical | **Drive the loop with ≥2 iterations/chunks and assert the combined result**, and inspect the actual intermediate structure being built, not just a downstream summary of it. |

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
