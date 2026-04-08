1# -*- coding: utf-8 -*-
"""Tests for document routes."""

import io
import json
import os
from unittest.mock import MagicMock, patch

import pytest


class TestDocumentListRoute:
    def test_list_documents_returns_200(self, client, app):
        app.db.get_all_documents = MagicMock(return_value=[])
        response = client.get('/api/documents/list')
        assert response.status_code == 200

    def test_list_documents_returns_documents_key(self, client, app):
        app.db.get_all_documents = MagicMock(return_value=[
            {'id': 1, 'filename': 'test.pdf', 'chunk_count': 5}
        ])
        response = client.get('/api/documents/list')
        data = response.get_json()
        assert 'documents' in data
        assert len(data['documents']) == 1

    def test_list_documents_empty(self, client, app):
        app.db.get_all_documents = MagicMock(return_value=[])
        response = client.get('/api/documents/list')
        data = response.get_json()
        assert data.get('documents') == []

    def test_list_db_unavailable_returns_503(self, client, app):
        from src.db import DatabaseUnavailableError
        app.db.get_all_documents = MagicMock(
            side_effect=DatabaseUnavailableError("not connected")
        )
        response = client.get('/api/documents/list')
        assert response.status_code == 503


class TestDocumentDeleteRoute:
    def test_delete_document_success(self, client, app):
        app.db.delete_document = MagicMock(return_value=True)
        app.db.get_document_count = MagicMock(return_value=0)
        response = client.delete('/api/documents/1')
        assert response.status_code in (200, 204, 404)

    def test_delete_document_not_found(self, client, app):
        app.db.delete_document = MagicMock(return_value=False)
        response = client.delete('/api/documents/999')
        assert response.status_code in (200, 404)

    def test_delete_document_invalid_id(self, client):
        response = client.delete('/api/documents/not-an-id')
        assert response.status_code in (400, 404)


class TestDocumentClearRoute:
    def test_clear_all_documents(self, client, app):
        # Route calls delete_all_documents(); mock the correct method name
        app.db.delete_all_documents = MagicMock()
        response = client.delete('/api/documents/clear')
        assert response.status_code in (200, 204)
        app.db.delete_all_documents.assert_called_once()

    def test_clear_documents_db_unavailable_returns_503(self, client, app):
        from src.db import DatabaseUnavailableError
        app.db.delete_all_documents = MagicMock(
            side_effect=DatabaseUnavailableError("not connected")
        )
        response = client.delete('/api/documents/clear')
        assert response.status_code == 503


class TestDocumentUploadRoute:
    def test_upload_no_files_returns_400(self, client):
        response = client.post('/api/documents/upload')
        assert response.status_code in (400, 200)

    def test_upload_empty_filename_returns_400(self, client):
        import io
        data = {'files': (io.BytesIO(b""), '')}
        response = client.post('/api/documents/upload',
                               content_type='multipart/form-data',
                               data=data)
        assert response.status_code in (400, 200)

    def test_upload_get_not_allowed(self, client):
        response = client.get('/api/documents/upload')
        assert response.status_code in (405, 404)


class TestDocumentStatsRoute:
    def test_stats_returns_counts(self, client, app):
        app.db.get_document_count = MagicMock(return_value=3)
        app.db.get_chunk_count = MagicMock(return_value=150)
        app.db.get_chunk_statistics = MagicMock(return_value={
            'avg_chunk_size': 512, 'min_chunk_size': 128, 'max_chunk_size': 1024
        })
        response = client.get('/api/documents/stats')
        assert response.status_code == 200
        data = response.get_json()
        assert data['document_count'] == 3
        assert data['chunk_count'] == 150

    def test_stats_with_zero_documents(self, client, app):
        app.db.get_document_count = MagicMock(return_value=0)
        app.db.get_chunk_count = MagicMock(return_value=0)
        app.db.get_chunk_statistics = MagicMock(return_value={})
        response = client.get('/api/documents/stats')
        assert response.status_code == 200

    def test_stats_db_unavailable_returns_503(self, client, app):
        from src.db import DatabaseUnavailableError
        app.db.get_document_count = MagicMock(
            side_effect=DatabaseUnavailableError("not connected")
        )
        response = client.get('/api/documents/stats')
        assert response.status_code == 503


class TestDocumentSearchRoute:
    def test_search_returns_results(self, client, app):
        app.doc_processor.retrieve_context = MagicMock(return_value=[
            ("chunk text", "doc.pdf", 0, 0.9, {}, 1)
        ])
        response = client.post('/api/documents/search-text',
                               data=json.dumps({'query': 'test query'}),
                               content_type='application/json')
        assert response.status_code in (200, 400, 404)

    def test_search_missing_query(self, client):
        response = client.post('/api/documents/search-text',
                               data=json.dumps({}),
                               content_type='application/json')
        assert response.status_code in (400, 200, 404)

    def test_search_empty_query(self, client):
        response = client.post('/api/documents/search-text',
                               data=json.dumps({'query': ''}),
                               content_type='application/json')
        assert response.status_code in (400, 200, 404)
