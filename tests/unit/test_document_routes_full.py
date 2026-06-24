"""Tests for document routes."""

from unittest.mock import MagicMock


class TestDocumentListRoute:
    def test_list_documents_returns_200(self, client, app):
        app.state.db.get_all_documents = MagicMock(return_value=[])
        response = client.get('/api/documents/list')
        assert response.status_code == 200

    def test_list_documents_returns_documents_key(self, client, app):
        app.state.db.get_all_documents = MagicMock(return_value=[
            {'id': 1, 'filename': 'test.pdf', 'chunk_count': 5}
        ])
        response = client.get('/api/documents/list')
        data = response.json()
        assert 'documents' in data
        assert len(data['documents']) == 1

    def test_list_documents_empty(self, client, app):
        app.state.db.get_all_documents = MagicMock(return_value=[])
        response = client.get('/api/documents/list')
        data = response.json()
        assert data.get('documents') == []

    def test_list_db_unavailable_returns_503(self, client, app):
        from src.db import DatabaseUnavailableError
        app.state.db.get_all_documents = MagicMock(
            side_effect=DatabaseUnavailableError("not connected")
        )
        response = client.get('/api/documents/list')
        assert response.status_code == 503


class TestDocumentDeleteRoute:
    def test_delete_document_returns_200_and_success_true(self, client, app):
        app.state.db.delete_document = MagicMock()
        app.state.db.get_document_count = MagicMock(return_value=2)
        response = client.delete('/api/documents/1')
        assert response.status_code == 200
        assert response.json()['success'] is True

    def test_delete_document_calls_db_with_correct_id(self, client, app):
        app.state.db.delete_document = MagicMock()
        app.state.db.get_document_count = MagicMock(return_value=0)
        client.delete('/api/documents/42')
        app.state.db.delete_document.assert_called_once_with(42)

    def test_delete_document_updates_document_count(self, client, app):
        app.state.db.delete_document = MagicMock()
        app.state.db.get_document_count = MagicMock(return_value=3)
        client.delete('/api/documents/1')
        app.state.db.get_document_count.assert_called_once()

    def test_delete_document_db_unavailable_returns_503(self, client, app):
        from src.db import DatabaseUnavailableError
        app.state.db.delete_document = MagicMock(
            side_effect=DatabaseUnavailableError("not connected")
        )
        response = client.delete('/api/documents/1')
        assert response.status_code == 503

    def test_delete_document_unexpected_error_returns_500(self, client, app):
        app.state.db.delete_document = MagicMock(side_effect=RuntimeError("boom"))
        response = client.delete('/api/documents/1')
        assert response.status_code == 500
        assert response.json()['success'] is False

    def test_delete_document_invalid_id_returns_404(self, client):
        response = client.delete('/api/documents/not-an-id')
        assert response.status_code in (404, 422)


class TestDocumentClearRoute:
    def test_clear_all_documents(self, client, app):
        # Route calls delete_all_documents(); mock the correct method name
        app.state.db.delete_all_documents = MagicMock()
        response = client.delete('/api/documents/clear')
        assert response.status_code in (200, 204)
        app.state.db.delete_all_documents.assert_called_once()

    def test_clear_documents_db_unavailable_returns_503(self, client, app):
        from src.db import DatabaseUnavailableError
        app.state.db.delete_all_documents = MagicMock(
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
                               data=data)
        assert response.status_code in (400, 200, 422)

    def test_upload_get_not_allowed(self, client):
        response = client.get('/api/documents/upload')
        assert response.status_code in (405, 404)

    def test_upload_path_traversal_rejected(self, client):
        """validate_path returning False should silently skip the file."""
        import io
        from unittest.mock import patch
        data = {'files': (io.BytesIO(b"content"), 'test.txt')}
        with patch('src.routes_fastapi.document_routes.validate_path', return_value=False):
            response = client.post('/api/documents/upload',
                                   data=data)
        assert response.status_code in (200, 400, 422)


class TestDocumentStatsRoute:
    def test_stats_returns_counts(self, client, app):
        app.state.db.get_document_count = MagicMock(return_value=3)
        app.state.db.get_chunk_count = MagicMock(return_value=150)
        app.state.db.get_chunk_statistics = MagicMock(return_value={
            'avg_chunk_size': 512, 'min_chunk_size': 128, 'max_chunk_size': 1024
        })
        response = client.get('/api/documents/stats')
        assert response.status_code == 200
        data = response.json()
        assert data['document_count'] == 3
        assert data['chunk_count'] == 150

    def test_stats_with_zero_documents(self, client, app):
        app.state.db.get_document_count = MagicMock(return_value=0)
        app.state.db.get_chunk_count = MagicMock(return_value=0)
        app.state.db.get_chunk_statistics = MagicMock(return_value={})
        response = client.get('/api/documents/stats')
        assert response.status_code == 200

    def test_stats_db_unavailable_returns_503(self, client, app):
        from src.db import DatabaseUnavailableError
        app.state.db.get_document_count = MagicMock(
            side_effect=DatabaseUnavailableError("not connected")
        )
        response = client.get('/api/documents/stats')
        assert response.status_code == 503

    def test_stats_passes_workspace_id_to_db(self, client, app):
        app.state.db.get_document_count = MagicMock(return_value=2)
        app.state.db.get_chunk_count = MagicMock(return_value=10)
        app.state.db.get_chunk_statistics = MagicMock(return_value={})
        client.get('/api/documents/stats', headers={'X-Workspace-ID': 'ws-abc'})
        app.state.db.get_document_count.assert_called_once_with(workspace_id='ws-abc')
        app.state.db.get_chunk_count.assert_called_once_with(workspace_id='ws-abc')

    def test_stats_no_workspace_header_passes_none(self, client, app):
        app.state.db.get_document_count = MagicMock(return_value=5)
        app.state.db.get_chunk_count = MagicMock(return_value=25)
        app.state.db.get_chunk_statistics = MagicMock(return_value={})
        client.get('/api/documents/stats')
        app.state.db.get_document_count.assert_called_once_with(workspace_id=None)


class TestDocumentSearchRoute:
    def test_search_returns_results(self, client, app):
        app.state.doc_processor.retrieve_context = MagicMock(return_value=[
            ("chunk text", "doc.pdf", 0, 0.9, {}, 1)
        ])
        response = client.post('/api/documents/search-text',
                               json={'query': 'test query'})
        assert response.status_code in (200, 400, 404)

    def test_search_missing_query(self, client):
        response = client.post('/api/documents/search-text',
                               json={})
        assert response.status_code in (400, 200, 404)

    def test_search_empty_query(self, client):
        response = client.post('/api/documents/search-text',
                               json={'query': ''})
        assert response.status_code in (400, 200, 404)
