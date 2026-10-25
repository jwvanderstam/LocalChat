"""QP-2 S2 — with PG_APP_PASSWORD set, requests run as a role that owns nothing.

The audit's finding: the application connected as the database superuser, so a SQL
injection could reach `COPY ... TO PROGRAM` and run commands on the database host, or
drop the schema. This runs the real boot sequence (base schema, migrations, scoped role,
then the switch) against a database of its own, and asserts what the identity left
serving requests can and cannot do.

It also asserts what must *not* change yet (B2, ADR-5's amendment): unscoped paths still
read and write every row, through migration 0021's transition policy, and a scoped
transaction still sees only its own workspace.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.db]

psycopg = pytest.importorskip("psycopg", reason="role attributes are asserted against a real Postgres")

_ROOT = Path(__file__).resolve().parents[2]
_APP_PASSWORD = f"app-{uuid.uuid4().hex}"


def _admin_dsn() -> dict[str, Any]:
    from src import config

    return {
        "host": config.PG_HOST, "port": config.PG_PORT, "user": config.PG_USER,
        "password": config.PG_PASSWORD, "dbname": "postgres", "connect_timeout": 5,
    }


_PROBE = """
import json
import psycopg
from src.app_bootstrap import _drop_to_app_identity, _run_alembic_migrations
from src.db import Database
from src.utils.scope import ALL_WORKSPACES

db = Database()
ok, msg = db.initialize()
assert ok, msg
_run_alembic_migrations()
db.ensure_scoped_role()
_drop_to_app_identity(db)

out = {}
with db.get_connection() as conn:
    user, superuser = conn.execute(
        "SELECT current_user, rolsuper FROM pg_roles WHERE rolname = current_user").fetchone()
    out["user"], out["superuser"] = user, superuser

def refused(statement):
    try:
        with db.get_connection() as conn:
            conn.execute(statement)
    except psycopg.errors.InsufficientPrivilege:
        return True
    return False

out["copy_program_refused"] = refused("COPY (SELECT 1) TO PROGRAM 'true'")
out["create_table_refused"] = refused("CREATE TABLE s2_probe (id int)")
out["drop_table_refused"] = refused("DROP TABLE documents")

a = db.workspaces.create("s2-a", owner_id=None)
b = db.workspaces.create("s2-b", owner_id=None)
db.documents.insert("s2.md", "only in a", workspace_id=a, scope=a)
out["unscoped_sees_it"] = db.documents.count(scope=ALL_WORKSPACES) >= 1
with db.get_connection(scope=a) as conn:
    out["scope_a_docs"] = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
with db.get_connection(scope=b) as conn:
    out["scope_b_docs"] = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
print(json.dumps(out))
"""


@pytest.fixture(scope="module")
def probe() -> Iterator[dict[str, Any]]:
    dbname = f"s2_{uuid.uuid4().hex[:10]}"
    try:
        with psycopg.connect(**_admin_dsn()) as admin:  # type: ignore[arg-type]
            admin.autocommit = True
            admin.execute(f'CREATE DATABASE "{dbname}"')
    except psycopg.Error as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")
    try:
        result = subprocess.run(
            [sys.executable, "-c", _PROBE],
            cwd=_ROOT, env={**os.environ, "PG_DB": dbname, "PG_APP_PASSWORD": _APP_PASSWORD},
            capture_output=True, text=True, timeout=300,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        yield json.loads(result.stdout.strip().splitlines()[-1])
    finally:
        with psycopg.connect(**_admin_dsn()) as admin:  # type: ignore[arg-type]
            admin.autocommit = True
            admin.execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')


def test_requests_run_as_localchat_app_and_not_a_superuser(probe: dict[str, Any]) -> None:
    assert (probe["user"], probe["superuser"]) == ("localchat_app", False)


def test_copy_to_program_is_refused(probe: dict[str, Any]) -> None:
    """The route from a SQL injection to a shell on the database host."""
    assert probe["copy_program_refused"] is True


@pytest.mark.parametrize("statement", ["create_table_refused", "drop_table_refused"])
def test_ddl_is_refused(probe: dict[str, Any], statement: str) -> None:
    assert probe[statement] is True


def test_unscoped_paths_still_reach_every_row_through_the_transition_policy(
    probe: dict[str, Any],
) -> None:
    """B2: without 0021 the insert above would have been refused and nothing counted."""
    assert probe["unscoped_sees_it"] is True


def test_a_scoped_transaction_still_sees_only_its_own_workspace(probe: dict[str, Any]) -> None:
    assert (probe["scope_a_docs"], probe["scope_b_docs"]) == (1, 0)
