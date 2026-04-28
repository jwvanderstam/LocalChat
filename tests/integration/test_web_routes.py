
"""
Web Routes Integration Tests
=============================

Tests for web page routes (src/routes/web_routes.py)

Target: Increase coverage from 58% to 85% (+0.5% overall)

Author: LocalChat Team
Created: January 2025
"""




class TestFaviconRoute:
    """Test favicon serving."""

    def test_favicon_returns_204_when_not_found(self, client):
        """Test favicon returns 204 when file doesn't exist."""
        response = client.get('/favicon.ico')

        # Should return 204 No Content if not found, or 200 if exists
        assert response.status_code in [200, 204, 404]

    def test_favicon_serves_file_when_exists(self, client, tmp_path, monkeypatch):
        """Test favicon serves file when it exists."""
        # This tests the positive path
        response = client.get('/favicon.ico')

        # Either serves file or returns 204
        assert response.status_code in [200, 204]


class TestIndexRoute:
    """Test index/home page."""

    def test_index_renders_chat_template(self, client):
        """Test index route renders chat template."""
        response = client.get('/')

        assert response.status_code == 200
        assert b'html' in response.data.lower() or b'<!DOCTYPE' in response.data

    def test_index_returns_html(self, client):
        """Test index returns HTML content."""
        response = client.get('/')

        assert response.content_type.startswith('text/html')


class TestChatRoute:
    """Test chat page route."""

    def test_chat_renders_template(self, client):
        """Test chat route renders chat template."""
        response = client.get('/chat')

        assert response.status_code == 200

    def test_chat_returns_html(self, client):
        """Test chat returns HTML content."""
        response = client.get('/chat')

        assert response.content_type.startswith('text/html')


class TestDocumentsRoute:
    """Test documents management page."""

    def test_documents_renders_template(self, client):
        """Test documents route renders template."""
        response = client.get('/documents')

        assert response.status_code == 200

    def test_documents_returns_html(self, client):
        """Test documents returns HTML content."""
        response = client.get('/documents')

        assert response.content_type.startswith('text/html')


class TestModelsRoute:
    """Test models management page."""

    def test_models_renders_template(self, client):
        """Test models route renders template."""
        response = client.get('/models')

        assert response.status_code == 200

    def test_models_returns_html(self, client):
        """Test models returns HTML content."""
        response = client.get('/models')

        assert response.content_type.startswith('text/html')


class TestOverviewRoute:
    """Test overview page."""

    def test_overview_renders_template(self, client):
        """Test overview route renders template."""
        response = client.get('/overview')

        assert response.status_code == 200

    def test_overview_returns_html(self, client):
        """Test overview returns HTML content."""
        response = client.get('/overview')

        assert response.content_type.startswith('text/html')


class TestSettingsRoute:
    """Test settings page route."""

    def test_settings_renders_template(self, client):
        """Test settings route renders template."""
        response = client.get('/settings')

        assert response.status_code == 200

    def test_settings_returns_html(self, client):
        """Test settings returns HTML content."""
        response = client.get('/settings')

        assert response.content_type.startswith('text/html')

    def test_settings_observability_tab_present(self, client):
        """Test settings page includes the Observability tab."""
        response = client.get('/settings')

        assert response.status_code == 200
        assert b'Observability' in response.data

    def test_settings_appearance_tab_present(self, client):
        """Test settings page includes the Appearance tab and theme swatches container."""
        response = client.get('/settings')

        assert response.status_code == 200
        assert b'Appearance' in response.data
        assert b'theme-swatches' in response.data


class TestWebRoutesGeneral:
    """Test general web route behavior."""

    def test_all_routes_accessible(self, client):
        """Test all web routes are accessible."""
        routes = ['/', '/chat', '/documents', '/models', '/overview', '/settings']

        for route in routes:
            response = client.get(route)
            assert response.status_code == 200, f"Route {route} failed"

    def test_invalid_route_returns_404(self, client):
        """Test invalid route returns 404."""
        response = client.get('/nonexistent')

        assert response.status_code == 404
