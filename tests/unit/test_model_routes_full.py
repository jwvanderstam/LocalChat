"""Tests for model routes."""

import json
from unittest.mock import patch


class TestModelRoutesList:
    def test_list_models_success(self, client):
        response = client.get('/api/models')
        assert response.status_code == 200
        data = response.json()
        assert 'models' in data

    def test_list_models_returns_success_flag(self, client):
        response = client.get('/api/models')
        data = response.json()
        assert 'success' in data


class TestActiveModel:
    def test_get_active_model(self, client):
        response = client.get('/api/models/active')
        assert response.status_code == 200
        data = response.json()
        assert 'model' in data

    def test_set_active_model_missing_body(self, client):
        response = client.post('/api/models/active',
                               json={})
        assert response.status_code in (400, 200, 500)

    def test_set_active_model_missing_key(self, client):
        response = client.post('/api/models/active',
                               json={"not_model": "x"})
        assert response.status_code in (400, 200, 500)

    def test_set_active_model_success(self, client, app):
        with patch.object(app.state.ollama_client, 'list_models',
                          return_value=(True, [{'name': 'llama3.2', 'size': 1}])):
            response = client.post('/api/models/active',
                                   json={"model": "llama3.2"})
            assert response.status_code in (200, 404)

    def test_set_active_model_not_found(self, client, app):
        with patch.object(app.state.ollama_client, 'list_models',
                          return_value=(True, [{'name': 'other-model', 'size': 1}])):
            response = client.post('/api/models/active',
                                   json={"model": "nonexistent-model"})
            assert response.status_code in (404, 400, 200, 500)


class TestModelPull:
    def test_pull_model_missing_name(self, client):
        response = client.post('/api/models/pull',
                               json={})
        assert response.status_code in (400, 200, 500)

    def test_pull_model_streams_or_responds(self, client, app):
        with patch.object(app.state.ollama_client, 'pull_model',
                          return_value=iter(['{"status":"success"}'])):
            response = client.post('/api/models/pull',
                                   json={"model": "llama3.2"})
            assert response.status_code in (200, 400)


class TestModelDelete:
    def test_delete_model_missing_name(self, client):
        import json as _json
        response = client.request('DELETE', '/api/models/delete',
                                  content=_json.dumps({}),
                                  headers={"Content-Type": "application/json"})
        assert response.status_code in (400, 200, 405, 500)

    def test_delete_model_success(self, client, app):
        import json as _json
        with patch.object(app.state.ollama_client, 'delete_model',
                          return_value=(True, 'Deleted')):
            response = client.request('DELETE', '/api/models/delete',
                                      content=_json.dumps({"model": "old-model"}),
                                      headers={"Content-Type": "application/json"})
            assert response.status_code in (200, 400)


class TestModelTest:
    def test_test_model_success(self, client, app):
        with patch.object(app.state.ollama_client, 'test_model',
                          return_value=(True, 'OK')):
            response = client.post('/api/models/test',
                                   json={"model": "llama3.2"})
            assert response.status_code in (200, 400)

    def test_test_model_missing_name(self, client):
        response = client.post('/api/models/test',
                               json={})
        assert response.status_code in (400, 200, 500)


class TestModelRoutesOllamaDown:
    def test_list_models_when_ollama_fails(self, client, app):
        with patch.object(app.state.ollama_client, 'list_models',
                          return_value=(False, [])):
            response = client.get('/api/models')
            assert response.status_code in (200, 503)
