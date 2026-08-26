"""The pool warns when ``SET hnsw.ef_search`` does not survive a transaction.

A transaction-pooling proxy resets session state between transactions, so the GUC
the pool sets once per connection is gone by the first real query. Vector search
then runs at the server default: lower recall, no error, no log line. These tests
are the difference between that being a signal and being invisible.
"""

from unittest.mock import MagicMock

import psycopg
import pytest

from src.db import connection as connection_module
from src.db.connection import EF_SEARCH_EXPECTED, _warn_if_ef_search_did_not_stick


@pytest.fixture(autouse=True)
def _reset_warning_latch(monkeypatch):
    # The latch is process-wide by design; a test that inherited it from another
    # test would pass while asserting nothing.
    monkeypatch.setattr(connection_module, "_ef_search_warning_issued", False)


def _conn_reading_back(value, error=None):
    conn = MagicMock()
    cursor = MagicMock()
    if error is not None:
        cursor.execute.side_effect = error
    cursor.fetchone.return_value = None if value is None else (value,)
    conn.cursor.return_value.__enter__.return_value = cursor
    return conn


def test_no_warning_when_the_setting_survived(caplog):
    conn = _conn_reading_back(EF_SEARCH_EXPECTED)

    with caplog.at_level("WARNING"):
        _warn_if_ef_search_did_not_stick(conn)

    assert caplog.records == []
    assert connection_module._ef_search_warning_issued is False


def test_warns_with_the_observed_value_when_the_proxy_reset_it(caplog):
    conn = _conn_reading_back("40")

    with caplog.at_level("WARNING"):
        _warn_if_ef_search_did_not_stick(conn)

    assert len(caplog.records) == 1
    message = caplog.records[0].message
    assert "'40'" in message
    assert EF_SEARCH_EXPECTED in message
    assert connection_module._ef_search_warning_issued is True


def test_warns_only_once_across_connections(caplog):
    with caplog.at_level("WARNING"):
        _warn_if_ef_search_did_not_stick(_conn_reading_back("40"))
        _warn_if_ef_search_did_not_stick(_conn_reading_back("40"))
        _warn_if_ef_search_did_not_stick(_conn_reading_back("64"))

    # One line, not one per pooled connection for the life of the process.
    assert len(caplog.records) == 1


def test_the_read_back_runs_in_its_own_transaction():
    # Reading it back inside the transaction that set it would pass under exactly
    # the proxy this guards against. The rollback is what makes the check real.
    conn = _conn_reading_back(EF_SEARCH_EXPECTED)

    _warn_if_ef_search_did_not_stick(conn)

    conn.rollback.assert_called_once()


def test_a_database_error_is_not_fatal_and_does_not_warn(caplog):
    conn = _conn_reading_back(None, error=psycopg.OperationalError("SHOW failed"))

    with caplog.at_level("WARNING"):
        _warn_if_ef_search_did_not_stick(conn)

    # Degrading a diagnostic must not look like the degradation it reports.
    assert caplog.records == []
    assert connection_module._ef_search_warning_issued is False


def test_an_empty_result_is_treated_as_not_stuck(caplog):
    conn = _conn_reading_back(None)

    with caplog.at_level("WARNING"):
        _warn_if_ef_search_did_not_stick(conn)

    assert len(caplog.records) == 1
    assert "None" in caplog.records[0].message
