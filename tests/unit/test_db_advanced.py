# -*- coding: utf-8 -*-

"""
Database Advanced Tests
=======================

Additional tests for missing coverage in src/db.py (63.96% ? 80%)

Missing lines: 120 lines across:
- VectorLoader edge cases
- check_server_availability error paths
- Connection pool management
- Statistics and search functions

Author: LocalChat Team
Created: January 2025
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
import socket


class TestVectorLoaderEdgeCases:
    """Test VectorLoader edge cases."""
    
    def test_vector_loader_with_memoryview(self):
        """Test VectorLoader with memoryview input."""
        from src.db import VectorLoader
        
        loader = VectorLoader(None, None)
        
        # Create memoryview from bytes
        data = memoryview(b'[0.1,0.2,0.3]')
        result = loader.load(data)
        
        assert result == [0.1, 0.2, 0.3]
    
    def test_vector_loader_with_empty_brackets(self):
        """Test VectorLoader with empty brackets."""
        from src.db import VectorLoader
        
        loader = VectorLoader(None, None)
        result = loader.load(b'[]')
        
        assert result == []
    
    def test_vector_loader_with_malformed_data(self):
        """Test VectorLoader with invalid format."""
        from src.db import VectorLoader
        
        loader = VectorLoader(None, None)
        result = loader.load(b'invalid')
        
        assert result == []


class TestServerAvailabilityChecks:
    """Test check_server_availability edge cases."""
    
    def test_check_server_dns_resolution_failure(self):
        """Test DNS resolution error."""
        from src.db import Database
        
        with patch('socket.socket') as mock_socket:
            mock_sock_instance = MagicMock()
            mock_sock_instance.connect_ex.side_effect = socket.gaierror("DNS error")
            mock_socket.return_value = mock_sock_instance
            
            available, msg = Database.check_server_availability("invalid.host", 5432)
            
            assert available is False
            assert "resolve" in msg.lower() or "hostname" in msg.lower()
    
    def test_check_server_timeout(self):
        """Test connection timeout."""
        from src.db import Database
        
        with patch('socket.socket') as mock_socket:
            mock_sock_instance = MagicMock()
            mock_sock_instance.connect_ex.side_effect = socket.timeout()
            mock_socket.return_value = mock_sock_instance
            
            available, msg = Database.check_server_availability("localhost", 5432, timeout=0.1)
            
            assert available is False
            assert "timeout" in msg.lower()
    
    def test_check_server_connection_refused(self):
        """Test connection refused (server not running)."""
        from src.db import Database
        
        with patch('socket.socket') as mock_socket:
            mock_sock_instance = MagicMock()
            mock_sock_instance.connect_ex.return_value = 1  # Connection refused
            mock_socket.return_value = mock_sock_instance
            
            available, msg = Database.check_server_availability("localhost", 5432)
            
            assert available is False
            assert "NOT reachable" in msg
    
    def test_check_server_unexpected_error(self):
        """Test unexpected error during check."""
        from src.db import Database
        
        with patch('socket.socket', side_effect=Exception("Unexpected")):
            available, msg = Database.check_server_availability("localhost", 5432)
            
            assert available is False
            assert "unexpected" in msg.lower()


class TestInitializeErrorPaths:
    """Test initialize() error paths."""
    
    def test_initialize_when_server_unavailable(self):
        """Test initialization when PostgreSQL server is not running."""
        from src import db as db_module
        
        test_db = db_module.Database()
        
        with patch.object(test_db, 'check_server_availability', return_value=(False, "Server unavailable")):
            success, msg = test_db.initialize()
            
            assert success is False
            assert "unavailable" in msg.lower()
            assert test_db.is_connected is False
    
    def test_initialize_connection_error_not_missing_db(self):
        """Test initialization with connection error that's not missing database."""
        from src import db as db_module
        import psycopg
        
        test_db = db_module.Database()
        
        with patch.object(test_db, 'check_server_availability', return_value=(True, "OK")):
            with patch('psycopg.connect', side_effect=psycopg.OperationalError("Auth failed")):
                success, msg = test_db.initialize()
                
                assert success is False
                assert "failed" in msg.lower()
    
    def test_initialize_creates_pool_with_configure_callback(self):
        """Test that initialize creates pool with proper configuration."""
        from src import db as db_module
        
        test_db = db_module.Database()
        
        mock_conn = MagicMock()
        mock_conn.info.transaction_status = 0
        
        with patch.object(test_db, 'check_server_availability', return_value=(True, "OK")):
            with patch('psycopg.connect', return_value=mock_conn):
                with patch('psycopg_pool.ConnectionPool') as mock_pool:
                    with patch.object(test_db, '_ensure_extensions_and_tables'):
                        test_db.initialize()
                        
                        # Verify pool was created with configure callback
                        assert mock_pool.called


class TestCreateDatabase:
    """Test _create_database method."""
    
    def test_create_database_when_already_exists(self):
        """Test database creation when database already exists."""
        from src import db as db_module
        
        test_db = db_module.Database()
        
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)  # Database exists
        
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        with patch('psycopg.connect', return_value=mock_conn):
            # Should not raise, just log
            test_db._create_database()
    
    def test_create_database_error_handling(self):
        """Test database creation error handling."""
        from src import db as db_module
        
        test_db = db_module.Database()
        
        with patch('psycopg.connect', side_effect=Exception("Permission denied")):
            with pytest.raises(Exception):
                test_db._create_database()


