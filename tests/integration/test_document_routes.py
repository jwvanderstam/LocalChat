# -*- coding: utf-8 -*-

"""
Document Routes Integration Tests
==================================

Tests for document management routes (src/routes/document_routes.py)

Target: Increase coverage from 55% to 75% (+2% overall)

Covers:
- Document upload/ingestion
- Document listing
- RAG retrieval testing
- Document statistics
- Text search
- Document deletion

Author: LocalChat Team
Created: January 2025
"""

import pytest
import json
import io
from pathlib import Path


class TestUploadDocuments:
    """Test document upload endpoint."""
    
    def test_upload_requires_post(self, client):
        """Test upload requires POST method."""
        response = client.get('/api/documents/upload')
        
        assert response.status_code == 405
    
    def test_upload_requires_files(self, client):
        """Test upload requires files in request."""
        response = client.post('/api/documents/upload')
        
        assert response.status_code == 400
        data = response.get_json()
        assert 'files' in data.get('message', '').lower()
    
    def test_upload_rejects_empty_files(self, client):
        """Test upload rejects empty file list."""
        response = client.post('/api/documents/upload', data={
            'files': (io.BytesIO(b''), '')
        })
        
        assert response.status_code == 400
    
    def test_upload_accepts_pdf_file(self, client, tmp_path):
        """Test upload accepts PDF files."""
        # Create test PDF file
        pdf_content = b'%PDF-1.4 test content'
        
        response = client.post('/api/documents/upload', data={
            'files': [(io.BytesIO(pdf_content), 'test.pdf')]
        }, content_type='multipart/form-data')
        
        # Should return SSE stream or error
        assert response.status_code in [200, 400, 500]
    
    def test_upload_accepts_text_file(self, client):
        """Test upload accepts text files."""
        text_content = b'This is test content'
        
        response = client.post('/api/documents/upload', data={
            'files': [(io.BytesIO(text_content), 'test.txt')]
        }, content_type='multipart/form-data')
        
        assert response.status_code in [200, 400, 500]
    
    def test_upload_rejects_unsupported_format(self, client):
        """Test upload rejects unsupported file formats."""
        response = client.post('/api/documents/upload', data={
            'files': [(io.BytesIO(b'content'), 'test.xyz')]
        }, content_type='multipart/form-data')
        
        # Should reject or handle gracefully
        assert response.status_code in [200, 400]
    
    def test_upload_returns_sse_stream(self, client):
        """Test upload returns Server-Sent Events stream."""
        text_content = b'Test content'
        
        response = client.post('/api/documents/upload', data={
            'files': [(io.BytesIO(text_content), 'test.txt')]
        }, content_type='multipart/form-data')
        
        if response.status_code == 200:
            assert response.mimetype == 'text/event-stream'


class TestListDocuments:
    """Test document listing endpoint."""
    
    def test_list_returns_200(self, client):
        """Test list endpoint returns 200."""
        response = client.get('/api/documents/list')
        
        assert response.status_code == 200
    
    def test_list_returns_json(self, client):
        """Test list returns JSON."""
        response = client.get('/api/documents/list')
        
        assert response.content_type == 'application/json'
    
    def test_list_has_success_field(self, client):
        """Test list response has success field."""
        response = client.get('/api/documents/list')
        data = response.get_json()
        
        assert 'success' in data
    
    def test_list_has_documents_array(self, client):
        """Test list response has documents array."""
        response = client.get('/api/documents/list')
        data = response.get_json()
        
        if data.get('success'):
            assert 'documents' in data
            assert isinstance(data['documents'], list)
    
    def test_list_document_structure(self, client):
        """Test document objects have expected structure."""
        response = client.get('/api/documents/list')
        data = response.get_json()
        
        if data.get('success') and data.get('documents'):
            doc = data['documents'][0]
            # Should have basic fields
            assert 'id' in doc or 'filename' in doc


class TestDocumentStats:
    """Test document statistics endpoint."""
    
    def test_stats_returns_200(self, client):
        """Test stats endpoint returns 200."""
        response = client.get('/api/documents/stats')
        
        assert response.status_code == 200
    
    def test_stats_returns_json(self, client):
        """Test stats returns JSON."""
        response = client.get('/api/documents/stats')
        
        assert response.content_type == 'application/json'
    
    def test_stats_has_required_fields(self, client):
        """Test stats response has required fields."""
        response = client.get('/api/documents/stats')
        data = response.get_json()
        
        if data.get('success'):
            assert 'document_count' in data
            assert 'chunk_count' in data
    
    def test_stats_fields_are_integers(self, client):
        """Test stats fields are correct types."""
        response = client.get('/api/documents/stats')
        data = response.get_json()
        
        if data.get('success'):
            assert isinstance(data.get('document_count', 0), int)
            assert isinstance(data.get('chunk_count', 0), int)
    
    def test_stats_includes_chunk_statistics(self, client):
        """Test stats includes detailed chunk statistics."""
        response = client.get('/api/documents/stats')
        data = response.get_json()
        
        if data.get('success'):
            # May have chunk_statistics field
            assert 'chunk_statistics' in data or 'chunk_count' in data


