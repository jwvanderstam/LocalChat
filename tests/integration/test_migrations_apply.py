"""TQ-5b — the migration chain actually runs, and running it twice changes nothing.

Until TQ-2 no CI job had ever executed a migration: they run from `bootstrap_app()` at
startup, and CI builds its app with `create_app()`. Every revision in `versions/`
reached `main` unexecuted, with the first real run happening on a deployment.

TQ-2 made migrations run as a *side effect* of needing a correct schema. This asserts
them as a *property*, on a database of its own so nothing depends on what an earlier
test left behind:

* the upgrade succeeds, judged by **exit status** — `_run_alembic_migrations()` catches
  and logs failures, so the application starts happily on an unmigrated schema, and for
  several days in August 2026 that log line went to a logger Alembic had just disabled.
  A check reading output would have passed throughout. The process exit code cannot be
  swallowed.
* the database lands on the single head the script directory declares.
* a second upgrade is a no-op. "Additive migrations only" is a claim nothing verified.

**Correction to the ticket:** it specified "upgrade head against an *empty* database".
That fails here, and correctly so — `0002` opens with `ALTER TABLE conversations`, and
`IF NOT EXISTS` guards the column, not the table. The base schema comes from
`_ensure_extensions_and_tables()`; the migrations are additive on top of it. Those are
two halves of one schema by design (see CLAUDE.md), so the sequence under test is the
one production runs, not the one the ticket imagined.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator

import psycopg
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.db]

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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


def _alembic(command: str, dbname: str) -> subprocess.CompletedProcess[str]:
    """Run alembic as a process, so the assertion can be its exit status."""
    env = {**os.environ, "PG_DB": dbname}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *command.split()],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=300,
    )


@pytest.fixture(scope="module")
def migrated_database() -> Iterator[str]:
    """A database of its own: created, given the base schema, then migrated."""
    dbname = f"tq5b_{uuid.uuid4().hex[:10]}"
    try:
        with psycopg.connect(**_admin_dsn()) as conn:  # type: ignore[arg-type]
            conn.autocommit = True
            conn.execute(f'CREATE DATABASE "{dbname}"')
    except psycopg.Error as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")

    try:
        # The base schema, exactly as bootstrap creates it before migrating.
        create = subprocess.run(
            [sys.executable, "-c",
             "from src.db import Database; ok, msg = Database().initialize();"
             " raise SystemExit(0 if ok else msg)"],
            cwd=REPO_ROOT, env={**os.environ, "PG_DB": dbname},
            capture_output=True, text=True, timeout=300,
        )
        assert create.returncode == 0, f"base schema failed: {create.stdout}{create.stderr}"
        yield dbname
    finally:
        with psycopg.connect(**_admin_dsn()) as conn:  # type: ignore[arg-type]
            conn.autocommit = True
            conn.execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')


@pytest.mark.db
class TestTheChainApplies:
    def test_upgrade_head_exits_zero(self, migrated_database):
        """Exit status, not log output: a failure is logged and swallowed at startup."""
        result = _alembic("upgrade head", migrated_database)
        assert result.returncode == 0, result.stderr

    def test_database_lands_on_the_declared_head(self, migrated_database):
        _alembic("upgrade head", migrated_database)
        current = _alembic("current", migrated_database).stdout.strip().splitlines()
        heads = _alembic("heads", migrated_database).stdout.strip().splitlines()
        assert current and heads
        assert current[-1].split()[0] == heads[-1].split()[0]

    def test_the_head_is_marked_as_such(self, migrated_database):
        """`current` naming a revision that is not head means the chain stopped early."""
        current = _alembic("current", migrated_database).stdout.strip()
        assert "(head)" in current, current


@pytest.mark.db
class TestRunningItAgainChangesNothing:
    """Idempotency is what "additive migrations only" claims; nothing checked it."""

    def test_second_upgrade_exits_zero(self, migrated_database):
        _alembic("upgrade head", migrated_database)
        assert _alembic("upgrade head", migrated_database).returncode == 0

    def test_second_upgrade_leaves_the_revision_alone(self, migrated_database):
        _alembic("upgrade head", migrated_database)
        before = _alembic("current", migrated_database).stdout.strip()
        _alembic("upgrade head", migrated_database)
        assert _alembic("current", migrated_database).stdout.strip() == before

    def test_second_upgrade_applies_no_revision(self, migrated_database):
        """The stronger form: not just the same end state, but no work done."""
        _alembic("upgrade head", migrated_database)
        again = _alembic("upgrade head", migrated_database)
        assert "Running upgrade" not in (again.stdout + again.stderr)


@pytest.mark.db
class TestTheCheckWouldNoticeAFailure:
    """Guards the assertions above. A runner that reports success regardless proves
    nothing, and this suite's whole value is that it fails when the chain does."""

    def test_a_bad_revision_target_is_a_non_zero_exit(self, migrated_database):
        result = _alembic("upgrade nonexistent_revision", migrated_database)
        assert result.returncode != 0

    def test_an_unmigratable_database_is_a_non_zero_exit(self):
        """Against a database with no base schema, `0002` has no table to alter — which
        is also the evidence for the docstring's correction to the ticket."""
        dbname = f"tq5b_empty_{uuid.uuid4().hex[:8]}"
        try:
            with psycopg.connect(**_admin_dsn()) as conn:  # type: ignore[arg-type]
                conn.autocommit = True
                conn.execute(f'CREATE DATABASE "{dbname}"')
        except psycopg.Error as exc:
            pytest.skip(f"PostgreSQL is not available: {exc}")
        try:
            assert _alembic("upgrade head", dbname).returncode != 0
        finally:
            with psycopg.connect(**_admin_dsn()) as conn:  # type: ignore[arg-type]
                conn.autocommit = True
                conn.execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')
