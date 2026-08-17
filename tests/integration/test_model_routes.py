
"""
Model Routes Integration Tests
===============================

Tests for model management routes (src/routes/model_routes.py)

Target: Increase coverage from 24% to 70% (+3% overall)

Covers:
- Model listing
- Active model get/set
- Model pulling
- Model deletion
- Model testing
- Error handling

Author: LocalChat Team
Created: January 2025
"""


import json as _json

import pytest


class TestListModels:
    """Test model listing endpoint."""

    def test_list_models_returns_200(self, client):
        """Test list models returns 200."""
        response = client.get('/api/models/')

        assert response.status_code == 200

    def test_list_models_returns_json(self, client):
        """Test list models returns JSON."""
        response = client.get('/api/models/')

        assert response.headers.get('content-type', '') == 'application/json'
        data = response.json()
        assert 'success' in data
        assert 'models' in data

    def test_list_models_has_correct_structure(self, client):
        """Test list models response structure."""
        response = client.get('/api/models/')
        data = response.json()

        assert isinstance(data.get('success'), bool)
        assert isinstance(data.get('models'), list)

    def test_list_models_when_ollama_available(self, client, mock_ollama):
        """Test list models when Ollama is available."""
        response = client.get('/api/models/')
        data = response.json()

        # Should succeed or report Ollama unavailable
        assert 'success' in data


class TestGetActiveModel:
    """Test getting active model."""

    def test_get_active_model_returns_200(self, client):
        """Test GET active model returns 200."""
        response = client.get('/api/models/active')

        assert response.status_code == 200

    def test_get_active_model_returns_json(self, client):
        """Test GET active model returns JSON."""
        response = client.get('/api/models/active')

        assert response.headers.get('content-type', '') == 'application/json'

    def test_get_active_model_has_model_field(self, client):
        """Test GET active model has model field."""
        response = client.get('/api/models/active')
        data = response.json()

        assert 'model' in data

    def test_get_active_model_returns_none_when_not_set(self, client):
        """Test GET active model returns None when not set."""
        from src import config
        config.app_state.set_active_model(None)

        response = client.get('/api/models/active')
        data = response.json()

        # Should have model field (may be None)
        assert 'model' in data


class TestSetActiveModel:
    """Test setting active model."""

    def test_set_active_model_requires_post(self, client):
        """Test set active model requires POST."""
        # GET is for getting, POST for setting
        response = client.post('/api/models/active', json={
            'model': 'llama3.2'
        })

        # Should process POST (200 or error)
        assert response.status_code in [200, 400, 404, 500, 503]

    def test_set_active_model_requires_model_name(self, client):
        """Test set active model requires model field."""
        response = client.post('/api/models/active', json={})

        assert response.status_code in [400, 500]
        data = response.json()
        if response.status_code == 400:
            assert 'model' in data.get('message', '').lower()

    def test_set_active_model_rejects_empty_name(self, client):
        """Test set active model rejects empty model name."""
        response = client.post('/api/models/active', json={
            'model': ''
        })

        assert response.status_code in [400, 500]

    def test_set_active_model_rejects_nonexistent_model(self, client, mock_ollama):
        """Test set active model rejects non-existent model."""
        response = client.post('/api/models/active', json={
            'model': 'nonexistent-model-xyz'
        })

        # Should reject (404) or handle error
        assert response.status_code in [404, 500, 503]

    def test_set_active_model_with_valid_model(self, client, mock_ollama_with_models):
        """Test set active model with valid model name."""
        response = client.post('/api/models/active', json={
            'model': 'llama3.2'
        })

        # Should succeed or report error
        assert response.status_code in [200, 404, 500, 503]
        if response.status_code == 200:
            data = response.json()
            assert data.get('success') is True

    def test_set_active_model_updates_state(self, client, mock_ollama_with_models):
        """Setting the active model records it, resolved against the model list.

        Asserted unconditionally. `if status == 200:` and `or active is None`
        between them let this pass in three different worlds — resolved,
        unresolved, and never set — which is how it survived a fixture that
        patched nothing.
        """
        from src import config

        response = client.post('/api/models/active', json={'model': 'llama3.2'})

        assert response.status_code == 200
        assert config.app_state.get_active_model() == 'llama3.2'

    def test_a_prefix_resolves_to_the_full_tag_from_the_model_list(
            self, client, mock_ollama_with_models):
        """`_resolve_model_name` exists to turn `llama3.2` into whatever the
        server actually calls it. Nothing asserted that, so the resolution could
        have been dropped and the suite stayed green."""
        from src import config

        mock_ollama_with_models.list_models.return_value = (True, [
            {'name': 'llama3.2:latest', 'size': 4500000000},
        ])

        response = client.post('/api/models/active', json={'model': 'llama3.2'})

        assert response.status_code == 200
        assert config.app_state.get_active_model() == 'llama3.2:latest'

    def test_a_model_the_server_does_not_have_is_refused(
            self, client, mock_ollama_with_models):
        """The negative side of resolution: an unknown name must not be stored."""
        from src import config

        config.app_state.set_active_model('llama3.2')

        response = client.post('/api/models/active', json={'model': 'not-installed'})

        assert response.status_code == 404
        assert config.app_state.get_active_model() == 'llama3.2'


