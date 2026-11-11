"""SECURITY.md item 13 against Postgres — a password change ends the sessions issued before it.

The unit tests prove each part on a mock: the change writes ``tokens_valid_after``, the
guard hands the token's ``iat`` to ``users.get_role``, the route gives the caller a new
session. This proves the parts meet in the real query: a session opened before the
change is refused after it, the new one is admitted, and nobody else is signed out.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.security_fastapi import (
    SESSION_COOKIE,
    AuthError,
    create_access_token,
    resolve_principal,
)
from src.services.passwords import hash_user_password
from src.services.users import UsersService

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
    # CI's database gets only the base schema; tokens_valid_after is migration 0024.
    from src.app_bootstrap import _run_alembic_migrations

    _run_alembic_migrations()
    return db


@pytest.fixture()
def people(database: Any) -> Iterator[SimpleNamespace]:
    tag = uuid.uuid4().hex[:8]
    user = database.users.create(f"item13-{tag}", hash_user_password(CURRENT), role="user")
    other = database.users.create(f"item13-other-{tag}", hash_user_password(CURRENT), role="user")
    yield SimpleNamespace(user=user, other=other)
    for user_id in (user, other):
        database.users.retire(user_id)
        database.users.purge(user_id)


def _earlier_session(user_id: str) -> str:
    # A token's iat is whole seconds, and one issued in the same second as the change
    # passes by design; five seconds back makes "before" unambiguous.
    return create_access_token(user_id, {"iat": int(time.time()) - 5})


def _admitted(database: Any, token: str) -> bool:
    request = MagicMock()
    request.headers = {"Authorization": f"Bearer {token}"}
    request.cookies = {}
    request.app.state.db = database
    try:
        resolve_principal(request)
    except AuthError:
        return False
    return True


def _change_own(database: Any, token: str):
    from src.routes_fastapi.auth_routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state = SimpleNamespace(db=database)
    return TestClient(app).post(
        "/api/users/me/password",
        json={"current_password": CURRENT, "new_password": NEW},
        headers={"Authorization": f"Bearer {token}"},
    )


def test_a_session_from_before_the_change_is_admitted_until_it(database, people):
    # The control: without a change, the same earlier session works.
    assert _admitted(database, _earlier_session(people.user)) is True


def test_changing_your_own_password_ends_your_other_sessions(database, people):
    other_device = _earlier_session(people.user)
    resp = _change_own(database, _earlier_session(people.user))
    assert (resp.status_code, _admitted(database, other_device)) == (200, False)


def test_the_session_the_change_returns_is_admitted(database, people):
    resp = _change_own(database, _earlier_session(people.user))
    assert _admitted(database, resp.cookies[SESSION_COOKIE]) is True


def test_an_admin_reset_ends_the_users_sessions(database, people):
    session = _earlier_session(people.user)
    UsersService(database).update_user(people.user, {}, password="a-new-long-password")
    assert _admitted(database, session) is False


def test_another_users_sessions_are_untouched(database, people):
    theirs = _earlier_session(people.other)
    UsersService(database).update_user(people.user, {}, password="a-new-long-password")
    assert _admitted(database, theirs) is True


def test_an_update_without_a_password_ends_no_session(database, people):
    session = _earlier_session(people.user)
    UsersService(database).update_user(people.user, {"email": f"{uuid.uuid4().hex[:8]}@example.com"},
                                       password=None)
    assert _admitted(database, session) is True
