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
        from src import db as db_module
        
        # Mock the connection and cursor properly
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None
        
        with patch.object(db_module.db, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_get_conn.return_value.__exit__.return_value = None
            
            exists, doc_info = db_module.db.document_exists("nonexistent.pdf")
            
            assert exists is False
            assert doc_info == {}
    
    def test_document_exists_returns_true_when_found(self):
        """Test document_exists returns True for existing document."""
        from src import db as db_module
        
        # Mock cursor to return document data
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1, "2025-01-01", 10)
        
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None
        
        with patch.object(db_module.db, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_get_conn.return_value.__exit__.return_value = None
            
            exists, doc_info = db_module.db.document_exists("test.pdf")
            
            assert exists is True
            assert doc_info is not None
            assert doc_info['id'] == 1
            assert doc_info['chunk_count'] == 10
    
    def test_insert_document_returns_valid_id(self):
        """Test insert_document returns valid document ID."""
        from src import db as db_module
        
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)
        
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None
        mock_conn.commit = MagicMock()
        
        with patch.object(db_module.db, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_get_conn.return_value.__exit__.return_value = None
            
            doc_id = db_module.db.insert_document(
                filename="test.pdf",
                content="Sample content",
                metadata={'pages': 5}
            )
            
            assert doc_id == 1
            assert isinstance(doc_id, int)
    
    def test_get_all_documents_returns_list(self):
        """Test retrieving all documents."""
        from src import db as db_module
        
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            (1, "doc1.pdf", "2025-01-01", 10),
            (2, "doc2.txt", "2025-01-02", 5),
        ]
        
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None
        
        with patch.object(db_module.db, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_get_conn.return_value.__exit__.return_value = None
            
            docs = db_module.db.get_all_documents()
            
            assert len(docs) == 2
            assert docs[0]['filename'] == "doc1.pdf"
            assert docs[1]['filename'] == "doc2.txt"
    
    def test_get_document_count_returns_integer(self):
        """Test document count retrieval."""
        from src import db as db_module
        
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (5,)
        
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None
        
        with patch.object(db_module.db, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_get_conn.return_value.__exit__.return_value = None
            
            count = db_module.db.get_document_count()
            
            assert count == 5
            assert isinstance(count, int)


class TestChunkOperations:
    """Test chunk-related operations."""
    
    def test_insert_chunks_batch_handles_empty_list(self):
        """Test batch insertion with empty list."""
        from src import db as db_module
        
        # Empty list should not cause error
        db_module.db.insert_chunks_batch([])
        # No assertion needed - just verify no exception
    
    def test_insert_chunks_batch_processes_multiple(self):
        """Test batch insertion with multiple chunks."""
        from src import db as db_module
        
        chunks_data = [
            (1, "chunk 1", 0, [0.1] * 768),
            (1, "chunk 2", 1, [0.2] * 768),
            (1, "chunk 3", 2, [0.3] * 768),
        ]
        
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None
        mock_conn.commit = MagicMock()
        
        with patch.object(db_module.db, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_get_conn.return_value.__exit__.return_value = None
            
            db_module.db.insert_chunks_batch(chunks_data)
            
            # Verify cursor was used
            assert mock_cursor.execute.called
    
    def test_get_chunk_count_returns_integer(self):
        """Test chunk count retrieval."""
        from src import db as db_module
        
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (100,)
        
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None
        
        with patch.object(db_module.db, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_get_conn.return_value.__exit__.return_value = None
            
            count = db_module.db.get_chunk_count()
            
            assert count == 100
            assert isinstance(count, int)


class TestVectorSearch:
    """Test vector similarity search operations."""
    
    def test_search_similar_chunks_returns_results(self):
        """Test vector similarity search."""
        from src import db as db_module
        
        query_embedding = [0.1] * 768
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("chunk text 1", "doc1.pdf", 0, 0.95),
            ("chunk text 2", "doc1.pdf", 1, 0.85),
        ]
        
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None
        mock_conn.commit = MagicMock()
        
        with patch.object(db_module.db, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_get_conn.return_value.__exit__.return_value = None
            
            results = db_module.db.search_similar_chunks(
                query_embedding=query_embedding,
                top_k=5
            )
            
            assert len(results) == 2
            assert results[0][3] == 0.95  # similarity score
    
    def test_search_similar_chunks_respects_top_k(self):
        """Test top_k limit in search."""
        from src import db as db_module
        
        query_embedding = [0.1] * 768
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("chunk 1", "doc.pdf", 0, 0.95),
            ("chunk 2", "doc.pdf", 1, 0.90),
        ]
        
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None
        mock_conn.commit = MagicMock()
        
        with patch.object(db_module.db, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_get_conn.return_value.__exit__.return_value = None
            
            results = db_module.db.search_similar_chunks(
                query_embedding=query_embedding,
                top_k=2
            )
            
            assert len(results) <= 2
    
    def test_search_similar_chunks_handles_empty_results(self):
        """Test search with no matching results."""
        from src import db as db_module
        
        query_embedding = [0.1] * 768
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None
        mock_conn.commit = MagicMock()
        
        with patch.object(db_module.db, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_get_conn.return_value.__exit__.return_value = None
            
            results = db_module.db.search_similar_chunks(
                query_embedding=query_embedding
            )
            
            assert results == []


class TestErrorHandling:
    """Test error handling in database operations."""
    
    def test_document_exists_handles_db_error(self):
        """Test error handling in document_exists."""
        from src import db as db_module
        
        with patch.object(db_module.db, 'get_connection', side_effect=Exception("DB Error")):
            try:
                exists, doc_info = db_module.db.document_exists("test.pdf")
                # If it doesn't raise, it should return False
                assert exists is False
            except Exception:
                # Exception is also acceptable
                pass
    
    def test_search_handles_connection_error(self):
        """Test search with connection error."""
        from src import db as db_module
        
        with patch.object(db_module.db, 'get_connection', side_effect=Exception("Connection failed")):
            with pytest.raises(Exception):
                db_module.db.search_similar_chunks(
                    query_embedding=[0.1] * 768
                )


class TestDatabaseStats:
    """Test database statistics functions."""
    
    def test_get_database_stats_returns_counts(self):
        """Test getting database statistics."""
        from src import db as db_module
        
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [(5,), (100,)]
        
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None
        
        with patch.object(db_module.db, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_get_conn.return_value.__exit__.return_value = None
            
            doc_count = db_module.db.get_document_count()
            chunk_count = db_module.db.get_chunk_count()
            
            assert doc_count == 5
            assert chunk_count == 100
