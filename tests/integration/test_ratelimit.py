"""
Rate Limiting Integration Tests
================================

Verifies that slowapi enforces limits on FastAPI routes.
Redis tests are skipped when Redis is unavailable.
"""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address


def _redis_available(host: str = "localhost", port: int = 6379) -> bool:
    """Return True when a Redis instance is reachable."""
    try:
        import redis

        r = redis.Redis(
            host=host, port=port, socket_timeout=1, socket_connect_timeout=1
        )
        r.ping()
        return True
    except Exception:
        return False


def _make_test_app(storage_uri: str) -> FastAPI:
    """Minimal FastAPI app with a /ping endpoint limited to 2 per minute."""
    limiter = Limiter(key_func=get_remote_address, storage_uri=storage_uri)
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.get("/ping")
    @limiter.limit("2/minute")
    def ping(request: Request) -> str:
        return "pong"

    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestRateLimiting:
    def test_memory_rate_limit_enforced(self):
        """429 is returned after the limit is exceeded (in-process memory)."""
        app = _make_test_app("memory://")
        client = TestClient(app, raise_server_exceptions=False)
        assert client.get("/ping").status_code == 200
        assert client.get("/ping").status_code == 200
        assert client.get("/ping").status_code == 429

    @pytest.mark.skipif(
        not _redis_available(), reason="Redis not available at localhost:6379"
    )
    def test_redis_rate_limit_enforced(self):
        """429 is returned after the limit is exceeded (Redis storage)."""
        app = _make_test_app("redis://localhost:6379/1")
        client = TestClient(app, raise_server_exceptions=False)
        assert client.get("/ping").status_code == 200
        assert client.get("/ping").status_code == 200
        assert client.get("/ping").status_code == 429

    @pytest.mark.skipif(
        not _redis_available(), reason="Redis not available at localhost:6379"
    )
    def test_redis_counter_stored_in_db1(self):
        """Rate limit counter key is written to Redis DB 1."""
        import redis

        r = redis.Redis(host="localhost", port=6379, db=1)
        r.flushdb()

        app = _make_test_app("redis://localhost:6379/1")
        TestClient(app, raise_server_exceptions=False).get("/ping")

        keys = r.keys("*")
        assert len(keys) >= 1, "Expected at least one rate-limit key in Redis DB 1"
        r.flushdb()

    @pytest.mark.skipif(
        not _redis_available(), reason="Redis not available at localhost:6379"
    )
    def test_redis_counter_shared_across_instances(self):
        """Two Limiter instances pointing at the same Redis share a counter."""
        import redis

        r = redis.Redis(host="localhost", port=6379, db=1)
        r.flushdb()

        app_a = _make_test_app("redis://localhost:6379/1")
        assert TestClient(app_a, raise_server_exceptions=False).get("/ping").status_code == 200

        app_b = _make_test_app("redis://localhost:6379/1")
        client_b = TestClient(app_b, raise_server_exceptions=False)
        assert client_b.get("/ping").status_code == 200
        assert client_b.get("/ping").status_code == 429

        r.flushdb()
