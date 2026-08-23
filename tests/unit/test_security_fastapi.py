"""Unit tests for src/security_fastapi.py."""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, patch

import pytest

#: PBKDF2 rounds `verify_credentials` uses. Spelled out rather than imported so a
#: change to the real constant fails these tests instead of following them silently.
_PBKDF2_ROUNDS = 100_000


@pytest.fixture
def env_admin_password(monkeypatch):
    """A known env-var admin password, so the *success* path can be asserted.

    Without this the tests below depend on whatever `ADMIN_PASSWORD` the
    environment happens to hold. Unset — as in a bare container — every call
    returns None at the first guard, and a test asserting None passes without
    reaching the password comparison at all (TQ-3).
    """
    from src import security_fastapi as sec

    password = "known-admin-password-for-tests"
    salt = b"\x17" * 32
    monkeypatch.setattr(sec, "_ADMIN_PASSWORD_RAW", password)
    monkeypatch.setattr(sec, "_ADMIN_PASSWORD_SALT", salt)
    monkeypatch.setattr(
        sec, "_ADMIN_PASSWORD_HASH",
        hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS),
    )
    return password


@pytest.mark.unit
class TestCreateAccessToken:
    def test_returns_string(self):
        from src.security_fastapi import create_access_token

        token = create_access_token("user-123")
        assert isinstance(token, str)
        assert len(token) > 20

    def test_with_additional_claims(self):
        from src.security_fastapi import create_access_token

        token = create_access_token("user-abc", {"role": "admin"})
        assert isinstance(token, str)


@pytest.mark.unit
class TestVerifyCredentials:
    def test_wrong_username_returns_none(self):
        from src.security_fastapi import verify_credentials

        assert verify_credentials("wronguser", "anypassword") is None

    def test_admin_wrong_password_returns_none(self, env_admin_password):
        from src.security_fastapi import verify_credentials

        result = verify_credentials("admin", "definitely-wrong-password-xyz")
        assert result is None

    def test_correct_admin_credentials_return_the_admin_subject_and_role(
            self, env_admin_password):
        """The success path, asserted for the first time. Every test here checked a
        rejection, so mutating the return value — or the guard that reaches it —
        changed nothing any test could see."""
        from src.security_fastapi import verify_credentials

        assert verify_credentials("admin", env_admin_password) == ("admin", "admin")

    def test_another_username_with_the_admin_password_is_refused(
            self, env_admin_password):
        """Inverting the username guard makes this account's password work for *any*
        username, authenticated as admin. Only a correct password reaches that far,
        so a wrong-password test cannot detect it."""
        from src.security_fastapi import verify_credentials

        assert verify_credentials("someone-else", env_admin_password) is None

    def test_no_admin_password_returns_none(self):
        from src.security_fastapi import verify_credentials

        with patch("src.security_fastapi._ADMIN_PASSWORD_RAW", ""):
            result = verify_credentials("admin", "anything")
            assert result is None


@pytest.mark.unit
class TestSessionAndTokenContracts:
    """TQ-3. Three names other code depends on by value, none of them asserted:
    renaming any of them left the whole suite green."""

    def test_the_session_cookie_name_is_fixed(self):
        """The browser sends this name; changing it signs everyone out at once."""
        from src.security_fastapi import SESSION_COOKIE

        assert SESSION_COOKIE == "localchat_session"

    def test_every_token_carries_a_jti(self):
        """Revocation is keyed on `jti` (SEC-2). A token minted without one cannot
        be revoked at all."""
        from src.security_fastapi import _decode_token, create_access_token

        claims = _decode_token(create_access_token("user-abc"))

        assert claims["jti"]

    def test_two_tokens_for_one_user_get_different_jtis(self):
        """A shared jti would revoke every session a user has, not the one asked
        for — and the assertion above passes for a constant."""
        from src.security_fastapi import _decode_token, create_access_token

        first = _decode_token(create_access_token("user-abc"))["jti"]
        second = _decode_token(create_access_token("user-abc"))["jti"]

        assert first != second


