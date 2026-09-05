"""Every database connection carries an explicit `sslmode`.

libpq's own default is `prefer`, which negotiates TLS and then **silently accepts
an unencrypted connection** when the negotiation fails. Against a container on the
same host that is tolerable; against a managed database reached over the public
internet it is a downgrade nobody is told about. `PG_SSLMODE` makes the choice
explicit, and a managed deployment sets `require`.
"""

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


def _database():
    from src import db as db_module

    return db_module.Database()


class TestThePoolCarriesSslmode:
    def test_pool_kwargs_use_the_configured_sslmode(self, monkeypatch):
        monkeypatch.setattr("src.config.PG_SSLMODE", "require")
        test_db = _database()
        mock_conn = MagicMock()
        mock_conn.info.transaction_status = 0

        with patch.object(test_db, "check_server_availability", return_value=(True, "OK")):
            with patch("psycopg.connect", return_value=mock_conn):
                with patch("src.db.connection.ConnectionPool") as mock_pool:
                    with patch.object(test_db, "_ensure_extensions_and_tables"):
                        test_db.initialize()

        assert mock_pool.call_args.kwargs["kwargs"]["sslmode"] == "require"

    def test_a_different_value_reaches_the_pool_unchanged(self, monkeypatch):
        """The explicit value must win over libpq's default, not merely differ from it."""
        monkeypatch.setattr("src.config.PG_SSLMODE", "verify-full")
        test_db = _database()
        mock_conn = MagicMock()
        mock_conn.info.transaction_status = 0

        with patch.object(test_db, "check_server_availability", return_value=(True, "OK")):
            with patch("psycopg.connect", return_value=mock_conn):
                with patch("src.db.connection.ConnectionPool") as mock_pool:
                    with patch.object(test_db, "_ensure_extensions_and_tables"):
                        test_db.initialize()

        assert mock_pool.call_args.kwargs["kwargs"]["sslmode"] == "verify-full"


class TestTheBootstrapConnectionsCarryItToo:
    def test_ensure_vector_extension_connects_with_sslmode(self, monkeypatch):
        """It runs before the pool exists, so it needs the setting in its own right."""
        monkeypatch.setattr("src.config.PG_SSLMODE", "require")
        test_db = _database()
        mock_conn = MagicMock()
        mock_conn.info.transaction_status = 0

        with patch.object(test_db, "check_server_availability", return_value=(True, "OK")):
            with patch("psycopg.connect", return_value=mock_conn) as mock_connect:
                with patch("src.db.connection.ConnectionPool"):
                    with patch.object(test_db, "_ensure_extensions_and_tables"):
                        test_db.initialize()

        assert mock_connect.call_args.kwargs["sslmode"] == "require"

    def test_create_database_connects_with_sslmode(self, monkeypatch):
        """The 'database does not exist' path opens its own connection to `postgres`."""
        monkeypatch.setattr("src.config.PG_SSLMODE", "require")
        test_db = _database()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        with patch("psycopg.connect") as mock_connect:
            mock_connect.return_value.__enter__.return_value = mock_conn
            test_db._create_database()

        assert mock_connect.call_args.kwargs["sslmode"] == "require"


class TestTheDefaultIsUnchangedForLocalUse:
    def test_default_is_prefer_so_the_compose_stack_still_connects(self):
        """postgres:16 ships without TLS; a stricter default would break `docker compose up`."""
        import importlib

        import src.config as config_module

        importlib.reload(config_module)
        assert config_module.PG_SSLMODE == "prefer"
