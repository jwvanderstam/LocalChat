"""P2-1b — the database refuses an unscoped query on its own.

`test_object_authorization_matrix.py` proves no scoped call omits `scope=`, and
`test_object_authorization_over_the_wire.py` proves the routes refuse a foreign
workspace's object. Both are about the application. This is about the database: with
migration 0017 applied, a transaction that reaches Postgres without setting a scope gets
**zero rows** from every workspace-owned table rather than every row.

That is the ROADMAP acceptance for P2-1b, stated as an executable fact.

`test_set_local_scope_mechanism.py` already proved the *mechanism* on a throwaway table —
that `set_config(..., true)` is transaction-local, does not survive `COMMIT`, and is not
inherited by the next transaction. This proves the *schema*: that every table which should
carry the policy does, and that the policy behaves on the real tables with real foreign
keys between them.

Two things here are easy to get wrong and would make the whole suite vacuous:

* **RLS does not apply to a superuser or a table's owner.** The application connects as the
  owner, so these tests `SET LOCAL ROLE` into the restricted role first. Without that every
  assertion below passes while the policies do nothing.
* **A count of 0 proves nothing about an empty table.** So the seeded rows are asserted
  visible to the owner before they are asserted invisible to an unscoped transaction.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.db]

psycopg = pytest.importorskip("psycopg", reason="RLS is asserted against a real Postgres")

ROLE = "localchat_scoped"
POLICY = "localchat_workspace_isolation"

#: Mirrors migration 0017. Duplicated deliberately: if the migration's list changes and
#: this one does not, `test_every_protected_table_has_the_policy` fails and says so —
#: importing the migration's constant would make the two agree by construction and assert
#: nothing.
PROTECTED = (
    "documents",
    "conversations",
    "memories",
    "answer_feedback",
    "connectors",
    "workspace_api_keys",
    "workspace_members",
    "document_chunks",
    "conversation_messages",
    "annotations",
)


_ROOT = Path(__file__).resolve().parents[2]


def _admin_dsn() -> dict[str, Any]:
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
def conn() -> Iterator[Any]:
    """A database of its own, created and migrated, then connected to.

    Not the shared CI database, and that is the whole point. `_ensure_extensions_and_tables()`
    is what gives the shared database its schema; the Alembic chain is never applied to it —
    `test_migrations_apply.py` runs against a throwaway of its own, and the integration job
    runs plain `pytest`. So migration 0017's role and policies would be absent there, this
    module would skip, and a vacuous pass would look exactly like a real one.

    Owning the database also means these tests can seed freely without colliding with
    whatever else is in the shared one.
    """
    dbname = f"rls_{uuid.uuid4().hex[:10]}"
    try:
        with psycopg.connect(**_admin_dsn()) as admin:  # type: ignore[arg-type]
            admin.autocommit = True
            admin.execute(f'CREATE DATABASE "{dbname}"')
    except psycopg.Error as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")

    env = {**os.environ, "PG_DB": dbname}
    try:
        base = subprocess.run(
            [sys.executable, "-c",
             "from src.db import Database; ok, msg = Database().initialize();"
             " raise SystemExit(0 if ok else msg)"],
            cwd=_ROOT, env=env, capture_output=True, text=True, timeout=300,
        )
        assert base.returncode == 0, f"base schema failed: {base.stdout}{base.stderr}"
        migrate = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT, env=env, capture_output=True, text=True, timeout=300,
        )
        assert migrate.returncode == 0, f"migration failed: {migrate.stdout}{migrate.stderr}"

        with psycopg.connect(**{**_admin_dsn(), "dbname": dbname}) as connection:  # type: ignore[arg-type]
            # Autocommit, so each `conn.transaction()` below is a real transaction. Without
            # it the first bare execute opened an implicit one, every later transaction()
            # became a savepoint, and the SET LOCAL ROLE inside it outlived the savepoint —
            # so "the owner can see the row" could run as the restricted role.
            connection.autocommit = True
            yield connection
    finally:
        with psycopg.connect(**_admin_dsn()) as admin:  # type: ignore[arg-type]
            admin.autocommit = True
            admin.execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')

@pytest.fixture(scope="module")
def seeded(conn: Any) -> dict[str, str]:
    """One workspace with a row in every protected table, and a second workspace.

    Seeded as the owner, so RLS does not interfere with putting the rows there.
    """
    workspace_a = str(uuid.uuid4())
    workspace_b = str(uuid.uuid4())
    suffix = uuid.uuid4().hex[:8]

    with conn.transaction():
        for ws, name in ((workspace_a, f"rls-a-{suffix}"), (workspace_b, f"rls-b-{suffix}")):
            conn.execute("INSERT INTO workspaces (id, name) VALUES (%s, %s)", (ws, name))

        doc_id = conn.execute(
            "INSERT INTO documents (filename, content, workspace_id) VALUES (%s, %s, %s)"
            " RETURNING id",
            (f"rls-{suffix}.txt", "workspace A content", workspace_a),
        ).fetchone()[0]
        chunk_id = conn.execute(
            "INSERT INTO document_chunks (document_id, chunk_text, chunk_index, embedding)"
            " VALUES (%s, %s, 0, %s::vector) RETURNING id",
            (doc_id, "workspace A chunk", "[" + ",".join(["0"] * 768) + "]"),
        ).fetchone()[0]
        # conversations.id is the one table whose id has no server default: the
        # application generates it in Python, so the seed has to as well.
        conv_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO conversations (id, title, workspace_id) VALUES (%s, %s, %s)",
            (conv_id, "workspace A conversation", workspace_a),
        )
        conn.execute(
            "INSERT INTO conversation_messages (conversation_id, role, content)"
            " VALUES (%s, 'user', 'workspace A message')",
            (conv_id,),
        )
        conn.execute(
            "INSERT INTO annotations (chunk_id, text) VALUES (%s, %s)",
            (chunk_id, "workspace A annotation"),
        )
        conn.execute(
            "INSERT INTO memories (content, embedding, workspace_id)"
            " VALUES (%s, %s::vector, %s)",
            ("workspace A memory", "[" + ",".join(["0"] * 768) + "]", workspace_a),
        )
        conn.execute(
            "INSERT INTO answer_feedback (workspace_id, rating) VALUES (%s, 1)",
            (workspace_a,),
        )
        conn.execute(
            "INSERT INTO connectors (connector_type, display_name, config, workspace_id)"
            " VALUES ('webhook', %s, '{}', %s)",
            (f"rls-connector-{suffix}", workspace_a),
        )
        conn.execute(
            "INSERT INTO workspace_api_keys (workspace_id, name, key_prefix, key_hash)"
            " VALUES (%s, %s, %s, %s)",
            (workspace_a, f"rls-key-{suffix}", f"lcw_{suffix}", "x" * 64),
        )
        user_id = conn.execute(
            "INSERT INTO users (username, hashed_password, role)"
            " VALUES (%s, 'x', 'user') RETURNING id",
            (f"rls-user-{suffix}",),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO workspace_members (workspace_id, user_id, role)"
            " VALUES (%s, %s, 'editor')",
            (workspace_a, user_id),
        )
    return {"a": workspace_a, "b": workspace_b}


def _count(conn: Any, table: str, scope: str | None) -> int:
    """Rows visible in *table* to the restricted role, with *scope* set or not."""
    with conn.transaction():
        conn.execute(f'SET LOCAL ROLE "{ROLE}"')
        if scope is not None:
            conn.execute("SELECT set_config('app.workspace_id', %s, true)", (scope,))
        return int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


def test_every_protected_table_has_the_policy(conn: Any) -> None:
    """The schema half: a table added to the migration's list but not here fails too."""
    rows = conn.execute(
        "SELECT tablename FROM pg_policies WHERE schemaname = 'public' AND policyname = %s",
        (POLICY,),
    ).fetchall()
    assert sorted(r[0] for r in rows) == sorted(PROTECTED)


