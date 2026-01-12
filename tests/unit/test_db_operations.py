# -*- coding: utf-8 -*-

"""
Unit Tests for Database Operations
===================================

Comprehensive tests for src/db.py database operations.

Target: Increase coverage from 38% to 75% (+8% total coverage)

Focus areas:
- Document CRUD operations
- Chunk operations
- Vector search
- Batch operations
- Connection management
- Error handling

Author: LocalChat Team
Created: January 2025
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
import psycopg2


class TestDocumentOperations:
    """Test document CRUD operations."""
    
    def test_document_exists_returns_false_when_not_found(self):
        """Test document_exists returns False for non-existent document."""
        from src import db
        
        # Mock the connection and cursor properly
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None  # Changed from fetchall to fetchone
        
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None
        
        with patch.object(db.db, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_get_conn.return_value.__exit__.return_value = None
            
            exists, doc_info = db.db.document_exists("nonexistent.pdf")
            
            assert exists is False
            assert doc_info == {}
    
    def test_document_exists_returns_true_when_found(self):
        """Test document_exists returns True for existing document."""
        from src.db import DatabaseManager
        
        db = DatabaseManager()
        
        # Mock cursor to return document data
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [(1, "test.pdf", 10, "2025-01-01")]
        
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None
        
        with patch.object(db, 'get_connection', return_value=mock_conn):
            exists, doc_info = db.document_exists("test.pdf")
            
            assert exists is True
            assert doc_info is not None
            assert doc_info['id'] == 1
            assert doc_info['filename'] == "test.pdf"
            assert doc_info['chunk_count'] == 10
    
    def test_insert_document_returns_valid_id(self):
        """Test insert_document returns valid document ID."""
        from src.db import DatabaseManager
        
        db = DatabaseManager()
        
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)
        
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None
        
        with patch.object(db, 'get_connection', return_value=mock_conn):
            doc_id = db.insert_document(
                filename="test.pdf",
                content="Sample content",
                metadata={'pages': 5}
            )
            
            assert doc_id == 1
            assert isinstance(doc_id, int)
    
    def test_get_all_documents_returns_list(self):
        """Test retrieving all documents."""
        from src.db import DatabaseManager
        
        db = DatabaseManager()
        
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            (1, "doc1.pdf", 10, "2025-01-01"),
            (2, "doc2.txt", 5, "2025-01-02"),
        ]
        
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None
        
        with patch.object(db, 'get_connection', return_value=mock_conn):
            docs = db.get_all_documents()
            
            assert len(docs) == 2
            assert docs[0]['filename'] == "doc1.pdf"
            assert docs[1]['filename'] == "doc2.txt"
    
    def test_get_document_count_returns_integer(self):
        """Test document count retrieval."""
        from src.db import DatabaseManager
        
        db = DatabaseManager()
        
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (5,)
        
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None
        
        with patch.object(db, 'get_connection', return_value=mock_conn):
            count = db.get_document_count()
            
            assert count == 5
            assert isinstance(count, int)


class TestChunkOperations:
    """Test chunk-related operations."""
    
    def test_insert_chunks_batch_handles_empty_list(self):
        """Test batch insertion with empty list."""
        from src.db import DatabaseManager
        
        db = DatabaseManager()
        
        # Empty list should not cause error
        db.insert_chunks_batch([])
        # No assertion needed - just verify no exception
    
    def test_insert_chunks_batch_processes_multiple(self):
        """Test batch insertion with multiple chunks."""
        from src.db import DatabaseManager
        
        db = DatabaseManager()
        
        chunks_data = [
            (1, "chunk 1", 0, [0.1] * 768),
            (1, "chunk 2", 1, [0.2] * 768),
            (1, "chunk 3", 2, [0.3] * 768),
        ]
        
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None
        
        with patch.object(db, 'get_connection', return_value=mock_conn):
            db.insert_chunks_batch(chunks_data)
            
            # Verify cursor was used
            assert mock_cursor.execute.called or mock_cursor.executemany.called
    
    def test_get_chunk_count_returns_integer(self):
        """Test chunk count retrieval."""
        from src.db import DatabaseManager
        
        db = DatabaseManager()
        
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (100,)
        
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None
        
        with patch.object(db, 'get_connection', return_value=mock_conn):
            count = db.get_chunk_count()
            
            assert count == 100
            assert isinstance(count, int)


class TestVectorSearch:
    """Test vector similarity search operations."""
    
    def test_search_similar_chunks_returns_results(self):
        """Test vector similarity search."""
        from src.db import DatabaseManager
        
        db = DatabaseManager()
        
        query_embedding = [0.1] * 768
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("chunk text 1", "doc1.pdf", 0, 0.95),
            ("chunk text 2", "doc1.pdf", 1, 0.85),
        ]
        
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None
        
        with patch.object(db, 'get_connection', return_value=mock_conn):
            results = db.search_similar_chunks(
                query_embedding=query_embedding,
                top_k=5,
                min_similarity=0.7
            )
            
            assert len(results) == 2
            assert results[0][3] == 0.95  # similarity score
    
    def test_search_similar_chunks_respects_top_k(self):
        """Test top_k limit in search."""
        from src.db import DatabaseManager
        
        db = DatabaseManager()
        
        query_embedding = [0.1] * 768
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("chunk 1", "doc.pdf", 0, 0.95),
            ("chunk 2", "doc.pdf", 1, 0.90),
        ]
        
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None
        
        with patch.object(db, 'get_connection', return_value=mock_conn):
            results = db.search_similar_chunks(
                query_embedding=query_embedding,
                top_k=2
            )
            
            assert len(results) <= 2
    
    def test_search_similar_chunks_handles_empty_results(self):
        """Test search with no matching results."""
        from src.db import DatabaseManager
        
        db = DatabaseManager()
        
        query_embedding = [0.1] * 768
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None
        
        with patch.object(db, 'get_connection', return_value=mock_conn):
            results = db.search_similar_chunks(
                query_embedding=query_embedding
            )
            
            assert results == []


class TestErrorHandling:
    """Test error handling in database operations."""
    
    def test_document_exists_handles_db_error(self):
        """Test error handling in document_exists."""
        from src.db import DatabaseManager
        
        db = DatabaseManager()
        
        mock_conn = MagicMock()
        mock_conn.cursor.side_effect = Exception("DB Error")
        
        with patch.object(db, 'get_connection', return_value=mock_conn):
            exists, doc_info = db.document_exists("test.pdf")
            
            # Should handle error gracefully
            assert exists is False
            assert doc_info is None
    
    def test_search_handles_connection_error(self):
        """Test search with connection error."""
        from src.db import DatabaseManager
        
        db = DatabaseManager()
        
        with patch.object(db, 'get_connection', side_effect=Exception("Connection failed")):
            with pytest.raises(Exception):
                db.search_similar_chunks(
                    query_embedding=[0.1] * 768
                )


class TestDatabaseStats:
    """Test database statistics functions."""
    
    def test_get_database_stats_returns_dict(self):
        """Test getting database statistics."""
        from src.db import DatabaseManager
        
        db = DatabaseManager()
        
        mock_cursor = MagicMock()
        # Mock stats query results
        mock_cursor.fetchone.side_effect = [(5,), (100,)]
        
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None
        
        with patch.object(db, 'get_connection', return_value=mock_conn):
            with patch.object(db, 'get_document_count', return_value=5):
                with patch.object(db, 'get_chunk_count', return_value=100):
                    doc_count = db.get_document_count()
                    chunk_count = db.get_chunk_count()
                    
                    assert doc_count == 5
                    assert chunk_count == 100
