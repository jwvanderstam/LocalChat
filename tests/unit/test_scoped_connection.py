"""P2-1b-iii — `get_connection(scope=...)` switches the transaction into the scoped role.

The integration test (`test_row_level_security.py`) proves the effect against Postgres.
This pins the statements themselves in the fast suite: the role switch, the workspace as a
bound parameter rather than interpolated text, and the owner role for everything else.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.db import Database
from src.db.connection import SCOPED_ROLE
from src.utils.scope import ALL_WORKSPACES

pytestmark = pytest.mark.unit

WS = "11111111-1111-1111-1111-111111111111"


def _db_with_pooled_connection() -> tuple[Database, MagicMock, MagicMock]:
    cur = MagicMock()
    conn = MagicMock()
    conn.autocommit = False
    conn.cursor.return_value.__enter__.return_value = cur
    db = Database()
    db.connection_pool = MagicMock()
    db.connection_pool.getconn.return_value = conn
    return db, conn, cur


def test_a_workspace_scope_switches_role_and_binds_the_workspace():
    db, _, cur = _db_with_pooled_connection()
    with db.get_connection(scope=WS):
        pass
    calls = [c.args for c in cur.execute.call_args_list]
    assert calls == [
        (f"SET LOCAL ROLE {SCOPED_ROLE}",),
        ("SELECT set_config('app.workspace_id', %s, true)", (WS,)),
        ("SET LOCAL hnsw.iterative_scan = strict_order",),
        ("SET LOCAL hnsw.ef_search = 400",),
    ]


@pytest.mark.parametrize("scope", [ALL_WORKSPACES, None], ids=["all-workspaces", "none"])
def test_every_other_scope_stays_on_the_owner_role(scope):
    db, _, cur = _db_with_pooled_connection()
    with db.get_connection(scope=scope):
        pass
    cur.execute.assert_not_called()


def test_an_autocommit_connection_is_refused_and_still_returned_to_the_pool():
    """Each statement would be its own transaction, so the role would lapse at once."""
    db, conn, cur = _db_with_pooled_connection()
    conn.autocommit = True
    with pytest.raises(RuntimeError, match="autocommit off"):
        with db.get_connection(scope=WS):
            pass
    cur.execute.assert_not_called()
    db.connection_pool.putconn.assert_called_once_with(conn)


def test_an_empty_workspace_is_refused_rather_than_scoped_to_nothing():
    db, _, cur = _db_with_pooled_connection()
    with pytest.raises(ValueError, match="workspace scope is required"):
        with db.get_connection(scope=""):
            pass
    cur.execute.assert_not_called()