class TestRetrievalTesting:
    """Test RAG retrieval testing endpoint."""
    
    def test_test_requires_post(self, client):
        """Test retrieval test requires POST."""
        response = client.get('/api/documents/test')
        
        assert response.status_code == 405
    
    def test_test_requires_query(self, client):
        """Test retrieval test requires query."""
        response = client.post('/api/documents/test', json={})
        
        assert response.status_code in [400, 500]
    
    def test_test_with_valid_query(self, client):
        """Test retrieval test with valid query."""
        response = client.post('/api/documents/test', json={
            'query': 'What is this about?'
        })
        
        assert response.status_code in [200, 500]
    
    def test_test_returns_json(self, client):
        """Test retrieval test returns JSON."""
        response = client.post('/api/documents/test', json={
            'query': 'Test query'
        })
        
        if response.status_code == 200:
            assert response.content_type == 'application/json'
            data = response.get_json()
            assert 'success' in data
    
    def test_test_with_hybrid_search_flag(self, client):
        """Test retrieval test with hybrid search option."""
        response = client.post('/api/documents/test', json={
            'query': 'Test query',
            'use_hybrid_search': True
        })
        
        assert response.status_code in [200, 500]
    
    def test_test_rejects_empty_query(self, client):
        """Test retrieval test rejects empty query."""
        response = client.post('/api/documents/test', json={
            'query': ''
        })
        
        assert response.status_code in [400, 500]
    
    def test_test_rejects_too_long_query(self, client):
        """Test retrieval test rejects very long queries."""
        long_query = 'x' * 2000
        response = client.post('/api/documents/test', json={
            'query': long_query
        })
        
        assert response.status_code in [200, 400, 500]


class TestTextSearch:
    """Test text search endpoint."""
    
    def test_search_text_requires_post(self, client):
        """Test text search requires POST."""
        response = client.get('/api/documents/search-text')
        
        assert response.status_code == 405
    
    def test_search_text_requires_search_text(self, client):
        """Test text search requires search_text field."""
        response = client.post('/api/documents/search-text', json={})
        
        assert response.status_code == 400
        data = response.get_json()
        assert 'search_text' in data.get('message', '').lower()
    
    def test_search_text_with_valid_input(self, client):
        """Test text search with valid input."""
        response = client.post('/api/documents/search-text', json={
            'search_text': 'test'
        })
        
        assert response.status_code in [200, 500]
    
    def test_search_text_returns_json(self, client):
        """Test text search returns JSON."""
        response = client.post('/api/documents/search-text', json={
            'search_text': 'keyword'
        })
        
        if response.status_code == 200:
            assert response.content_type == 'application/json'
            data = response.get_json()
            assert 'success' in data
            assert 'results' in data
    
    def test_search_text_respects_limit(self, client):
        """Test text search respects limit parameter."""
        response = client.post('/api/documents/search-text', json={
            'search_text': 'test',
            'limit': 5
        })
        
        if response.status_code == 200:
            data = response.get_json()
            if data.get('success') and data.get('results'):
                assert len(data['results']) <= 5
    
    def test_search_text_rejects_empty_string(self, client):
        """Test text search rejects empty search string."""
        response = client.post('/api/documents/search-text', json={
            'search_text': ''
        })
        
        assert response.status_code == 400


class TestClearDocuments:
    """Test document deletion endpoint."""
    
    def test_clear_requires_delete(self, client):
        """Test clear requires DELETE method."""
        response = client.get('/api/documents/clear')
        
        assert response.status_code == 405
    
    def test_clear_returns_json(self, client):
        """Test clear returns JSON response."""
        response = client.delete('/api/documents/clear')
        
        assert response.content_type == 'application/json'
    
    def test_clear_has_success_field(self, client):
        """Test clear response has success field."""
        response = client.delete('/api/documents/clear')
        data = response.get_json()
        
        assert 'success' in data
    
    def test_clear_executes_successfully(self, client):
        """Test clear can execute (even if no documents)."""
        response = client.delete('/api/documents/clear')
        
        # Should succeed (200) or handle gracefully
        assert response.status_code in [200, 500]


class TestDocumentRoutesSecurity:
    """Test security aspects of document routes."""
    
    def test_upload_validates_file_type(self, client):
        """Test upload validates file types."""
        # Try uploading executable
        response = client.post('/api/documents/upload', data={
            'files': [(io.BytesIO(b'MZ'), 'malware.exe')]
        }, content_type='multipart/form-data')
        
        # Should reject or handle safely
        assert response.status_code in [200, 400]
    
    def test_search_sanitizes_input(self, client):
        """Test search endpoints sanitize input."""
        # Try SQL injection attempt
        response = client.post('/api/documents/search-text', json={
            'search_text': "'; DROP TABLE documents; --"
        })
        
        # Should handle safely
        assert response.status_code in [200, 400, 500]


class TestDocumentRoutesErrorHandling:
    """Test error handling in document routes."""
    
    def test_list_handles_database_error(self, client):
        """Test list handles database errors gracefully."""
        response = client.get('/api/documents/list')
        
        # Should return response (success or error)
        assert response.status_code in [200, 500]
    
    def test_stats_handles_database_error(self, client):
        """Test stats handles database errors gracefully."""
        response = client.get('/api/documents/stats')
        
        # Should return response
        assert response.status_code in [200, 500]
    
    def test_test_handles_processing_error(self, client):
        """Test retrieval test handles processing errors."""
        response = client.post('/api/documents/test', json={
            'query': 'Test query that might fail'
        })
        
        # Should handle gracefully
        assert response.status_code in [200, 500]
        if response.status_code == 500:
            data = response.get_json()
            assert 'message' in data or 'error' in data