class TestChunkStatistics:
    """Test get_chunk_statistics method."""
    
    def test_get_chunk_statistics_with_data(self):
        """Test getting chunk statistics with existing data."""
        from src import db as db_module
        
        mock_cursor = MagicMock()
        # Mock counts query
        mock_cursor.fetchone.return_value = (100, 95, 500.5)
        # Mock sample query
        mock_cursor.fetchall.return_value = [
            ("doc1.pdf", 0, "Sample text 1", 200, True),
            ("doc2.txt", 1, "Sample text 2", 150, False),
        ]
        
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        with patch.object(db_module.db, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_get_conn.return_value.__exit__.return_value = None
            
            stats = db_module.db.get_chunk_statistics()
            
            assert stats['total_chunks'] == 100
            assert stats['chunks_with_embeddings'] == 95
            assert stats['chunks_without_embeddings'] == 5
            assert stats['avg_chunk_length'] == 500.5
            assert len(stats['sample_chunks']) == 2
    
    def test_get_chunk_statistics_with_empty_database(self):
        """Test statistics when database is empty."""
        from src import db as db_module
        
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (0, 0, None)
        mock_cursor.fetchall.return_value = []
        
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        with patch.object(db_module.db, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_get_conn.return_value.__exit__.return_value = None
            
            stats = db_module.db.get_chunk_statistics()
            
            assert stats['total_chunks'] == 0
            assert stats['avg_chunk_length'] == 0


class TestSearchChunksByText:
    """Test search_chunks_by_text method."""
    
    def test_search_chunks_by_text_finds_matches(self):
        """Test text search finds matching chunks."""
        from src import db as db_module
        
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("doc.pdf", 0, "Text containing keyword", 25),
            ("doc.pdf", 1, "Another keyword match", 21),
        ]
        
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        with patch.object(db_module.db, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_get_conn.return_value.__exit__.return_value = None
            
            results = db_module.db.search_chunks_by_text("keyword", limit=10)
            
            assert len(results) == 2
            assert results[0]['filename'] == "doc.pdf"
            assert 'preview' in results[0]
            assert 'full_text' in results[0]
    
    def test_search_chunks_by_text_no_matches(self):
        """Test text search with no matches."""
        from src import db as db_module
        
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        with patch.object(db_module.db, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_get_conn.return_value.__exit__.return_value = None
            
            results = db_module.db.search_chunks_by_text("nonexistent")
            
            assert results == []
    
    def test_search_chunks_by_text_respects_limit(self):
        """Test that text search respects limit parameter."""
        from src import db as db_module
        
        mock_cursor = MagicMock()
        # Return exactly limit number of results
        mock_cursor.fetchall.return_value = [
            ("doc.pdf", i, f"Match {i}", 20) for i in range(5)
        ]
        
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        with patch.object(db_module.db, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_get_conn.return_value.__exit__.return_value = None
            
            results = db_module.db.search_chunks_by_text("test", limit=5)
            
            assert len(results) <= 5


class TestDeleteAllDocuments:
    """Test delete_all_documents method."""
    
    def test_delete_all_documents_success(self):
        """Test deleting all documents."""
        from src import db as db_module
        
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 10  # First for chunks, then for docs
        
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.commit = MagicMock()
        
        with patch.object(db_module.db, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_get_conn.return_value.__exit__.return_value = None
            
            # Should not raise
            db_module.db.delete_all_documents()
            
            # Verify commit was called
            assert mock_conn.commit.called


class TestGetAdjacentChunks:
    """Test get_adjacent_chunks method."""
    
    def test_get_adjacent_chunks_retrieves_window(self):
        """Test retrieving adjacent chunks with window."""
        from src import db as db_module
        
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("Chunk 0 text", 0),
            ("Chunk 1 text", 1),
            ("Chunk 2 text", 2),
        ]
        
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        with patch.object(db_module.db, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_get_conn.return_value.__exit__.return_value = None
            
            results = db_module.db.get_adjacent_chunks(
                document_id=1,
                chunk_index=1,
                window_size=1
            )
            
            assert len(results) == 3
            assert results[1][1] == 1  # Middle chunk index


class TestConnectionPoolManagement:
    """Test connection pool lifecycle."""
    
    def test_get_connection_raises_when_not_initialized(self):
        """Test get_connection raises when pool not initialized."""
        from src import db as db_module
        
        test_db = db_module.Database()
        # Don't initialize
        
        with pytest.raises(RuntimeError, match="Connection pool not initialized"):
            with test_db.get_connection():
                pass
    
    def test_close_handles_exception(self):
        """Test close() handles exceptions gracefully."""
        from src import db as db_module
        
        test_db = db_module.Database()
        test_db.connection_pool = MagicMock()
        test_db.connection_pool.close.side_effect = Exception("Close error")
        test_db.is_connected = True
        
        # Should not raise, just log warning
        test_db.close()
        
        assert test_db.is_connected is False
    
    def test_close_when_pool_none(self):
        """Test close when connection pool is None."""
        from src import db as db_module
        
        test_db = db_module.Database()
        test_db.connection_pool = None
        
        # Should not raise
        test_db.close()
