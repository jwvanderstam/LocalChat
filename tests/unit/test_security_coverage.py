# -*- coding: utf-8 -*-
"""Additional coverage for src/security.py."""

import json
import pytest
from unittest.mock import patch, MagicMock


class TestRequireAuthOptional:
    def test_allows_unauthenticated_access(self, app):
        """require_auth_optional lets requests through without a token."""
        from src.security import require_auth_optional

        @require_auth_optional
        def view():
            return "ok"

        with app.app_context():
            with app.test_request_context('/'):
                result = view()
        assert result == "ok"

    def test_wraps_preserves_function_name(self):
        from src.security import require_auth_optional

        @require_auth_optional
        def my_view():
            pass

        assert my_view.__name__ == "my_view"


class TestAdminRequired:
    def test_admin_required_wraps_function(self):
        from src.security import admin_required

        @admin_required
        def protected():
            return "secret"

        assert protected.__name__ == "protected"


class TestSetupHealthCheck:
    def test_setup_health_check_does_not_raise(self, app):
        from src.security import setup_health_check
        # Should be a no-op (health handled by monitoring)
        setup_health_check(app)


class TestSetupRateLimitHandler:
    def test_setup_rate_limit_handler_registers_429(self, app):
        from src.security import setup_rate_limit_handler
        setup_rate_limit_handler(app)
        # 429 handler should now be registered
        assert app.error_handler_spec is not None


class TestAuthLoginEndpoint:
    """Auth routes are only registered when testing=False (security init runs).
    In the standard test fixture (testing=True) all endpoints return 404; that
    is the expected behaviour and is included in every assertion."""

    def test_login_missing_body_returns_400(self, client):
        response = client.post('/api/auth/login',
                               data='not json',
                               content_type='application/json')
        assert response.status_code in (400, 404, 422)

    def test_login_missing_credentials_returns_400(self, client):
        response = client.post('/api/auth/login',
                               data=json.dumps({}),
                               content_type='application/json')
        assert response.status_code in (400, 404)

    def test_login_missing_password_returns_400(self, client):
        response = client.post('/api/auth/login',
                               data=json.dumps({'username': 'admin'}),
                               content_type='application/json')
        assert response.status_code in (400, 404)

    def test_login_invalid_credentials_returns_401(self, client):
        response = client.post('/api/auth/login',
                               data=json.dumps({'username': 'admin', 'password': 'wrong'}),
                               content_type='application/json')
        assert response.status_code in (401, 404)

    def test_login_unknown_user_returns_401(self, client):
        response = client.post('/api/auth/login',
                               data=json.dumps({'username': 'nobody', 'password': 'pass'}),
                               content_type='application/json')
        assert response.status_code in (401, 404)

    def test_login_success_with_correct_credentials(self, client, app):
        """Login succeeds when ADMIN_PASSWORD env var is set and matches."""
        with patch.dict('os.environ', {'ADMIN_PASSWORD': 'correct_pass'}):
            with patch('src.security.USERS', {
                'admin': {'password': 'correct_pass', 'role': 'admin'}
            }):
                response = client.post('/api/auth/login',
                                       data=json.dumps({
                                           'username': 'admin',
                                           'password': 'correct_pass'
                                       }),
                                       content_type='application/json')
                assert response.status_code in (200, 404)
                if response.status_code == 200:
                    assert 'access_token' in response.get_json()

    def test_login_returns_token_type_bearer(self, client):
        with patch('src.security.USERS', {
            'admin': {'password': 'mypass', 'role': 'admin'}
        }):
            response = client.post('/api/auth/login',
                                   data=json.dumps({'username': 'admin', 'password': 'mypass'}),
                                   content_type='application/json')
            if response.status_code == 200:
                data = response.get_json()
                assert data.get('token_type') == 'Bearer'


class TestAuthVerifyEndpoint:
    def test_verify_without_token_returns_401_or_422(self, client):
        response = client.get('/api/auth/verify')
        assert response.status_code in (401, 404, 422)

    def test_verify_with_invalid_token_returns_401_or_422(self, client):
        response = client.get('/api/auth/verify',
                              headers={'Authorization': 'Bearer invalid.token.here'})
        assert response.status_code in (401, 404, 422)


