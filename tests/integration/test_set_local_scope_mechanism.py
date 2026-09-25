"""P2-1b precondition — that `SET LOCAL` is a safe carrier for a workspace scope.

P2-1b proposes Postgres row-level security keyed on `SET LOCAL app.workspace_id`,
so a query that reaches the database without a scope returns nothing rather than
everything. Its ticket carried an open precondition: `hnsw.ef_search` is known to
be dropped behind a pooler, so would this go the same way?

It does not, and the difference is the mechanism rather than the setting.
`ef_search` is set with a **session-level** `SET` in the pool's `configure`
callback and every later transaction relies on it persisting. `SET LOCAL` is
bounded to one transaction, and a transaction-pooling proxy holds one server
connection for the whole of a transaction by definition — so the scope cannot
outlive, or leak out of, the transaction that set it.

These four cases are that argument made executable. Cases 3 and 4 are the ones
that matter: they are what `ef_search` could not do.
"""

import uuid
from collections.abc import Iterator

import psycopg
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.db]

_WS_A = "11111111-1111-1111-1111-111111111111"
_WS_B = "22222222-2222-2222-2222-222222222222"


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
def scoped_table() -> Iterator[psycopg.Connection]:
    """A throwaway database with one RLS-protected table and a non-superuser.

    The role matters: RLS does not apply to the table owner or to a superuser,
    so running this as the admin would pass while proving nothing.
    """
    suffix = uuid.uuid4().hex[:10]
    dbname = f"rls_{suffix}"
    # A role is cluster-wide, not per-database, so it outlives the database it was
    # made for. Unique per run, and dropped in the same finally that drops the
    # database, or a failed run leaves it behind on the server.
    role = f"rls_probe_{suffix}"
    with psycopg.connect(**_admin_dsn(), autocommit=True) as admin:  # type: ignore[arg-type]
        admin.execute(f'CREATE DATABASE "{dbname}"')
    try:
        dsn = {**_admin_dsn(), "dbname": dbname}
        with psycopg.connect(**dsn) as conn:  # type: ignore[arg-type]
            conn.execute("CREATE TABLE docs (id int, workspace_id uuid, body text)")
            conn.execute(
                "INSERT INTO docs VALUES (1, %s, 'workspace A'), (2, %s, 'workspace B')",
                (_WS_A, _WS_B),
            )
            conn.execute("ALTER TABLE docs ENABLE ROW LEVEL SECURITY")
            conn.execute(
                "CREATE POLICY ws_isolation ON docs USING ("
                "  workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid"
                ")"
            )
            conn.execute(f'CREATE ROLE "{role}" NOLOGIN')
            conn.execute(f'GRANT SELECT ON docs TO "{role}"')
            conn.commit()
            conn.execute(f'SET ROLE "{role}"')
            conn.commit()
            yield conn
    finally:
        with psycopg.connect(**_admin_dsn(), autocommit=True) as admin:  # type: ignore[arg-type]
            admin.execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')
            admin.execute(f'DROP ROLE IF EXISTS "{role}"')


def _scope(conn: psycopg.Connection, workspace_id: str) -> None:
    """Set the transaction-local scope.

    `SET LOCAL app.workspace_id = %s` does not work: `SET` is a utility statement
    and takes no bind parameter, so the only way to write it is to interpolate the
    id into the SQL — an injection site on a value that decides what you can see.
    `set_config(name, value, is_local => true)` is an ordinary function call, takes
    the value as a parameter, and means exactly the same thing. P2-1b should use
    this form.
    """
    conn.execute("SELECT set_config('app.workspace_id', %s, true)", (workspace_id,))


def _count(conn: psycopg.Connection) -> int:
    row = conn.execute("SELECT count(*) FROM docs").fetchone()
    return int(row[0]) if row else -1


def test_a_query_with_no_scope_returns_nothing(scoped_table):
    """P2-1b's stated acceptance: reaching the database without a scope must
    return zero rows rather than every row."""
    assert _count(scoped_table) == 0
    scoped_table.rollback()


def test_a_scope_set_for_the_transaction_selects_that_workspace(scoped_table):
    _scope(scoped_table, _WS_A)
    row = scoped_table.execute("SELECT body FROM docs").fetchone()
    assert row is not None and row[0] == "workspace A"
    scoped_table.rollback()


def test_the_scope_does_not_survive_the_transaction(scoped_table):
    """The property `hnsw.ef_search` does not have, and the whole reason this is
    safe behind a transaction pooler: the scope cannot outlive its transaction."""
    _scope(scoped_table, _WS_A)
    assert _count(scoped_table) == 1
    scoped_table.commit()

    assert _count(scoped_table) == 0
    scoped_table.rollback()


def test_a_later_transaction_does_not_inherit_an_earlier_scope(scoped_table):
    """The leak case. pgbouncer in transaction mode does not reset session state,
    it leaks it between clients — which is what makes a session-level `SET`
    unsafe there. A `SET LOCAL` scope must not bleed into the next transaction."""
    _scope(scoped_table, _WS_A)
    assert _count(scoped_table) == 1
    scoped_table.commit()

    _scope(scoped_table, _WS_B)
    row = scoped_table.execute("SELECT body FROM docs").fetchone()
    assert row is not None and row[0] == "workspace B"
    scoped_table.rollback()