@pytest.mark.unit
class TestVerifyCredentialsDb:
    def test_db_user_found(self):
        from src.security_fastapi import verify_credentials_db

        db = MagicMock()
        db.is_connected = True
        db.verify_user_password.return_value = {"id": "u1", "role": "user"}
        result = verify_credentials_db("alice", "secret", db)
        assert result == ("u1", "user")

    def test_the_row_s_own_role_is_returned_not_the_fallback(self):
        """TQ-3. The case above uses a row whose role is `"user"` — the same value
        the fallback supplies — so it passes whether the role is read or invented."""
        from src.security_fastapi import verify_credentials_db

        db = MagicMock()
        db.is_connected = True
        db.verify_user_password.return_value = {"id": "u1", "role": "admin"}

        assert verify_credentials_db("alice", "secret", db) == ("u1", "admin")

    def test_a_row_with_no_role_falls_back_to_the_least_privileged_one(self):
        from src.security_fastapi import verify_credentials_db

        db = MagicMock()
        db.is_connected = True
        db.verify_user_password.return_value = {"id": "u1"}

        assert verify_credentials_db("alice", "secret", db) == ("u1", "user")

    def test_a_database_object_without_is_connected_is_not_consulted(self):
        """TQ-3. The `False` default in `getattr(db, "is_connected", False)`: with
        it flipped, an object that never reports connectivity gets asked to
        authenticate anyway. A MagicMock always has the attribute, so only a real
        object without one reaches the default."""
        from src.security_fastapi import verify_credentials_db

        class DatabaseWithoutTheAttribute:
            def verify_user_password(self, username: str, password: str) -> dict[str, str]:
                return {"id": "u1", "role": "admin"}

        # Falls through to the env-var admin, which refuses a non-admin username.
        assert verify_credentials_db("alice", "secret", DatabaseWithoutTheAttribute()) is None

    def test_db_not_connected_falls_back(self):
        from src.security_fastapi import verify_credentials_db

        db = MagicMock()
        db.is_connected = False
        # Falls back to env-var admin check; wrong password → None
        result = verify_credentials_db("alice", "secret", db)
        assert result is None

    def test_db_none_falls_back(self):
        from src.security_fastapi import verify_credentials_db

        result = verify_credentials_db("alice", "secret", None)
        assert result is None


@pytest.mark.unit
class TestGetCurrentUserId:
    def _make_request(self, auth_header=None, revoked=False):
        req = MagicMock()
        req.app.state.db.is_connected = True
        req.app.state.db.is_token_revoked.return_value = revoked
        headers = {}
        if auth_header:
            headers["Authorization"] = auth_header
        req.headers.get = lambda k, default="": headers.get(k, default)
        req.cookies = {}
        return req

    def test_no_credentials_no_header_returns_none(self):
        from src.security_fastapi import get_current_user_id

        assert get_current_user_id(self._make_request(), credentials=None) is None

    def test_valid_token_in_bearer_header_resolves_to_its_subject(self):
        """Previously `result is None or result == "user-xyz"` — true either way, so it
        proved nothing. With the bypass gone the real subject can be asserted."""
        from src.security_fastapi import create_access_token, get_current_user_id

        token = create_access_token("user-xyz")
        req = self._make_request(auth_header=f"Bearer {token}")
        assert get_current_user_id(req, credentials=None) == "user-xyz"

    def test_a_garbage_token_resolves_to_nobody(self):
        from src.security_fastapi import get_current_user_id

        req = self._make_request(auth_header="Bearer not-a-token")
        assert get_current_user_id(req, credentials=None) is None


@pytest.mark.unit
class TestRequireAuth:
    """The "testing mode returns anonymous" cases are deleted, not rewritten: TQ-1b
    removed the mode. There is no longer a caller the application trusts by default."""

    def _anonymous_request(self):
        req = MagicMock()
        req.headers.get = lambda k, default="": default
        req.cookies = {}
        return req

    def test_no_credentials_raises_401(self):
        from fastapi import HTTPException

        from src.security_fastapi import require_auth

        request = self._anonymous_request()
        with pytest.raises(HTTPException) as exc_info:
            require_auth(request, credentials=None)
        assert exc_info.value.status_code == 401