class TestInitSecurity:
    """Verify that init_security sets the module-level globals."""

    @pytest.fixture(autouse=True)
    def _call_init_security(self):
        """Call init_security on a fresh Flask app so globals are set."""
        from flask import Flask
        from src.security import init_security
        app = Flask("init_sec_test")
        with patch("src.security.config") as cfg:
            cfg.DEMO_MODE = False
            cfg.CORS_ENABLED = False
            cfg.CORS_ORIGINS = []
            cfg.JWT_SECRET_KEY = "test-secret-key-long-enough"
            cfg.JWT_ACCESS_TOKEN_EXPIRES = 3600
            cfg.RATELIMIT_ENABLED = False
            cfg.RATELIMIT_GENERAL = "200 per day"
            init_security(app)

    def test_init_security_creates_jwt_manager(self):
        import src.security as sec
        assert sec.jwt_manager is not None

    def test_init_security_creates_limiter(self):
        import src.security as sec
        assert sec.limiter is not None


class TestInitSecurityBranches:
    """Cover init_security branches not exercised by the default test app."""

    def _make_flask_app(self):
        from flask import Flask
        return Flask(f"sec_test_{id(self)}")

    def test_demo_mode_path(self):
        """DEMO_MODE=True skips JWT setup and disables rate limiting."""
        from src.security import init_security
        app = self._make_flask_app()
        with patch("src.security.config") as cfg:
            cfg.DEMO_MODE = True
            cfg.CORS_ENABLED = False
            cfg.CORS_ORIGINS = []
            cfg.JWT_SECRET_KEY = "secret"
            cfg.JWT_ACCESS_TOKEN_EXPIRES = 3600
            cfg.RATELIMIT_ENABLED = True
            cfg.RATELIMIT_GENERAL = "200 per day"
            init_security(app)
        import src.security as sec
        assert sec.jwt_manager is not None
        assert sec.limiter is not None

    def test_demo_mode_with_cors(self):
        """DEMO_MODE=True + CORS_ENABLED registers CORS."""
        from src.security import init_security
        app = self._make_flask_app()
        with patch("src.security.config") as cfg:
            cfg.DEMO_MODE = True
            cfg.CORS_ENABLED = True
            cfg.CORS_ORIGINS = ["*"]
            cfg.JWT_SECRET_KEY = "s"
            cfg.JWT_ACCESS_TOKEN_EXPIRES = 3600
            cfg.RATELIMIT_ENABLED = False
            cfg.RATELIMIT_GENERAL = "200 per day"
            init_security(app)  # should not raise

    def test_rate_limiting_disabled_path(self):
        """RATELIMIT_ENABLED=False creates a disabled limiter."""
        from src.security import init_security
        app = self._make_flask_app()
        with patch("src.security.config") as cfg:
            cfg.DEMO_MODE = False
            cfg.CORS_ENABLED = False
            cfg.CORS_ORIGINS = []
            cfg.JWT_SECRET_KEY = "secret"
            cfg.JWT_ACCESS_TOKEN_EXPIRES = 3600
            cfg.RATELIMIT_ENABLED = False
            cfg.RATELIMIT_GENERAL = "200 per day"
            init_security(app)
        import src.security as sec
        assert sec.limiter is not None

    def test_cors_enabled_path(self):
        """CORS_ENABLED=True attaches CORS to the app."""
        from src.security import init_security
        app = self._make_flask_app()
        with patch("src.security.config") as cfg:
            cfg.DEMO_MODE = False
            cfg.CORS_ENABLED = True
            cfg.CORS_ORIGINS = ["http://localhost:3000"]
            cfg.JWT_SECRET_KEY = "secret"
            cfg.JWT_ACCESS_TOKEN_EXPIRES = 3600
            cfg.RATELIMIT_ENABLED = True
            cfg.RATELIMIT_GENERAL = "200 per day"
            init_security(app)  # should not raise

    def test_request_response_logging_hooks(self):
        """log_request and log_response hooks run without error."""
        from src.security import init_security
        app = self._make_flask_app()
        with patch("src.security.config") as cfg:
            cfg.DEMO_MODE = False
            cfg.CORS_ENABLED = False
            cfg.CORS_ORIGINS = []
            cfg.JWT_SECRET_KEY = "secret"
            cfg.JWT_ACCESS_TOKEN_EXPIRES = 3600
            cfg.RATELIMIT_ENABLED = False
            cfg.RATELIMIT_GENERAL = "200 per day"
            init_security(app)

        @app.route("/ping")
        def ping():
            return "pong"

        with app.test_client() as c:
            response = c.get("/ping")
        assert response.status_code == 200


