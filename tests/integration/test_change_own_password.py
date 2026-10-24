"""Changing your own password, against a real Postgres.

The unit tests prove the route's decisions against a mock. This proves the effect: the
stored hash really changes, the old password stops working and the new one starts,
and a refused change leaves the account exactly as it was.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.services.passwords import hash_user_password, verify_user_password
from tests.utils.auth import auth_headers

pytestmark = [pytest.mark.integration, pytest.mark.db]

CURRENT = "the current password"
NEW = "a brand new password"


@pytest.fixture(scope="module")
def database() -> Any:
    from src.db import Database

    db = Database()
    ok, message = db.initialize()
    if not ok or not db.is_connected:
        pytest.skip(f"PostgreSQL is not available: {message}")
    # CI's database gets only the base schema; users.deleted_at is migration 0007.
    # Alphabetically this module runs before any other that would migrate it.
    from src.app_bootstrap import _run_alembic_migrations

    _run_alembic_migrations()
    return db


@pytest.fixture()
def account(database: Any) -> Iterator[tuple[str, str]]:
    username = f"pwchange-{uuid.uuid4().hex[:8]}"
    user_id = database.users.create(username, hash_user_password(CURRENT), role="user")
    yield user_id, username
    database.users.retire(user_id)
    database.users.purge(user_id)


def _client(database: Any) -> TestClient:
    from src.routes_fastapi.auth_routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state = SimpleNamespace(db=database)
    return TestClient(app)


def _change(database: Any, user_id: str, current: str):
    return _client(database).post(
        "/api/users/me/password",
        json={"current_password": current, "new_password": NEW},
        headers=auth_headers(user_id),
    )


def _works(database: Any, username: str, password: str) -> bool:
    return verify_user_password(database.users, username, password) is not None


def test_after_a_change_only_the_new_password_signs_in(database, account):
    user_id, username = account
    resp = _change(database, user_id, CURRENT)
    assert (resp.status_code, _works(database, username, NEW),
            _works(database, username, CURRENT)) == (200, True, False)


def test_a_wrong_current_password_leaves_the_account_unchanged(database, account):
    user_id, username = account
    resp = _change(database, user_id, "not it")
    assert (resp.status_code, _works(database, username, CURRENT),
            _works(database, username, NEW)) == (400, True, False)