@pytest.mark.unit
class TestRequireAdminDep:
    def _anonymous_request(self):
        req = MagicMock()
        req.headers.get = lambda k, default="": default
        req.cookies = {}
        return req

    def test_no_credentials_raises_401(self):
        from fastapi import HTTPException

        from src.security_fastapi import require_admin_dep

        request = self._anonymous_request()
        with pytest.raises(HTTPException) as exc_info:
            require_admin_dep(request, credentials=None)
        assert exc_info.value.status_code == 401

    # ---- the role is read from the database, not from the token ----------------
    #
    # The role is minted into the JWT at login and the token lives two hours. Trusting
    # that claim let a demoted administrator keep administrative access until expiry,
    # while /api/users/me read the database and already showed the new role — so the
    # UI and the guard disagreed about who was an admin.

    def _request_with(self, role_in_db, *, connected=True, user_exists=True):
        """A request whose token claims admin, with the database saying otherwise."""
        from src.security_fastapi import create_access_token

        token = create_access_token("55555555-5555-5555-5555-555555555555", {"role": "admin"})
        req = MagicMock()
        req.headers.get = lambda k, default="": (f"Bearer {token}" if k == "Authorization" else default)
        req.cookies = {}
        db = MagicMock()
        db.is_connected = connected
        db.is_token_revoked.return_value = False
        db.get_user_role.return_value = role_in_db if user_exists else None
        req.app.state.db = db
        return req

    def test_token_claiming_admin_is_refused_once_the_database_says_otherwise(self):
        """The demotion case: a still-valid admin token after the role was removed."""
        from fastapi import HTTPException

        from src.security_fastapi import require_admin_dep

        request = self._request_with("user")
        with pytest.raises(HTTPException) as exc_info:
            require_admin_dep(request, credentials=None)
        assert exc_info.value.status_code == 403

    def test_a_retired_account_loses_admin_immediately(self):
        """get_user_by_id filters deleted_at, so a retired admin resolves to nobody."""
        from fastapi import HTTPException

        from src.security_fastapi import require_admin_dep

        request = self._request_with("admin", user_exists=False)
        with pytest.raises(HTTPException) as exc_info:
            require_admin_dep(request, credentials=None)
        assert exc_info.value.status_code == 403

    def test_a_current_admin_is_still_allowed(self):
        """The guard against over-correction: this must not lock real admins out."""
        from src.security_fastapi import require_admin_dep

        assert require_admin_dep(self._request_with("admin"), credentials=None)

    def test_promotion_takes_effect_without_signing_in_again(self):
        """The mirror case — the token still says 'user', the database says admin."""
        from src.security_fastapi import create_access_token, require_admin_dep

        token = create_access_token("66666666-6666-6666-6666-666666666666", {"role": "user"})
        req = MagicMock()
        req.headers.get = lambda k, default="": (f"Bearer {token}" if k == "Authorization" else default)
        req.cookies = {}
        db = MagicMock()
        db.is_connected = True
        db.is_token_revoked.return_value = False
        db.get_user_role.return_value = "admin"
        req.app.state.db = db

        assert require_admin_dep(req, credentials=None)

    def test_an_unverifiable_role_is_refused_rather_than_assumed(self):
        """Fail closed, as token revocation does: 503 says 'could not check',
        which is a different thing from 'not allowed'."""
        from fastapi import HTTPException

        from src.security_fastapi import require_admin_dep

        request = self._request_with("admin", connected=False)
        with pytest.raises(HTTPException) as exc_info:
            require_admin_dep(request, credentials=None)
        assert exc_info.value.status_code == 503

    def test_a_database_error_while_reading_the_role_is_refused(self):
        """The lookup runs on every admin request; a raise there must not become a
        500, and must not fall through to allowing the call either."""
        from fastapi import HTTPException

        from src.security_fastapi import require_admin_dep

        req = self._request_with("admin")
        req.app.state.db.get_user_role.side_effect = RuntimeError("connection reset")

        with pytest.raises(HTTPException) as exc_info:
            require_admin_dep(req, credentials=None)
        assert exc_info.value.status_code == 403

    def test_a_token_without_a_subject_is_not_an_admin(self):
        """Claims can be present and still name nobody."""
        from src.security_fastapi import _current_global_role

        assert _current_global_role(MagicMock(), {"role": "admin"}) is None

    def test_the_env_var_admin_still_works_without_a_database(self):
        """That account has no row to look up; it is administrative by construction,
        and it is the way back in when the database is empty."""
        from src.security_fastapi import create_access_token, require_admin_dep

        token = create_access_token("admin", {"role": "admin"})
        req = MagicMock()
        req.headers.get = lambda k, default="": (f"Bearer {token}" if k == "Authorization" else default)
        req.cookies = {}
        db = MagicMock()
        db.is_connected = False
        db.is_token_revoked.return_value = False
        req.app.state.db = db

        assert require_admin_dep(req, credentials=None) == "admin"


@pytest.mark.unit
class TestSetupCors:
    def test_cors_disabled_does_nothing(self):
        from fastapi import FastAPI

        from src.security_fastapi import setup_cors

        app = FastAPI()
        with patch("src.security_fastapi.config") as mc:
            mc.CORS_ENABLED = False
            setup_cors(app)
        # No middleware added — just checking no exception is raised

    def test_cors_enabled_adds_middleware(self):
        from fastapi import FastAPI

        from src.security_fastapi import setup_cors

        app = FastAPI()
        with patch("src.security_fastapi.config") as mc:
            mc.CORS_ENABLED = True
            mc.CORS_ORIGINS = ["http://localhost:3000"]
            setup_cors(app)
        # CORSMiddleware registered — no exception is sufficient
