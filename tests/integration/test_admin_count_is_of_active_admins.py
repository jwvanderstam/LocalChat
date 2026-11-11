"""R-10 against Postgres — the last-admin rule counts active admins, and why the body had to be strict.

The unit tests prove the route refuses a non-boolean ``is_active`` and the service asks
for the active count. This proves the two facts they rest on: the count moves only with
an active, live admin, and Postgres really does store the string ``"false"`` as false,
which is how that string got past the rule before the body was validated.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from src.services.passwords import hash_user_password

pytestmark = [pytest.mark.integration, pytest.mark.db]


@pytest.fixture(scope="module")
def database() -> Any:
    from src.db import Database

    db = Database()
    ok, message = db.initialize()
    if not ok or not db.is_connected:
        pytest.skip(f"PostgreSQL is not available: {message}")
    return db


@pytest.fixture()
def admin(database: Any) -> Iterator[str]:
    user_id = database.users.create(f"r10-{uuid.uuid4().hex[:8]}", hash_user_password("x" * 16), role="admin")
    yield user_id
    database.users.retire(user_id)
    database.users.purge(user_id)


def test_an_active_admin_is_counted(database, admin):
    before = database.users.count_active_admins()
    database.users.update(admin, is_active=False)
    assert database.users.count_active_admins() == before - 1


def test_a_retired_admin_is_not_counted(database, admin):
    before = database.users.count_active_admins()
    database.users.retire(admin)
    assert database.users.count_active_admins() == before - 1


def test_a_live_admin_that_is_deactivated_is_still_live(database, admin):
    """The bootstrap admin's check keeps counting live admins; only the rule changed."""
    before = database.users.count_live_admins()
    database.users.update(admin, is_active=False)
    assert database.users.count_live_admins() == before


def test_postgres_stores_the_string_false_as_false(database, admin):
    """The bypass the strict body closes: a string the rule's ``is False`` let through."""
    database.users.update(admin, is_active="false")
    assert database.users.get_by_id(admin)["is_active"] is False