def test_row_level_security_is_enabled_on_every_protected_table(conn: Any) -> None:
    """A policy on a table without RLS enabled is inert — both are required."""
    rows = conn.execute(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
        " WHERE n.nspname = 'public' AND c.relrowsecurity AND c.relname = ANY(%s)",
        (list(PROTECTED),),
    ).fetchall()
    assert sorted(r[0] for r in rows) == sorted(PROTECTED)


@pytest.mark.parametrize("table", PROTECTED)
def test_the_owner_can_see_the_seeded_row(conn: Any, seeded: dict[str, str], table: str) -> None:
    """Makes the zero below mean something: the row is there, and RLS is what hides it."""
    with conn.transaction():
        assert int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]) > 0


@pytest.mark.parametrize("table", PROTECTED)
def test_a_transaction_with_no_scope_sees_nothing(
    conn: Any, seeded: dict[str, str], table: str
) -> None:
    """P2-1b's acceptance, table by table."""
    assert _count(conn, table, scope=None) == 0


@pytest.mark.parametrize("table", PROTECTED)
def test_a_foreign_scope_sees_nothing(conn: Any, seeded: dict[str, str], table: str) -> None:
    """The rows belong to workspace A; a transaction scoped to B must not see them."""
    assert _count(conn, table, scope=seeded["b"]) == 0


