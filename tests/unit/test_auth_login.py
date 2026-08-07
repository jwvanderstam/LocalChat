"""AUTH-1 — logging in, and carrying the session by cookie.

Until this landed there was no login route at all: nothing outside
``security_fastapi`` ever called ``create_access_token``, and no frontend request
carried an ``Authorization`` header. RBAC-1 and RBAC-2 then guarded 82 routes, which
made the browser UI unusable — every call returned 401 with no way to authenticate.

Every test here runs with the RBAC bypass OFF, so the checks actually execute.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.security_fastapi import SESSION_COOKIE, create_access_token

USER = "33333333-3333-3333-3333-333333333333"
WS = "11111111-1111-1111-1111-111111111111"


@pytest.fixture(autouse=True)
def _rbac_on():
    # DEMO_MODE is gone (SEC-1); only the admin-password branch remains to neutralise.
    with patch("src.security_fastapi._ADMIN_PASSWORD_RAW", "set-so-rbac-is-live"):
        yield


def _client(*, verify_result=(USER, "user"), member_role: str | None = "editor"):
    from src.routes_fastapi.auth_routes import router

    state = MagicMock()
    state.testing = False
    state.db.is_connected = True
    state.db.is_token_revoked.return_value = False
    state.db.get_workspace_member_role.return_value = member_role
    state.db.get_default_workspace_id.return_value = WS
    state.db.get_user_by_id.return_value = {"id": USER, "username": "jo", "role": "user"}

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state = state

    patcher = patch("src.routes_fastapi.auth_routes.verify_credentials_db",
                    return_value=verify_result)
    patcher.start()
    client = TestClient(app, raise_server_exceptions=False)
    client._verify_patcher = patcher  # stopped by the fixture teardown below
    return client


@pytest.fixture(autouse=True)
def _stop_patchers():
    yield
    patch.stopall()


@pytest.mark.unit
class TestLoginIssuesASession:
    def test_correct_credentials_return_200(self):
        resp = _client().post("/api/auth/login", json={"username": "jo", "password": "pw"})
        assert resp.status_code == 200

    def test_correct_credentials_set_the_session_cookie(self):
        resp = _client().post("/api/auth/login", json={"username": "jo", "password": "pw"})
        assert SESSION_COOKIE in resp.cookies

    def test_cookie_is_httponly(self):
        """JavaScript must not be able to read it — the app renders LLM output to the DOM."""
        resp = _client().post("/api/auth/login", json={"username": "jo", "password": "pw"})
        assert "httponly" in resp.headers["set-cookie"].lower()

    def test_cookie_is_samesite_strict(self):
        resp = _client().post("/api/auth/login", json={"username": "jo", "password": "pw"})
        assert "samesite=strict" in resp.headers["set-cookie"].lower()

    def test_response_reports_the_role(self):
        resp = _client(verify_result=(USER, "admin")).post(
            "/api/auth/login", json={"username": "jo", "password": "pw"})
        assert resp.json()["role"] == "admin"


@pytest.mark.unit
class TestLoginRefusesBadCredentials:
    def test_wrong_password_returns_401(self):
        resp = _client(verify_result=None).post(
            "/api/auth/login", json={"username": "jo", "password": "wrong"})
        assert resp.status_code == 401

    def test_wrong_password_issues_no_cookie(self):
        resp = _client(verify_result=None).post(
            "/api/auth/login", json={"username": "jo", "password": "wrong"})
        assert SESSION_COOKIE not in resp.cookies

    def test_message_does_not_reveal_whether_the_user_exists(self):
        """One message for both cases, or the form becomes a username oracle."""
        resp = _client(verify_result=None).post(
            "/api/auth/login", json={"username": "ghost", "password": "x"})
        assert resp.json()["message"] == "Invalid username or password"

    def test_missing_password_returns_401_not_422(self):
        resp = _client().post("/api/auth/login", json={"username": "jo"})
        assert resp.status_code == 401


@pytest.mark.unit
class TestSessionCookieAuthenticates:
    def test_cookie_alone_reaches_a_guarded_route(self):
        """No Authorization header — exactly what a browser sends."""
        client = _client()
        client.cookies.set(SESSION_COOKIE, create_access_token(USER, {"role": "user"}))
        assert client.get("/api/users/me").status_code == 200

    def test_cookie_alone_reaches_an_admin_route(self):
        """require_admin_dep reads the Depends header; it must fall back to the cookie.

        Without the fallback every admin route 401s for a valid cookie session — found
        by curling the running app rather than by reading the code.
        """
        from src.routes_fastapi.model_routes import router as model_router

        state = MagicMock()
        state.testing = False
        state.db.is_connected = True
        state.db.is_token_revoked.return_value = False
        app = FastAPI()
        app.include_router(model_router, prefix="/api/models")
        app.state = state
        client = TestClient(app, raise_server_exceptions=False)
        client.cookies.set(SESSION_COOKIE, create_access_token(USER, {"role": "admin"}))
        assert client.get("/api/models").status_code != 401

    def test_authorization_header_still_wins(self):
        """Header first, so curl and n8n integrations keep working unchanged."""
        client = _client()
        client.cookies.set(SESSION_COOKIE, "not-a-valid-token")
        token = create_access_token(USER, {"role": "user"})
        resp = client.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_no_credential_at_all_is_refused(self):
        client = _client()
        assert client.get("/api/users/me").json()["can_write"] is False


@pytest.mark.unit
class TestLogoutEndsTheSession:
    def test_logout_clears_the_cookie(self):
        client = _client()
        client.cookies.set(SESSION_COOKIE, create_access_token(USER, {"role": "user"}))
        resp = client.post("/api/logout")
        assert 'localchat_session=""' in resp.headers.get("set-cookie", "") or \
               "Max-Age=0" in resp.headers.get("set-cookie", "")

    def test_logout_without_a_token_still_succeeds(self):
        """Asking to log out must end in logged-out, not in a 400."""
        assert _client().post("/api/logout").status_code == 200
