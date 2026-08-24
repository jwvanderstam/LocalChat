"""The perf suite runs against the harness TQ-4 already built.

`tests/e2e/conftest.py` starts a real uvicorn against CI's Postgres with
`OLLAMA_BASE_URL` pointed at TQ-2's stub. That is exactly what a concurrency
measurement needs, so it is imported rather than rebuilt — a second copy would
drift from the one the golden path proves works.
"""

import pytest

from tests.e2e.conftest import live_server  # noqa: F401


@pytest.fixture(scope="session")
def server_env() -> dict[str, str]:
    """Raise the chat rate limit for the duration of the benchmark.

    `RATELIMIT_CHAT` defaults to 10 per minute. Left at that, a concurrency run
    measures slowapi: at 200 requests, 190 come back 429 without ever reaching
    the event loop this is here to observe. Worth knowing that PERF-2's own
    committed numbers were taken at `--requests 10`, exactly the ceiling.
    """
    return {"RATELIMIT_CHAT": "100000 per minute"}