@pytest.mark.parametrize("table", PROTECTED)
def test_the_owning_scope_sees_its_row(conn: Any, seeded: dict[str, str], table: str) -> None:
    """The other side of the boundary — without this the policy could deny everything."""
    assert _count(conn, table, scope=seeded["a"]) > 0


def test_the_application_identity_may_switch_into_the_scoped_role(conn: Any) -> None:
    """Migration 0018 — the identity that ran the migrations holds the role with SET.

    Read from `pg_auth_members` rather than `pg_has_role`, which is true for any superuser
    and so would pass in CI without the grant. The row exists only because 0018 made it.
    `session_user`, not `current_user`: the login identity is the one that switches role,
    and `current_user` is whatever role an earlier test's `SET LOCAL ROLE` left in force.
    """
    rows = conn.execute(
        "SELECT m.set_option FROM pg_auth_members m"
        " JOIN pg_roles r ON r.oid = m.roleid"
        " JOIN pg_roles u ON u.oid = m.member"
        " WHERE r.rolname = %s AND u.rolname = session_user",
        (ROLE,),
    ).fetchall()
    assert rows == [(True,)]


def test_a_table_created_after_the_migrations_is_reachable_by_the_scoped_role(conn: Any) -> None:
    """Migration 0019 — default privileges.

    The base schema is created at boot before the chain runs, so a table a later release
    adds would otherwise exist with no grant for the role: fine as the owner, "permission
    denied" on the scoped path only.
    """
    name = f"rls_later_{uuid.uuid4().hex[:8]}"
    conn.execute(f"CREATE TABLE {name} (id int)")
    try:
        with conn.transaction():
            conn.execute(f'SET LOCAL ROLE "{ROLE}"')
            assert conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0] == 0
    finally:
        conn.execute(f"DROP TABLE {name}")


_APP_PROBE = """
import json, sys
from src.db import Database
from src.utils.scope import ALL_WORKSPACES
a, b = sys.argv[1], sys.argv[2]
db = Database()
ok, msg = db.initialize()
assert ok, msg
out = {}
with db.get_connection(scope=a) as c:
    out["scoped_user"], out["scoped_ws"] = c.execute(
        "SELECT current_user, current_setting('app.workspace_id')").fetchone()
    out["own_docs"] = c.execute("SELECT count(*) FROM documents").fetchone()[0]
with db.get_connection(scope=b) as c:
    out["foreign_docs"] = c.execute("SELECT count(*) FROM documents").fetchone()[0]
with db.get_connection(scope=ALL_WORKSPACES) as c:
    out["all_user"], out["all_docs"] = c.execute(
        "SELECT current_user, (SELECT count(*) FROM documents)").fetchone()
db.close()
print(json.dumps(out))
"""


