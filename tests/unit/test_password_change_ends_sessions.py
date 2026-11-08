"""SECURITY.md item 13 — a password change ends the account's sessions issued before it.

A session is a JWT, and changing a password revoked none: a session opened before the
change, on another device or by whoever learned the old password, kept working until it
expired. Now the change writes ``users.tokens_valid_after`` and the guard hands each
token's ``iat`` to ``users.get_role``, which admits only a token issued since. The
caller who changed their own password gets a new session in the same response.

Against Postgres: ``tests/integration/test_password_change_ends_sessions.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import config
from src.security_fastapi import SESSION_COOKIE, create_access_token, resolve_principal
from src.services.passwords import hash_user_password
from src.services.users import UsersService
from tests.utils.auth import auth_headers, authenticated_state

pytestmark = pytest.mark.unit

USER = "55555555-5555-5555-5555-555555555555"
CURRENT = "the current password"
NEW = "a brand new password"
_CURRENT_HASH = hash_user_password(CURRENT)


def _db() -> MagicMock:
    db = MagicMock()
    db.is_connected = True
    db.users.get_by_id.return_value = {"id": USER, "username": "jo", "role": "user"}
    db.users.get_by_username.side_effect = lambda username: {
        "id": USER, "username": "jo", "is_active": True, "hashed_password": _CURRENT_HASH}
    db.users.update.return_value = True
    return db


def _written(db: MagicMock) -> datetime:
    return db.users.update.call_args.kwargs["tokens_valid_after"]


class TestTheChangeIsRecorded:
    def test_changing_your_own_password_ends_sessions_issued_before_now(self):
        db = _db()
        before = datetime.now(UTC).replace(microsecond=0)
        UsersService(db).change_own_password(USER, CURRENT, NEW)
        written = _written(db)
        assert (before <= written <= datetime.now(UTC), written.microsecond) == (True, 0)

    def test_an_admin_reset_ends_the_users_sessions_too(self):
        db = _db()
        before = datetime.now(UTC).replace(microsecond=0)
        UsersService(db).update_user(USER, {}, password="a-new-long-password")
        written = _written(db)
        assert (before <= written <= datetime.now(UTC), written.tzinfo) == (True, UTC)

    def test_an_admin_update_without_a_password_ends_no_session(self):
        """Changing an email must not sign the user out everywhere."""
        db = _db()
        UsersService(db).update_user(USER, {"email": "jo@example.com"}, password=None)
        assert "tokens_valid_after" not in db.users.update.call_args.kwargs

    def test_a_refused_change_writes_nothing(self):
        db = _db()
        with pytest.raises(Exception):  # noqa: B017 — the 400 itself is test_change_own_password's
            UsersService(db).change_own_password(USER, "not it", NEW)
        assert db.users.update.called is False


def _request(db: MagicMock, token: str) -> MagicMock:
    req = MagicMock()
    req.headers = {"Authorization": f"Bearer {token}"}
    req.cookies = {}
    req.app.state.db = db
    return req


class TestTheGuardComparesTheIssueTime:
    def test_the_tokens_iat_reaches_the_role_lookup(self):
        db = authenticated_state().db
        token = create_access_token(USER)
        iat = jwt.decode(token, config.JWT_SECRET_KEY, algorithms=["HS256"])["iat"]
        resolve_principal(_request(db, token))
        assert db.users.get_role.call_args.kwargs == {"issued_at": datetime.fromtimestamp(iat, tz=UTC)}

    def test_a_token_without_iat_reads_as_issued_at_the_epoch(self):
        """So any password change at all ends it, rather than none."""
        db = authenticated_state().db
        token = jwt.encode({"sub": USER, "jti": "j-1", "exp": 4102444800},
                           config.JWT_SECRET_KEY, algorithm="HS256")
        resolve_principal(_request(db, token))
        assert db.users.get_role.call_args.kwargs == {"issued_at": datetime.fromtimestamp(0, tz=UTC)}


def _client(db: MagicMock) -> TestClient:
    from src.routes_fastapi.auth_routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    user = db.users.get_by_id.return_value
    app.state = authenticated_state(db=db)
    db.users.get_by_id.return_value = user
    return TestClient(app, raise_server_exceptions=True)


class TestTheCallerKeepsGoing:
    def test_a_successful_change_sets_a_new_session_for_the_caller(self):
        resp = _client(_db()).post("/api/users/me/password", headers=auth_headers(USER),
                                   json={"current_password": CURRENT, "new_password": NEW})
        claims = jwt.decode(resp.cookies[SESSION_COOKIE], config.JWT_SECRET_KEY, algorithms=["HS256"])
        assert (resp.status_code, claims["sub"]) == (200, USER)

    def test_the_new_session_is_issued_no_earlier_than_the_change(self):
        """Otherwise the guard would refuse the session it was just given."""
        db = _db()
        resp = _client(db).post("/api/users/me/password", headers=auth_headers(USER),
                                json={"current_password": CURRENT, "new_password": NEW})
        claims = jwt.decode(resp.cookies[SESSION_COOKIE], config.JWT_SECRET_KEY, algorithms=["HS256"])
        assert datetime.fromtimestamp(claims["iat"], tz=UTC) >= _written(db)

    def test_a_refused_change_sets_no_session(self):
        resp = _client(_db()).post("/api/users/me/password", headers=auth_headers(USER),
                                   json={"current_password": "not it", "new_password": NEW})
        assert (resp.status_code, SESSION_COOKIE in resp.cookies) == (400, False)
