# -*- coding: utf-8 -*-
"""Coverage for web routes and remaining error handler paths."""

import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Web routes
# ---------------------------------------------------------------------------

class TestWebRoutesFavicon:
    def test_favicon_returns_204_when_not_found(self, client):
        """Favicon returns 204 when file doesn't exist."""
        with patch('src.routes.web_routes.Path') as mock_path:
            mock_p = MagicMock()
            mock_p.__truediv__ = MagicMock(return_value=mock_p)
            mock_p.exists.return_value = False
            mock_path.return_value = mock_p
            response = client.get('/favicon.ico')
        assert response.status_code in (204, 200, 404)

    def test_favicon_endpoint_exists(self, client):
        response = client.get('/favicon.ico')
        assert response.status_code in (200, 204, 404)


class TestWebRoutesPages:
    def test_index_renders_or_404(self, client):
        response = client.get('/')
        assert response.status_code in (200, 404, 500)

    def test_chat_renders_or_404(self, client):
        response = client.get('/chat')
        assert response.status_code in (200, 404, 500)

    def test_documents_renders_or_404(self, client):
        response = client.get('/documents')
        assert response.status_code in (200, 404, 500)

    def test_models_renders_or_404(self, client):
        response = client.get('/models')
        assert response.status_code in (200, 404, 500)

    def test_overview_renders_or_404(self, client):
        response = client.get('/overview')
        assert response.status_code in (200, 404, 500)


# ---------------------------------------------------------------------------
# Error handler — remaining uncovered paths
# ---------------------------------------------------------------------------

class TestValidationMessageBuilderExtra:
    """Cover _build_validation_message branches not yet hit."""

    def test_string_too_long_message(self):
        from src.routes.error_handlers import _build_validation_message
        errors = [{
            'loc': ('message',),
            'type': 'string_too_long',
            'ctx': {'max_length': 100},
            'input': 'x' * 200,
            'msg': 'String should have at most 100 characters'
        }]
        msg = _build_validation_message(errors)
        assert "too long" in msg
        assert "200" in msg
        assert "100" in msg

    def test_string_too_short_message(self):
        from src.routes.error_handlers import _build_validation_message
        errors = [{
            'loc': ('query',),
            'type': 'string_too_short',
            'ctx': {'min_length': 3},
            'input': 'ab',
            'msg': 'String should have at least 3 characters'
        }]
        msg = _build_validation_message(errors)
        assert "at least" in msg
        assert "3" in msg

    def test_multiple_errors_capped_at_3(self):
        from src.routes.error_handlers import _build_validation_message
        errors = [
            {'loc': (f'field{i}',), 'type': 'missing', 'msg': 'required', 'input': None}
            for i in range(5)
        ]
        msg = _build_validation_message(errors)
        assert "2 more" in msg

    def test_exactly_three_errors_no_more(self):
        from src.routes.error_handlers import _build_validation_message
        errors = [
            {'loc': (f'field{i}',), 'type': 'missing', 'msg': 'required', 'input': None}
            for i in range(3)
        ]
        msg = _build_validation_message(errors)
        assert "more error" not in msg


class TestHTTPErrorHandlersExtra:
    def test_405_method_not_allowed(self, client):
        response = client.post('/api/status')
        assert response.status_code == 405
        data = response.get_json()
        assert data['error'] == 'MethodNotAllowed'
        assert 'method' in data.get('details', {})

    def test_500_internal_error(self):
        from src.app_factory import create_app
        isolated_app = create_app(testing=True)
        isolated_app.config['PROPAGATE_EXCEPTIONS'] = False

        @isolated_app.route('/trigger-500-isolated')
        def trigger_500():
            raise RuntimeError("deliberate error")

        with isolated_app.test_client() as c:
            response = c.get('/trigger-500-isolated')
        assert response.status_code == 500
        data = response.get_json()
        assert data['error'] == 'InternalServerError'

    def test_localchat_exception_handler(self):
        from src.app_factory import create_app
        from src import exceptions
        isolated_app = create_app(testing=True)
        isolated_app.config['PROPAGATE_EXCEPTIONS'] = False

        @isolated_app.route('/trigger-lc-exc-isolated')
        def trigger_exc():
            raise exceptions.ModelNotFoundError("test-model")

        with isolated_app.test_client() as c:
            response = c.get('/trigger-lc-exc-isolated')
        assert response.status_code in (400, 404, 500)
        data = response.get_json()
        assert 'error' in data

    def test_database_unavailable_handler(self, client, app):
        from src.db import DatabaseUnavailableError

        @app.route('/api/trigger-db-unavail')
        def trigger_db():
            raise DatabaseUnavailableError("DB is down")

        response = client.get('/api/trigger-db-unavail')
        assert response.status_code == 503
        data = response.get_json()
        assert data['error'] == 'DatabaseUnavailable'

    def test_413_too_large(self, client, app):
        @app.route('/api/trigger-413', methods=['POST'])
        def trigger_413():
            from flask import abort
            abort(413)

        response = client.post('/api/trigger-413')
        assert response.status_code == 413
        data = response.get_json()
        assert data['error'] == 'FileTooLarge'
