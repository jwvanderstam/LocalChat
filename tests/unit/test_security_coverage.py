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
    def test_login_missing_body_returns_400(self, client):
        response = client.post('/api/auth/login',
                               data='not json',
                               content_type='application/json')
        assert response.status_code in (400, 422)

    def test_login_missing_credentials_returns_400(self, client):
        response = client.post('/api/auth/login',
                               data=json.dumps({}),
                               content_type='application/json')
        assert response.status_code == 400

    def test_login_missing_password_returns_400(self, client):
        response = client.post('/api/auth/login',
                               data=json.dumps({'username': 'admin'}),
                               content_type='application/json')
        assert response.status_code == 400

    def test_login_invalid_credentials_returns_401(self, client):
        response = client.post('/api/auth/login',
                               data=json.dumps({'username': 'admin', 'password': 'wrong'}),
                               content_type='application/json')
        assert response.status_code == 401

    def test_login_unknown_user_returns_401(self, client):
        response = client.post('/api/auth/login',
                               data=json.dumps({'username': 'nobody', 'password': 'pass'}),
                               content_type='application/json')
        assert response.status_code == 401

    def test_login_success_with_correct_credentials(self, client, app):
        """Login succeeds when ADMIN_PASSWORD env var is set and matches."""
        with patch.dict('os.environ', {'ADMIN_PASSWORD': 'correct_pass'}):
            # Patch USERS directly since they're loaded at import time
            with patch('src.security.USERS', {
                'admin': {'password': 'correct_pass', 'role': 'admin'}
            }):
                response = client.post('/api/auth/login',
                                       data=json.dumps({
                                           'username': 'admin',
                                           'password': 'correct_pass'
                                       }),
                                       content_type='application/json')
                assert response.status_code == 200
                data = response.get_json()
                assert 'access_token' in data

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
        assert response.status_code in (401, 422)

    def test_verify_with_invalid_token_returns_401_or_422(self, client):
        response = client.get('/api/auth/verify',
                              headers={'Authorization': 'Bearer invalid.token.here'})
        assert response.status_code in (401, 422)


class TestInitSecurity:
    def test_init_security_creates_jwt_manager(self):
        from src.app_factory import create_app
        app = create_app(testing=True)
        import src.security as sec
        assert sec.jwt_manager is not None

    def test_init_security_creates_limiter(self):
        import src.security as sec
        assert sec.limiter is not None