class TestPullModel:
    """Test model pulling endpoint."""

    def test_pull_model_requires_post(self, client):
        """Test pull model requires POST."""
        response = client.get('/api/models/pull')

        assert response.status_code == 405

    def test_pull_model_requires_model_name(self, client):
        """Test pull model requires model field."""
        response = client.post('/api/models/pull', json={})

        assert response.status_code in [400, 500]

    def test_pull_model_rejects_empty_name(self, client):
        """Test pull model rejects empty model name."""
        response = client.post('/api/models/pull', json={
            'model': ''
        })

        assert response.status_code in [400, 500]

    def test_pull_model_reports_invalid_characters_specifically(self, client):
        """A human-readable name like 'Qwen 2.5 14B' (spaces) must surface the
        actual validation reason, not a generic 'model is required' message
        that doesn't tell the caller a name was provided but malformed."""
        response = client.post('/api/models/pull', json={
            'model': 'Qwen 2.5 14B'
        })

        assert response.status_code == 400
        assert response.json()['message'] == 'Model name contains invalid characters'

    def test_pull_model_missing_field_reports_model_required(self, client):
        """A request with no model field at all keeps the endpoint-specific
        default rather than Pydantic's generic 'Field required'."""
        response = client.post('/api/models/pull', json={})

        assert response.status_code == 400
        assert 'model' in response.json()['message'].lower()

    def test_pull_model_returns_sse_stream(self, client, mock_ollama):
        """Test pull model returns Server-Sent Events stream."""
        response = client.post('/api/models/pull', json={
            'model': 'llama3.2'
        })

        # Should start streaming or return error
        if response.status_code == 200:
            assert 'text/event-stream' in response.headers.get('content-type', '')

    def test_pull_model_handles_pull_error(self, client):
        """Test pull model handles errors gracefully."""
        response = client.post('/api/models/pull', json={
            'model': 'invalid-model-12345'
        })

        # Should handle error (500 or stream with error)
        assert response.status_code in [200, 500]


class TestDeleteModel:
    """Test model deletion endpoint."""

    def test_delete_model_requires_delete_method(self, client):
        """Test delete model requires DELETE method."""
        response = client.get('/api/models/delete')

        assert response.status_code == 405

    def test_delete_model_requires_model_name(self, client):
        """Test delete model requires model field."""
        response = client.request('DELETE', '/api/models/delete', content=_json.dumps({}),
                                  headers={"Content-Type": "application/json"})

        assert response.status_code in [400, 500]

    def test_delete_model_rejects_empty_name(self, client):
        """Test delete model rejects empty model name."""
        response = client.request('DELETE', '/api/models/delete',
                                  content=_json.dumps({'model': ''}),
                                  headers={"Content-Type": "application/json"})

        assert response.status_code in [400, 500]

    def test_delete_model_returns_json(self, client):
        """Test delete model returns JSON response."""
        response = client.request('DELETE', '/api/models/delete',
                                  content=_json.dumps({'model': 'test-model'}),
                                  headers={"Content-Type": "application/json"})

        assert response.headers.get('content-type', '') == 'application/json'

    def test_delete_model_handles_nonexistent(self, client, mock_ollama):
        """Test delete model handles non-existent model."""
        response = client.request('DELETE', '/api/models/delete',
                                  content=_json.dumps({'model': 'nonexistent-model'}),
                                  headers={"Content-Type": "application/json"})

        assert response.status_code in [400, 404]
        data = response.json()
        assert data is not None


