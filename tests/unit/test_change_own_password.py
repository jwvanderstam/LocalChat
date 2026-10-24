"""A signed-in user changes their own password: POST /api/users/me/password.

The route existed with no screen behind it, and three things were wrong with it that
the screen would have exposed at once:
- it answered a wrong current password with 401, which the frontend reads as an
  expired session and redirects to the login page, so a typo signed the user out;
- it identified the caller by decoding the token only, so a logged-out (revoked)
  token was still accepted, the one guard in the file that skipped revocation (H1);
- it took any new password, one character included, and was not rate-limited,
  though knowing the current password is its whole proof.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded
from werkzeug.security import check_password_hash

from src import config
from src.security_fastapi import limiter
from src.services.errors import ServiceError as PasswordChangeError
from src.services.passwords import hash_user_password
from src.services.users import UsersService
from tests.utils.auth import auth_headers, authenticated_state

pytestmark = pytest.mark.unit

USER = "44444444-4444-4444-4444-444444444444"
CURRENT = "the current password"
NEW = "a brand new password"
_URL = "/api/users/me/password"


_CURRENT_HASH = hash_user_password(CURRENT)


def _db(*, current_ok: bool = True, user: dict | None = None, updated: bool = True) -> MagicMock:
    db = MagicMock()
    db.users.get_by_id.return_value = (
        {"id": USER, "username": "jo", "role": "user"} if user is None else user
    )
    # A fresh row per call: the password check pops the hash off what it is given.
    db.users.get_by_username.side_effect = lambda username: (
        {"id": USER, "username": "jo", "is_active": True, "hashed_password": _CURRENT_HASH}
        if current_ok else None
    )
    db.users.update.return_value = updated
    return db


def change_own_password(db: MagicMock, user_id: str, current: str, new: str) -> None:
    UsersService(db).change_own_password(user_id, current, new)


def _stored_hash(db: MagicMock) -> str:
    return db.users.update.call_args.kwargs["hashed_password"]


class TestTheService:
    def test_the_right_current_password_stores_a_hash_of_the_new_one(self):
        db = _db()
        change_own_password(db, USER, CURRENT, NEW)
        stored = _stored_hash(db)
        assert (check_password_hash(stored, NEW), check_password_hash(stored, CURRENT)) == (
            True, False)

    def test_a_wrong_current_password_is_400_and_writes_nothing(self):
        db = _db()
        with pytest.raises(PasswordChangeError) as exc_info:
            change_own_password(db, USER, "not it", NEW)
        assert (exc_info.value.status_code, exc_info.value.message, db.users.update.called) == (
            400, "Current password is incorrect", False)

    def test_the_bootstrap_admin_has_no_row_and_never_reaches_the_database(self):
        """Its id is the string "admin", which Postgres would refuse as a UUID with a 500."""
        db = _db()
        with pytest.raises(PasswordChangeError) as exc_info:
            change_own_password(db, "admin", CURRENT, NEW)
        assert (exc_info.value.status_code, db.users.get_by_id.called) == (409, False)

    def test_a_user_who_no_longer_exists_is_409(self):
        db = _db()
        db.users.get_by_id.return_value = None
        with pytest.raises(PasswordChangeError) as exc_info:
            change_own_password(db, USER, CURRENT, NEW)
        assert exc_info.value.status_code == 409

    def test_an_update_that_changed_no_row_is_not_reported_as_success(self):
        """The account was retired between the check and the write."""
        with pytest.raises(PasswordChangeError) as exc_info:
            change_own_password(_db(updated=False), USER, CURRENT, NEW)
        assert exc_info.value.status_code == 409


def _client(db: MagicMock, *, revoked: bool = False) -> TestClient:
    from src.routes_fastapi.auth_routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    user = db.users.get_by_id.return_value
    app.state = authenticated_state(db=db)
    # authenticated_state answers users.get_by_id for the role lookup, without a
    # username; put back the row this test set up.
    db.users.get_by_id.return_value = user
    db.tokens.is_revoked.return_value = revoked
    # slowapi's own handler reads the limiter off app.state, which is a mock here.
    app.add_exception_handler(
        RateLimitExceeded, lambda request, exc: JSONResponse({}, status_code=429)
    )
    return TestClient(app, raise_server_exceptions=True)


def _post(client: TestClient, body: dict, headers: dict | None = None):
    return client.post(_URL, json=body, headers=auth_headers(USER) if headers is None else headers)


class TestTheRoute:
    def test_a_valid_change_answers_success(self):
        db = _db()
        resp = _post(_client(db), {"current_password": CURRENT, "new_password": NEW})
        assert (resp.status_code, resp.json()) == (200, {"success": True})

    def test_a_wrong_current_password_is_400_so_the_session_survives(self):
        resp = _post(_client(_db()), {"current_password": "not it", "new_password": NEW})
        assert (resp.status_code, resp.json()["message"]) == (400, "Current password is incorrect")

    def test_a_new_password_one_short_of_the_minimum_is_refused_before_the_database(self):
        db = _db()
        short = "x" * (config.USER_PASSWORD_MIN_LENGTH - 1)
        resp = _post(_client(db), {"current_password": CURRENT, "new_password": short})
        assert (resp.status_code, db.users.get_by_username.called) == (400, False)

    def test_a_new_password_at_the_minimum_is_accepted(self):
        exact = "x" * config.USER_PASSWORD_MIN_LENGTH
        resp = _post(_client(_db()), {"current_password": CURRENT, "new_password": exact})
        assert resp.status_code == 200

    def test_the_new_password_is_stored_as_typed_spaces_included(self):
        db = _db()
        _post(_client(db), {"current_password": CURRENT, "new_password": "  spaced out pw  "})
        assert check_password_hash(_stored_hash(db), "  spaced out pw  ") is True

    def test_a_missing_field_is_400_not_a_server_error(self):
        resp = _post(_client(_db()), {"new_password": NEW})
        assert resp.status_code == 400

    def test_no_session_is_401(self):
        resp = _post(_client(_db()), {"current_password": CURRENT, "new_password": NEW}, headers={})
        assert resp.status_code == 401

    def test_a_revoked_token_is_refused(self):
        """A logged-out session must not change the password, even knowing it."""
        db = _db()
        resp = _post(_client(db, revoked=True), {"current_password": CURRENT, "new_password": NEW})
        assert (resp.status_code, db.users.update.called) == (401, False)

    def test_the_caller_changes_only_their_own_account(self):
        db = _db()
        _post(_client(db), {"current_password": CURRENT, "new_password": NEW})
        assert db.users.update.call_args.args == (USER,)


@pytest.fixture
def live_limiter():
    was_enabled = limiter.enabled
    limiter.enabled = True
    limiter.reset()
    yield
    limiter.reset()
    limiter.enabled = was_enabled


def test_guessing_the_current_password_is_rate_limited_like_login(live_limiter):
    allowed = int(config.RATELIMIT_LOGIN.split()[0])
    client = _client(_db())
    statuses = [
        _post(client, {"current_password": f"guess {i}", "new_password": NEW}).status_code
        for i in range(allowed + 1)
    ]
    assert statuses == [400] * allowed + [429]
