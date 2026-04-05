"""
Rate Limiting Integration Tests
================================

Verifies that FlaskLimiter enforces limits and stores counters in Redis
when configured.  Redis tests are skipped when Redis is unavailable.
"""

import pytest
from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _make_test_app(storage_uri: str) -> Flask:
    """Minimal Flask app with a ``/ping`` endpoint limited to 2 per minute."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    lim = Limiter(
        app=app,
        key_func=get_remote_address,
        storage_uri=storage_uri,
    )

    @app.route("/ping")
    @lim.limit("2 per minute")
    def _ping():
        return "pong", 200

    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestRateLimiting:
    def test_memory_rate_limit_enforced(self):
        """429 is returned after the limit is exceeded (in-process memory)."""
        app = _make_test_app("memory://")
        with app.test_client() as client:
            assert client.get("/ping").status_code == 200
            assert client.get("/ping").status_code == 200
            assert client.get("/ping").status_code == 429

    @pytest.mark.skipif(
        not _redis_available(), reason="Redis not available at localhost:6379"
    )
    def test_redis_rate_limit_enforced(self):
        """429 is returned after the limit is exceeded (Redis storage)."""
        app = _make_test_app("redis://localhost:6379/1")
        with app.test_client() as client:
            assert client.get("/ping").status_code == 200
            assert client.get("/ping").status_code == 200
            assert client.get("/ping").status_code == 429

    @pytest.mark.skipif(
        not _redis_available(), reason="Redis not available at localhost:6379"
    )
    def test_redis_counter_stored_in_db1(self):
        """Rate limit counter key is written to Redis DB 1 (separate from app caches in DB 0)."""
        import redis

        r = redis.Redis(host="localhost", port=6379, db=1)
        r.flushdb()

        app = _make_test_app("redis://localhost:6379/1")
        with app.test_client() as client:
            client.get("/ping")

        keys = r.keys("*")
        assert len(keys) >= 1, "Expected at least one rate-limit key in Redis DB 1"
        r.flushdb()

    @pytest.mark.skipif(
        not _redis_available(), reason="Redis not available at localhost:6379"
    )
    def test_redis_counter_shared_across_instances(self):
        """Two Limiter instances pointing at the same Redis share a counter.

        This verifies the distributed behaviour: a request handled by instance A
        consumes capacity that instance B can no longer use.
        """
        import redis

        r = redis.Redis(host="localhost", port=6379, db=1)
        r.flushdb()

        # Instance A consumes one of the two available slots.
        app_a = _make_test_app("redis://localhost:6379/1")
        with app_a.test_client() as client_a:
            assert client_a.get("/ping").status_code == 200

        # Instance B shares the same Redis key; only one slot remains.
        app_b = _make_test_app("redis://localhost:6379/1")
        with app_b.test_client() as client_b:
            assert client_b.get("/ping").status_code == 200   # consumes last slot
            assert client_b.get("/ping").status_code == 429   # limit exhausted

        r.flushdb()
