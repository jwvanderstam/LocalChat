"""A pooled connection the server has already dropped must never reach a caller.

Observed on the Scaleway test stack, whose Serverless SQL database scales to zero
when idle: after thirteen minutes the first request failed with a 500 after 2.8 s,
a second failed in 0.22 s, and some minutes later requests succeeded again with no
intervention. The pool was handing out connections the server had closed.

Nothing about that is specific to a serverless database. `docker compose restart
db`, a failover, or a Postgres upgrade all produce the same window — the managed
platform only changed the frequency from rare to daily. So this is an integration
test against an ordinary PostgreSQL, killing the pool's own backends to reproduce
the condition exactly.

The unit-level companion asserts the pool is *configured* to check. This asserts
the behaviour that configuration is for, which is the part worth having.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import psycopg
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.db]


def _admin_dsn() -> dict[str, object]:
    from src import config

    return {
        "host": config.PG_HOST,
        "port": config.PG_PORT,
        "user": config.PG_USER,
        "password": config.PG_PASSWORD,
        "dbname": "postgres",
        "connect_timeout": 5,
    }


@pytest.fixture(scope="module")
def scratch_database() -> Iterator[str]:
    """A database of its own, so terminating backends cannot disturb other tests."""
    dbname = f"pooltest_{uuid.uuid4().hex[:10]}"
    try:
        with psycopg.connect(**_admin_dsn()) as conn:  # type: ignore[arg-type]
            conn.autocommit = True
            conn.execute(f'CREATE DATABASE "{dbname}"')
    except psycopg.Error as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")

    try:
        yield dbname
    finally:
        try:
            with psycopg.connect(**_admin_dsn()) as conn:  # type: ignore[arg-type]
                conn.autocommit = True
                conn.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()",
                    (dbname,),
                )
                conn.execute(f'DROP DATABASE IF EXISTS "{dbname}"')
        except psycopg.Error:
            pass


@pytest.fixture
def pool(scratch_database: str):
    """The application's own pool settings, pointed at the scratch database."""
    from psycopg_pool import ConnectionPool

    from src import config

    kwargs = {
        "host": config.PG_HOST,
        "port": config.PG_PORT,
        "user": config.PG_USER,
        "password": config.PG_PASSWORD,
        "dbname": scratch_database,
        "sslmode": config.PG_SSLMODE,
    }
    p = ConnectionPool(
        kwargs=kwargs,
        min_size=2,
        max_size=4,
        timeout=5,
        check=ConnectionPool.check_connection,
    )
    p.wait(timeout=10)
    try:
        yield p
    finally:
        p.close()


def _kill_backends(dbname: str) -> int:
    """Drop every server-side connection to `dbname`, as a restart or a sleep would."""
    with psycopg.connect(**_admin_dsn()) as conn:  # type: ignore[arg-type]
        conn.autocommit = True
        killed = conn.execute(
            "SELECT count(*) FROM ("
            "  SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
            "  WHERE datname = %s AND pid <> pg_backend_pid()"
            ") AS terminated",
            (dbname,),
        ).fetchone()
    return int(killed[0]) if killed else 0


class TestAPoolWhoseServerWentAway:
    def test_the_next_caller_gets_a_working_connection(self, pool, scratch_database):
        """The window this closes: every request failing until the pool recycles."""
        with pool.connection() as conn:
            assert conn.execute("SELECT 1").fetchone() == (1,)

        assert _kill_backends(scratch_database) >= 1, "nothing was killed; the test proves nothing"

        with pool.connection() as conn:
            assert conn.execute("SELECT 1").fetchone() == (1,)

    def test_it_keeps_working_across_repeated_losses(self, pool, scratch_database):
        """One recovery could be luck — a sleeping database does this every night."""
        for _ in range(3):
            _kill_backends(scratch_database)
            with pool.connection() as conn:
                assert conn.execute("SELECT 1").fetchone() == (1,)

    def test_without_the_check_the_caller_gets_the_dead_connection(self, scratch_database):
        """The bug itself, so the fix is measured against something real.

        A pool built the way this one was until now hands out the closed
        connection, and the caller is the first to find out.
        """
        from psycopg_pool import ConnectionPool

        from src import config

        unchecked = ConnectionPool(
            kwargs={
                "host": config.PG_HOST,
                "port": config.PG_PORT,
                "user": config.PG_USER,
                "password": config.PG_PASSWORD,
                "dbname": scratch_database,
                "sslmode": config.PG_SSLMODE,
            },
            min_size=2,
            max_size=2,
            timeout=5,
        )
        try:
            unchecked.wait(timeout=10)
            with unchecked.connection() as conn:
                conn.execute("SELECT 1")

            _kill_backends(scratch_database)

            with pytest.raises(psycopg.Error):
                with unchecked.connection() as conn:
                    conn.execute("SELECT 1")
        finally:
            unchecked.close()
