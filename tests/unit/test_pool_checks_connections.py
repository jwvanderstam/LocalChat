"""Both pool constructions check a connection before handing it out.

`Database.initialize()` builds a pool twice: once normally, and once more on the
"database does not exist" recovery path. The second is the one a change forgets,
so it is asserted separately rather than assumed to match the first.

The behaviour this configuration buys — a killed connection being replaced before
the caller sees it — is proven against a real PostgreSQL in
`tests/integration/test_pool_survives_a_lost_database.py`. This file only asserts
that the pool is asked to do it, in both places.
"""

from unittest.mock import MagicMock, patch

import psycopg
import pytest
from psycopg_pool import ConnectionPool

pytestmark = pytest.mark.unit


def _database():
    from src import db as db_module

    return db_module.Database()


def _initialise(pool_patch, connect_side_effect=None):
    test_db = _database()
    mock_conn = MagicMock()
    mock_conn.info.transaction_status = 0

    with patch.object(test_db, "check_server_availability", return_value=(True, "OK")):
        with patch("psycopg.connect", side_effect=connect_side_effect, return_value=mock_conn):
            with patch("src.db.connection.ConnectionPool", pool_patch):
                with patch.object(test_db, "_ensure_extensions_and_tables"):
                    test_db.initialize()
    return test_db


class TestTheNormalPath:
    def test_the_pool_is_told_to_check_connections(self):
        """Asserted against the pool class's own attribute, so a hand-rolled
        no-op passed as `check` would fail this rather than satisfy it."""
        pool = MagicMock()
        _initialise(pool)

        assert pool.call_args.kwargs["check"] is pool.check_connection


class TestTheDatabaseDidNotExistPath:
    def test_the_recovery_pool_checks_connections_too(self):
        """Built in a second place, and just as exposed to a server that went away."""
        pool = MagicMock()
        pool.side_effect = [
            psycopg.OperationalError('database "rag_db" does not exist'),
            MagicMock(),
        ]
        test_db = _database()
        mock_conn = MagicMock()
        mock_conn.info.transaction_status = 0

        with patch.object(test_db, "check_server_availability", return_value=(True, "OK")):
            with patch("psycopg.connect", return_value=mock_conn):
                with patch("src.db.connection.ConnectionPool", pool):
                    with patch.object(test_db, "_ensure_extensions_and_tables"):
                        with patch.object(test_db, "_create_database"):
                            test_db.initialize()

        assert pool.call_count == 2, "the recovery path did not build a second pool"
        assert pool.call_args_list[1].kwargs["check"] is pool.check_connection


class TestTheDependencyStillOffersIt:
    def test_psycopg_pool_provides_check_connection(self):
        """The reference above is only as good as psycopg keeping this callable.

        An upgrade that renamed or removed it would leave the mocked tests green
        and the real pool constructed with `check=<AttributeError>`.
        """
        assert callable(ConnectionPool.check_connection)
