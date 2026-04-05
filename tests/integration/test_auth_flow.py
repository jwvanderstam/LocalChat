"""Integration tests for the authentication flow (login, token verification, security)."""

import hashlib
import os
from datetime import timedelta
from unittest.mock import patch

import pytest

TEST_PASSWORD = "integration-test-password-abc123"


@pytest.fixture(scope="module")
def auth_app():
    """Minimal Flask app with security middleware using known test credentials."""
    import src.config as cfg
    import src.security as sec_mod
    from flask import Flask

    salt = os.urandom(32)
    pw_hash = hashlib.pbkdf2_hmac("sha256", TEST_PASSWORD.encode(), salt, 100_000)

    flask_app = Flask("auth_test_app")
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False

    old_jwt = sec_mod.jwt_manager
    old_limiter = sec_mod.limiter

    patches = [
        patch.object(sec_mod, "_ADMIN_PASSWORD_RAW", TEST_PASSWORD),
        patch.object(sec_mod, "_ADMIN_PASSWORD_SALT", salt),
        patch.object(sec_mod, "_ADMIN_PASSWORD_HASH", pw_hash),
        patch.object(cfg, "RATELIMIT_ENABLED", False),
        patch.object(cfg, "DEMO_MODE", False),
        patch.object(cfg, "CORS_ENABLED", False),
    ]
    for p in patches:
        p.start()

    try:
        sec_mod.init_security(flask_app)
        sec_mod.setup_auth_routes(flask_app)
        yield flask_app
    finally:
        for p in patches:
            p.stop()
        sec_mod.jwt_manager = old_jwt
        sec_mod.limiter = old_limiter


@pytest.fixture()
def auth_client(auth_app):
    return auth_app.test_client()


@pytest.mark.integration
class TestLogin:
    def test_valid_credentials_return_200_and_token(self, auth_client):
        resp = auth_client.post(
            "/api/auth/login",
            json={"username": "admin", "password": TEST_PASSWORD},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "access_token" in data
        assert data["token_type"] == "Bearer"
        assert isinstance(data["expires_in"], int)

    def test_wrong_password_returns_401(self, auth_client):
        resp = auth_client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrong_password"},
        )
        assert resp.status_code == 401

    def test_unknown_user_returns_401(self, auth_client):
        resp = auth_client.post(
            "/api/auth/login",
            json={"username": "hacker", "password": TEST_PASSWORD},
        )
        assert resp.status_code == 401

    def test_missing_body_returns_400_or_415(self, auth_client):
        # Flask 2.x raises 415 UnsupportedMediaType when content-type is not JSON
        resp = auth_client.post("/api/auth/login", data="not json")
        assert resp.status_code in (400, 415)

    def test_missing_fields_returns_400(self, auth_client):
        resp = auth_client.post("/api/auth/login", json={})
        assert resp.status_code == 400


@pytest.mark.integration
class TestVerifyToken:
    def test_valid_token_returns_200(self, auth_app, auth_client):
        from flask_jwt_extended import create_access_token

        with auth_app.app_context():
            token = create_access_token(identity="admin")

        resp = auth_client.get(
            "/api/auth/verify",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["username"] == "admin"
        assert data["valid"] is True

    def test_no_token_returns_401(self, auth_client):
        resp = auth_client.get("/api/auth/verify")
        assert resp.status_code == 401

    def test_tampered_token_rejected(self, auth_app, auth_client):
        from flask_jwt_extended import create_access_token

        with auth_app.app_context():
            token = create_access_token(identity="admin")

        # Corrupt the signature segment (everything after the last ".")
        header_payload, _ = token.rsplit(".", 1)
        tampered = header_payload + "." + "X" * 43

        resp = auth_client.get(
            "/api/auth/verify",
            headers={"Authorization": f"Bearer {tampered}"},
        )
        assert resp.status_code in (401, 422)

    def test_expired_token_returns_401(self, auth_app, auth_client):
        from flask_jwt_extended import create_access_token

        with auth_app.app_context():
            expired = create_access_token(
                identity="admin", expires_delta=timedelta(seconds=-3600)
            )

        resp = auth_client.get(
            "/api/auth/verify",
            headers={"Authorization": f"Bearer {expired}"},
        )
        assert resp.status_code == 401
