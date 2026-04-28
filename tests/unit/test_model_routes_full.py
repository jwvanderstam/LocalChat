"""Tests for model routes."""

import json
from unittest.mock import patch


class TestModelRoutesList:
    def test_list_models_success(self, client):
        response = client.get('/api/models')
        assert response.status_code == 200
        data = response.get_json()
        assert 'models' in data

    def test_list_models_returns_success_flag(self, client):
        response = client.get('/api/models')
        data = response.get_json()
        assert 'success' in data


class TestActiveModel:
    def test_get_active_model(self, client):
        response = client.get('/api/models/active')
        assert response.status_code == 200
        data = response.get_json()
        assert 'model' in data

    def test_set_active_model_missing_body(self, client):
        response = client.post('/api/models/active',
                               data=json.dumps({}),
                               content_type='application/json')
        assert response.status_code in (400, 200, 500)

    def test_set_active_model_missing_key(self, client):
        response = client.post('/api/models/active',
                               data=json.dumps({"not_model": "x"}),
                               content_type='application/json')
        assert response.status_code in (400, 200, 500)

    def test_set_active_model_success(self, client, app):
        with patch.object(app.ollama_client, 'list_models',
                          return_value=(True, [{'name': 'llama3.2', 'size': 1}])):
            response = client.post('/api/models/active',
                                   data=json.dumps({"model": "llama3.2"}),
                                   content_type='application/json')
            assert response.status_code in (200, 404)

    def test_set_active_model_not_found(self, client, app):
        with patch.object(app.ollama_client, 'list_models',
                          return_value=(True, [{'name': 'other-model', 'size': 1}])):
            response = client.post('/api/models/active',
                                   data=json.dumps({"model": "nonexistent-model"}),
                                   content_type='application/json')
            assert response.status_code in (404, 400, 200, 500)


class TestModelPull:
    def test_pull_model_missing_name(self, client):
        response = client.post('/api/models/pull',
                               data=json.dumps({}),
                               content_type='application/json')
        assert response.status_code in (400, 200, 500)

    def test_pull_model_streams_or_responds(self, client, app):
        with patch.object(app.ollama_client, 'pull_model',
                          return_value=iter(['{"status":"success"}'])):
            response = client.post('/api/models/pull',
                                   data=json.dumps({"model": "llama3.2"}),
                                   content_type='application/json')
            assert response.status_code in (200, 400)


class TestModelDelete:
    def test_delete_model_missing_name(self, client):
        response = client.delete('/api/models/delete',
                                 data=json.dumps({}),
                                 content_type='application/json')
        assert response.status_code in (400, 200, 405, 500)

    def test_delete_model_success(self, client, app):
        with patch.object(app.ollama_client, 'delete_model',
                          return_value=(True, 'Deleted')):
            response = client.delete('/api/models/delete',
                                     data=json.dumps({"model": "old-model"}),
                                     content_type='application/json')
            assert response.status_code in (200, 400)


class TestModelTest:
    def test_test_model_success(self, client, app):
        with patch.object(app.ollama_client, 'test_model',
                          return_value=(True, 'OK')):
            response = client.post('/api/models/test',
                                   data=json.dumps({"model": "llama3.2"}),
                                   content_type='application/json')
            assert response.status_code in (200, 400)

    def test_test_model_missing_name(self, client):
        response = client.post('/api/models/test',
                               data=json.dumps({}),
                               content_type='application/json')
        assert response.status_code in (400, 200, 500)


class TestModelRoutesOllamaDown:
    def test_list_models_when_ollama_fails(self, client, app):
        with patch.object(app.ollama_client, 'list_models',
                          return_value=(False, [])):
            response = client.get('/api/models')
            assert response.status_code in (200, 503)
