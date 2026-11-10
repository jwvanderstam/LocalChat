"""R-4 (QP-9 review) — access ends when the account or the workspace does, not at token expiry.

The guards read a caller's role from three places: `users.get_role` (global),
`members.role` (per workspace) and `api_keys.resolve` (a key's workspace). None of them
asked whether the user was still active, or whether the workspace was still live, so:

* a deactivated user kept their workspace roles, and a deactivated admin stayed admin,
  until the token expired;
* a retired user lost `is_admin` but kept every membership, which for an admin is owner
  of every workspace 0014 gave them;
* a retired workspace stayed readable by its members and its API keys indefinitely.

Each is set up against Postgres with the permitted case beside it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from types import SimpleNamespace

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.db]


@pytest.fixture(scope="module")
def database():
    from src.db import Database

    db = Database()
    ok, message = db.initialize()
    if not ok or not db.is_connected:
        pytest.skip(f"PostgreSQL is not available: {message}")

    from src.app_bootstrap import _run_alembic_migrations

    _run_alembic_migrations()
    return db


@pytest.fixture
def world(database) -> Iterator[SimpleNamespace]:
    tag = uuid.uuid4().hex[:8]
    ws = database.workspaces.create(f"r4-{tag}", owner_id=None)
    user = database.users.create(f"r4-user-{tag}", "not-a-real-hash")
    admin = database.users.create(f"r4-admin-{tag}", "not-a-real-hash", role="admin")
    database.members.add(ws, user, "editor")
    key, _row = database.api_keys.create(ws, f"r4-key-{tag}", role="viewer")
    yield SimpleNamespace(ws=ws, user=user, admin=admin, key=key)
    database.workspaces.retire(ws)
    database.users.retire(user)
    database.users.retire(admin)


def test_an_active_member_has_their_role(database, world):
    # The permitted case for the three membership tests below.
    assert database.members.role(world.ws, world.user) == "editor"


def test_a_deactivated_member_has_no_role(database, world):
    database.users.update(world.user, is_active=False)
    assert database.members.role(world.ws, world.user) is None


def test_a_retired_member_has_no_role(database, world):
    database.users.retire(world.user)
    assert database.members.role(world.ws, world.user) is None


def test_a_member_of_a_retired_workspace_has_no_role_there(database, world):
    database.workspaces.retire(world.ws)
    assert database.members.role(world.ws, world.user) is None


def test_an_active_admin_is_admin(database, world):
    assert database.users.get_role(world.admin) == "admin"


def test_a_deactivated_admin_has_no_global_role(database, world):
    database.users.update(world.admin, is_active=False)
    assert database.users.get_role(world.admin) is None


def test_a_key_resolves_to_its_live_workspace(database, world):
    assert database.api_keys.resolve(world.key) == (world.ws, "viewer")


def test_a_key_of_a_retired_workspace_resolves_to_nothing(database, world):
    database.workspaces.retire(world.ws)
    assert database.api_keys.resolve(world.key) is None
