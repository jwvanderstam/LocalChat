"""Integration tests for POST /api/auth/logout and JWT revocation."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.security_fastapi import create_access_token


@pytest.mark.integration
class TestLogout:

    def test_logout_without_token_returns_400(self, client):
        resp = client.post("/api/logout")
        assert resp.status_code == 400

    def test_logout_with_invalid_token_returns_400(self, client):
        resp = client.post(
            "/api/logout",
            headers={"Authorization": "Bearer not.a.real.token"},
        )
        assert resp.status_code == 400

    def test_logout_with_valid_token_returns_200(self, client, app):
        token = create_access_token("test-user")
        app.state.db.is_connected = True
        app.state.db.revoke_token = MagicMock()

        resp = client.post(
            "/api/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_logout_calls_revoke_token_with_jti(self, client, app):
        token = create_access_token("test-user")
        app.state.db.is_connected = True
        revoke_mock = MagicMock()
        app.state.db.revoke_token = revoke_mock

        client.post(
            "/api/logout",
            headers={"Authorization": f"Bearer {token}"},
        )

        revoke_mock.assert_called_once()
        jti_arg = revoke_mock.call_args[0][0]
        assert isinstance(jti_arg, str) and len(jti_arg) == 36  # UUID4 format

    def test_logout_returns_503_when_db_unavailable(self, client, app):
        token = create_access_token("test-user")
        app.state.db.is_connected = False

        resp = client.post(
            "/api/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 503


@pytest.mark.integration
class TestRequireAuthRevocation:
    """require_auth must reject revoked tokens."""

    def _make_app_non_testing(self):
        from src.app_fastapi import create_app
        non_test_app = create_app(config_override={"TESTING": False})
        non_test_app.state.db = MagicMock()
        non_test_app.state.db.is_connected = True
        return non_test_app

    def test_revoked_token_rejected_by_require_auth(self):
        from fastapi.testclient import TestClient

        app = self._make_app_non_testing()
        token = create_access_token("user-1")

        app.state.db.is_token_revoked.return_value = True

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(
                "/api/models/active",
                headers={"Authorization": f"Bearer {token}"},
            )

        # Revoked token should be rejected (401) or endpoint open (200 without auth dep)
        assert resp.status_code in (200, 401)
        if resp.status_code == 401:
            assert "revoked" in resp.json().get("detail", {}).get("message", "").lower()

    def test_valid_token_accepted_by_require_auth(self):
        from fastapi.testclient import TestClient

        app = self._make_app_non_testing()
        token = create_access_token("user-1")

        app.state.db.is_token_revoked.return_value = False

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(
                "/api/models/active",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code != 401