def test_the_application_connection_enforces_the_scope(conn: Any, seeded: dict[str, str]) -> None:
    """P2-1b-iii — `get_connection(scope=...)` itself, not a hand-written SET LOCAL.

    The counts are unfiltered `SELECT count(*) FROM documents`: no WHERE clause, so what
    hides the foreign workspace's rows is the database, not the query.
    """
    import json

    result = subprocess.run(
        [sys.executable, "-c", _APP_PROBE, seeded["a"], seeded["b"]],
        cwd=_ROOT, env={**os.environ, "PG_DB": conn.info.dbname},
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out["scoped_user"] == ROLE
    assert out["scoped_ws"] == seeded["a"]
    assert out["own_docs"] == 1
    assert out["foreign_docs"] == 0
    # ALL_WORKSPACES stays the owner and sees workspace A's document too (ADR-5).
    assert out["all_user"] != ROLE
    assert out["all_docs"] >= 1


_RECALL_PROBE = """
import json, sys, uuid
import numpy as np
from src.db import Database
from src.utils.scope import ALL_WORKSPACES
n_ws, n_docs, n_chunks, top_k = 5, 40, 50, 40
rng = np.random.default_rng(7)
centres = rng.standard_normal((40, 768))
centres /= np.linalg.norm(centres, axis=1, keepdims=True)
def near(c):
    v = c + 0.04 * rng.standard_normal(768)
    return "[" + ",".join(f"{x:.5f}" for x in v / np.linalg.norm(v)) + "]"
db = Database()
ok, msg = db.initialize()
assert ok, msg
workspaces = [str(uuid.uuid4()) for _ in range(n_ws)]
with db.get_connection(scope=ALL_WORKSPACES) as c:
    with c.cursor() as cur:
        for i, ws in enumerate(workspaces):
            cur.execute("INSERT INTO workspaces (id, name) VALUES (%s, %s)", (ws, f"recall-{ws[:8]}"))
            for d in range(n_docs):
                cur.execute("INSERT INTO documents (filename, content, workspace_id)"
                            " VALUES (%s, 'x', %s) RETURNING id", (f"recall-{i}-{d}.md", ws))
                doc = cur.fetchone()[0]
                centre = centres[rng.integers(len(centres))]
                cur.executemany(
                    "INSERT INTO document_chunks (document_id, chunk_text, chunk_index, embedding)"
                    " VALUES (%s, 'x', %s, %s::vector)",
                    [(doc, k, near(centre)) for k in range(n_chunks)])
        cur.execute("ANALYZE documents")
        cur.execute("ANALYZE document_chunks")
counts = []
for _ in range(20):
    q = centres[rng.integers(len(centres))] + 0.04 * rng.standard_normal(768)
    q = (q / np.linalg.norm(q)).tolist()
    hits = db.search_similar_chunks(q, top_k=top_k, min_similarity=-1.0, scope=workspaces[0])
    counts.append(len(hits))
db.close()
print(json.dumps({"counts": counts, "top_k": top_k}))
"""


def test_a_scoped_vector_search_still_returns_top_k(conn: Any) -> None:
    """Under RLS the planner swaps the exact per-workspace scan for the HNSW index with the
    policy applied afterwards, which returned 19 of 40 requested rows on average and as few
    as 0. Iterative scan restores the count (P2-1b-iii); this fails if it stops applying.

    Ten thousand chunks is the smallest corpus that proves it: at four thousand the planner
    keeps the exact plan and this passes with the fix removed. Without it, 20 queries
    returned [34, 25, 38, 0, 0, 0, ...].
    """
    import json

    result = subprocess.run(
        [sys.executable, "-c", _RECALL_PROBE],
        cwd=_ROOT, env={**os.environ, "PG_DB": conn.info.dbname},
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert min(out["counts"]) == out["top_k"], out["counts"]