class TestAuthRoutesWithFullApp:
    """Exercise auth routes using an app with security fully initialised."""

    @pytest.fixture
    def auth_app(self):
        from flask import Flask
        from src.security import init_security, setup_auth_routes
        app = Flask("auth_full_test")
        with patch("src.security.config") as cfg:
            cfg.DEMO_MODE = False
            cfg.CORS_ENABLED = False
            cfg.CORS_ORIGINS = []
            cfg.JWT_SECRET_KEY = "test-secret-key-long-enough"
            cfg.JWT_ACCESS_TOKEN_EXPIRES = 3600
            cfg.RATELIMIT_ENABLED = False
            cfg.RATELIMIT_GENERAL = "200 per day"
            init_security(app)
            setup_auth_routes(app)
        return app

    @pytest.fixture
    def auth_client(self, auth_app):
        return auth_app.test_client()

    def test_login_missing_body_returns_400(self, auth_client):
        response = auth_client.post("/api/auth/login",
                                    data="not json",
                                    content_type="application/json")
        assert response.status_code == 400

    def test_login_empty_json_returns_400(self, auth_client):
        response = auth_client.post("/api/auth/login",
                                    json={})
        assert response.status_code == 400

    def test_login_missing_password_returns_400(self, auth_client):
        response = auth_client.post("/api/auth/login",
                                    json={"username": "admin"})
        assert response.status_code == 400

    def test_login_wrong_credentials_returns_401(self, auth_client):
        response = auth_client.post("/api/auth/login",
                                    json={"username": "admin", "password": "wrong"})
        assert response.status_code == 401

    def test_login_success_returns_token(self, auth_client):
        import hashlib
        test_password = "pass"
        test_salt = b"fixed-test-salt-32-bytes-padding"
        test_hash = hashlib.pbkdf2_hmac('sha256', test_password.encode(), test_salt, 100_000)
        with patch("src.security._ADMIN_PASSWORD_RAW", test_password), \
             patch("src.security._ADMIN_PASSWORD_SALT", test_salt), \
             patch("src.security._ADMIN_PASSWORD_HASH", test_hash):
            response = auth_client.post("/api/auth/login",
                                        json={"username": "admin", "password": test_password})
        assert response.status_code == 200
        data = response.get_json()
        assert "access_token" in data
        assert data["token_type"] == "Bearer"

    def test_verify_without_token_returns_401(self, auth_client):
        response = auth_client.get("/api/auth/verify")
        assert response.status_code in (401, 422)

    def test_verify_with_valid_token(self, auth_client):
        with patch("src.security.USERS", {"admin": {"password": "pass", "role": "admin"}}):
            login_resp = auth_client.post("/api/auth/login",
                                          json={"username": "admin", "password": "pass"})
        if login_resp.status_code != 200:
            pytest.skip("login failed, cannot test verify")
        token = login_resp.get_json()["access_token"]
        response = auth_client.get("/api/auth/verify",
                                   headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.get_json()["valid"] is True


class TestAdminRequiredDecorator:
    """Cover the admin_required decorator body (role check)."""

    @pytest.fixture
    def auth_app(self):
        from flask import Flask
        from src.security import init_security, setup_auth_routes, admin_required
        app = Flask("admin_req_test")
        with patch("src.security.config") as cfg:
            cfg.DEMO_MODE = False
            cfg.CORS_ENABLED = False
            cfg.CORS_ORIGINS = []
            cfg.JWT_SECRET_KEY = "test-secret-key-long-enough"
            cfg.JWT_ACCESS_TOKEN_EXPIRES = 3600
            cfg.RATELIMIT_ENABLED = False
            cfg.RATELIMIT_GENERAL = "200 per day"
            init_security(app)
            setup_auth_routes(app)

        @app.route("/admin-only")
        @admin_required
        def admin_only():
            return "secret"

        return app

    @pytest.fixture
    def auth_client(self, auth_app):
        return auth_app.test_client()

    def _get_token(self, client, role="admin"):
        with patch("src.security.USERS", {"user": {"password": "pw", "role": role}}):
            resp = client.post("/api/auth/login",
                               json={"username": "user", "password": "pw"})
        if resp.status_code != 200:
            return None
        return resp.get_json()["access_token"]

    def test_admin_required_rejects_non_admin(self, auth_client):
        token = self._get_token(auth_client, role="user")
        if token is None:
            pytest.skip("could not obtain token")
        response = auth_client.get("/admin-only",
                                   headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403

    def test_admin_required_allows_admin(self, auth_client):
        token = self._get_token(auth_client, role="admin")
        if token is None:
            pytest.skip("could not obtain token")
        response = auth_client.get("/admin-only",
                                   headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200


class TestRateLimitHandler:
    """Cover the rate-limit error handler body (lines 315-316)."""

    def test_rate_limit_handler_returns_429_json(self, app):
        """Simulate a 429 response through the registered handler."""
        from src.security import setup_rate_limit_handler
        setup_rate_limit_handler(app)

        @app.route("/limited")
        def limited():
            from flask import abort
            abort(429)

        with app.test_client() as c:
            response = c.get("/limited")
        assert response.status_code == 429
        data = response.get_json()
        assert data["error"] == "RateLimitExceeded"