class TestTestModel:
    """Test model testing endpoint."""

    def test_test_model_requires_post(self, client):
        """Test test model requires POST."""
        response = client.get('/api/models/test')

        assert response.status_code == 405

    def test_test_model_requires_model_name(self, client):
        """Test test model requires model field."""
        response = client.post('/api/models/test', json={})

        assert response.status_code in [400, 500]

    def test_test_model_rejects_empty_name(self, client):
        """Test test model rejects empty model name."""
        response = client.post('/api/models/test', json={
            'model': ''
        })

        assert response.status_code in [400, 500]

    def test_test_model_returns_json(self, client):
        """Test test model returns JSON."""
        response = client.post('/api/models/test', json={
            'model': 'llama3.2'
        })

        assert response.headers.get('content-type', '') == 'application/json'

    def test_test_model_has_success_field(self, client):
        """Test test model response has success field."""
        response = client.post('/api/models/test', json={
            'model': 'llama3.2'
        })

        data = response.json()
        assert 'success' in data

    def test_test_model_has_result_field(self, client):
        """Test test model response has result field."""
        response = client.post('/api/models/test', json={
            'model': 'llama3.2'
        })

        data = response.json()
        assert 'result' in data or 'message' in data


class TestModelRoutesErrorHandling:
    """Test error handling in model routes."""

    def test_list_models_handles_ollama_unavailable(self, client):
        """Test list models when Ollama is unavailable."""
        response = client.get('/api/models/')

        # Should return response (success false or error)
        assert response.status_code in [200, 503]
        data = response.json()
        assert 'success' in data

    def test_set_active_handles_list_failure(self, client):
        """Test set active model handles list models failure."""
        response = client.post('/api/models/active', json={
            'model': 'test-model'
        })

        # Should handle gracefully
        assert response.status_code in [200, 404, 500, 503]

    def test_all_endpoints_return_json_on_error(self, client):
        """Test all endpoints return JSON on error."""
        endpoints = [
            ('POST', '/api/models/active', {}),
            ('POST', '/api/models/pull', {}),
            ('DELETE', '/api/models/delete', {}),
            ('POST', '/api/models/test', {}),
        ]

        for method, url, data in endpoints:
            if method == 'POST':
                response = client.post(url, json=data)
            elif method == 'DELETE':
                response = client.request('DELETE', url, content=_json.dumps(data),
                                          headers={"Content-Type": "application/json"})

            # Should return JSON error
            assert response.headers.get('content-type', '') == 'application/json'
            resp_data = response.json()
            assert 'message' in resp_data or 'success' in resp_data


class TestModelRoutesSecurity:
    """Test security aspects of model routes."""

    def test_model_name_sanitization(self, client):
        """Test model names are sanitized."""
        # Try injection attempt
        response = client.post('/api/models/active', json={
            'model': '../../../etc/passwd'
        })

        # Should reject or handle safely
        assert response.status_code in [400, 404, 500, 503]

    def test_special_characters_in_model_name(self, client):
        """Test special characters in model names."""
        response = client.post('/api/models/active', json={
            'model': 'model<script>alert(1)</script>'
        })

        # Should handle safely
        assert response.status_code in [400, 404, 500, 503]


# Fixtures
@pytest.fixture
def mock_ollama(monkeypatch):
    """Mock Ollama client."""
    from unittest.mock import MagicMock

    mock_client = MagicMock()
    mock_client.list_models.return_value = (False, [])
    mock_client.test_model.return_value = (True, "Test response")
    mock_client.pull_model.return_value = iter([{'status': 'downloading'}])
    mock_client.delete_model.return_value = (True, "Deleted")

    return mock_client


@pytest.fixture
def mock_ollama_with_models(app, monkeypatch):
    """Mock Ollama client with models, installed on the app the routes read.

    It used to build the mock and return it without patching anything —
    `monkeypatch` was taken as an argument and never used — so
    `/api/models/active` called the *real* `app.state.ollama_client` and listed
    whatever Ollama the machine could reach.

    That passed only because nothing answered on `localhost:11434`: with no model
    list, the route stored the requested name verbatim. Once the compose stack
    published Ollama on the host, the real list came back, `llama3.2` resolved to
    `llama3.2:latest`, and the test failed — on a *working* development machine,
    while staying green in CI, which is exactly backwards.
    """
    from unittest.mock import MagicMock

    mock_client = MagicMock()
    mock_client.list_models.return_value = (True, [
        {'name': 'llama3.2', 'size': 4500000000},
        {'name': 'nomic-embed-text', 'size': 274000000}
    ])
    mock_client.test_model.return_value = (True, "Test response")
    monkeypatch.setattr(app.state, "ollama_client", mock_client)

    return mock_client
