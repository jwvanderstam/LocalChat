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
class TestVerifyCredentialsDb:
    def test_db_user_found(self):
        from src.security_fastapi import verify_credentials_db

        db = MagicMock()
        db.is_connected = True
        db.verify_user_password.return_value = {"id": "u1", "role": "user"}
        result = verify_credentials_db("alice", "secret", db)
        assert result == ("u1", "user")

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

        with pytest.raises(HTTPException) as exc_info:
            require_auth(self._anonymous_request(), credentials=None)
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

        with pytest.raises(HTTPException) as exc_info:
            require_admin_dep(self._anonymous_request(), credentials=None)
        assert exc_info.value.status_code == 401


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
