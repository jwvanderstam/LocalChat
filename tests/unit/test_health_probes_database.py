"""`/api/health` reports the database it can reach now, not the one it reached at boot.

`compute_health_status` used to return `startup_status['database']` — a boolean
recorded once, during startup, and never revisited. The endpoint therefore
reported `up` for the life of the process however unreachable the database had
become. Against a Serverless SQL database that scales to zero, that is not a
theoretical gap: logins returned 500 while health stayed green.

A TCP check would not have closed it either. A connection pooler accepts the
socket whether or not the database behind it can answer, so the probe has to
borrow a real connection and run a query — the same thing a request does.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from src import monitoring

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear_probe_cache():
    """The probe caches for a few seconds; each test starts from cold.

    Written defensively so that removing the probe makes these tests fail on
    their assertions rather than error in setup — a suite that errors proves
    only that a symbol is missing, not that the behaviour changed.
    """
    cache = getattr(monitoring, "_db_probe", None)
    if cache is not None:
        cache["at"], cache["up"] = 0.0, False
    yield
    if cache is not None:
        cache["at"], cache["up"] = 0.0, False


def _app(*, boot_ok=True, query=None):
    app = MagicMock()
    app.startup_status = {"database": boot_ok, "ollama": False}
    app.embedding_cache = None
    app.ollama_client = MagicMock()
    app.ollama_client.check_connection.side_effect = OSError("no ollama")

    calls = []

    @contextmanager
    def get_connection():
        if query is not None:
            query()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (1,)
        cursor.execute.side_effect = lambda sql, *a: calls.append(sql)
        conn.cursor.return_value.__enter__.return_value = cursor
        yield conn

    app.db.get_connection = get_connection
    return app, calls


class TestAReachableDatabase:
    def test_reports_up_and_actually_queries(self):
        app, calls = _app()

        status, code, checks = monitoring.compute_health_status(app)

        assert checks["database"] == {"status": "up", "healthy": True}
        assert calls == ["SELECT 1"], "health must issue a real query, not read a flag"
        assert code == 200


class TestADatabaseThatWentAwayAfterBoot:
    """The case the old implementation got wrong, and the reason this exists."""

    def test_reports_down_even_though_boot_succeeded(self):
        def gone():
            raise OSError("connection pool exhausted: server closed the connection")

        app, _ = _app(boot_ok=True, query=gone)

        status, code, checks = monitoring.compute_health_status(app)

        assert checks["database"]["status"] == "down"
        assert checks["database"]["healthy"] is False
        assert status == "unhealthy"
        assert code == 503, "a probe has to be able to act on this"

    def test_a_failing_probe_does_not_raise_out_of_the_endpoint(self):
        def gone():
            raise RuntimeError("boom")

        app, _ = _app(query=gone)

        monitoring.compute_health_status(app)  # must not raise


class TestADatabaseThatNeverCameUp:
    def test_no_query_is_attempted_when_boot_already_failed(self):
        app, calls = _app(boot_ok=False)

        _, code, checks = monitoring.compute_health_status(app)

        assert checks["database"]["healthy"] is False
        assert calls == [], "nothing to probe when the pool was never built"
        assert code == 503


class TestTheProbeIsCheapToPoll:
    def test_repeated_calls_within_the_ttl_query_once(self):
        app, calls = _app()

        for _ in range(5):
            monitoring.compute_health_status(app)

        assert calls == ["SELECT 1"], "polling health must not become load of its own"

    def test_the_cached_verdict_is_the_observed_one_not_a_default(self):
        """Caching `False` is as important as caching `True`."""

        def gone():
            raise OSError("gone")

        app, _ = _app(query=gone)

        first = monitoring.compute_health_status(app)[2]["database"]["healthy"]
        second = monitoring.compute_health_status(app)[2]["database"]["healthy"]

        assert first is False and second is False

    def test_a_stale_verdict_expires(self):
        app, calls = _app()

        monitoring.compute_health_status(app)
        # Push the cached reading beyond its TTL rather than sleeping through it.
        monitoring._db_probe["at"] = (
            float(monitoring._db_probe["at"]) - float(monitoring._DB_PROBE_TTL_SECONDS) - 1
        )
        monitoring.compute_health_status(app)

        assert calls == ["SELECT 1", "SELECT 1"]
