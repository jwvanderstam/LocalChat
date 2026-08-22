
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

from datetime import datetime
from unittest.mock import MagicMock, patch

import psycopg
import pytest


@pytest.fixture(autouse=True)
def _ensure_db_connected():
    """Temporarily mark db as connected for tests that mock get_connection."""
    from src import db as db_module
    old = db_module.db.is_connected
    db_module.db.is_connected = True
    yield
    db_module.db.is_connected = old


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

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1, datetime(2025, 1, 1), 10, "abc123")

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

    def test_insert_document_stores_content_as_plain_text_even_with_a_key_set(self):
        """SEC-4 — documents.content is deliberately not field-encrypted.

        It was encrypted on write and never decrypted, while the same text sits
        in plain text in document_chunks.chunk_text, which is what retrieval
        reads. Re-adding encryption here protects nothing and this test says so.
        """
        from cryptography.fernet import Fernet

        from src import config
        from src import db as db_module

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None

        original_key = config.ENCRYPTION_KEY
        config.ENCRYPTION_KEY = Fernet.generate_key().decode()
        try:
            with patch.object(db_module.db, 'get_connection') as mock_get_conn:
                mock_get_conn.return_value.__enter__.return_value = mock_conn
                mock_get_conn.return_value.__exit__.return_value = None

                db_module.db.insert_document(
                    filename="test.pdf", content="Sample content", metadata={}
                )
        finally:
            config.ENCRYPTION_KEY = original_key

        params = mock_cursor.execute.call_args[0][1]
        assert params[1] == "Sample content"

    def test_get_all_documents_returns_list(self):
        """Test retrieving all documents."""
        from src import db as db_module

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            (1, "doc1.pdf", datetime(2025, 1, 1), 10),
            (2, "doc2.txt", datetime(2025, 1, 2), 5),
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

    def test_document_exists_scopes_query_by_workspace_id(self):
        """document_exists must filter by workspace_id — a filename collision
        across two workspaces must not read the wrong workspace's document."""
        from src import db as db_module

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None

        with patch.object(db_module.db, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_get_conn.return_value.__exit__.return_value = None

            db_module.db.document_exists("report.txt", workspace_id="ws-1")

            args, _ = mock_cursor.execute.call_args
            query, params = args
            assert "workspace_id" in query
            assert params == ("report.txt", "ws-1")

    def test_insert_document_with_conn_does_not_commit_or_acquire_pool_connection(self):
        """When conn is supplied, insert_document must use it directly and
        leave commit/rollback/pool-return to the caller's transaction."""
        from src import db as db_module

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (7,)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None

        with patch.object(db_module.db, 'get_connection') as mock_get_conn:
            doc_id = db_module.db.insert_document(
                filename="test.pdf", content="content", conn=mock_conn
            )

            assert doc_id == 7
            mock_conn.commit.assert_not_called()
            mock_get_conn.assert_not_called()

    def test_update_document_updates_by_id_and_preserves_it(self):
        """update_document must UPDATE the existing row, not create a new one."""
        from src import db as db_module

        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None
        mock_conn.commit = MagicMock()

        with patch.object(db_module.db, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_get_conn.return_value.__exit__.return_value = None

            db_module.db.update_document(
                3, content="new content", content_hash="newhash"
            )

            args, params = mock_cursor.execute.call_args[0]
            assert "UPDATE documents" in args
            assert params[-1] == 3  # doc_id is the WHERE-clause parameter
            mock_conn.commit.assert_called_once()

    def test_update_document_with_conn_does_not_commit(self):
        from src import db as db_module

        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None

        with patch.object(db_module.db, 'get_connection') as mock_get_conn:
            db_module.db.update_document(3, content="new content", conn=mock_conn)

            mock_conn.commit.assert_not_called()
            mock_get_conn.assert_not_called()

    def test_soft_delete_chunks_for_document_sets_deleted_at(self):
        """Old chunks must be retired (deleted_at set), not removed — rows are
        kept so citations referencing them still resolve."""
        from src import db as db_module

        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None
        mock_conn.commit = MagicMock()

        with patch.object(db_module.db, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_get_conn.return_value.__exit__.return_value = None

            db_module.db.soft_delete_chunks_for_document(3)

            args, params = mock_cursor.execute.call_args[0]
            assert "UPDATE document_chunks" in args
            assert "deleted_at" in args
            assert "DELETE" not in args
            assert params == (3,)
            mock_conn.commit.assert_called_once()

    def test_soft_delete_chunks_for_document_with_conn_does_not_commit(self):
        from src import db as db_module

        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None

        with patch.object(db_module.db, 'get_connection') as mock_get_conn:
            db_module.db.soft_delete_chunks_for_document(3, conn=mock_conn)

            mock_conn.commit.assert_not_called()
            mock_get_conn.assert_not_called()


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

    def test_insert_chunks_batch_with_conn_does_not_commit_or_acquire_pool_connection(self):
        """When conn is supplied, insert_chunks_batch must use it directly and
        leave commit/rollback/pool-return to the caller's transaction."""
        from src import db as db_module

        chunks_data = [(1, "chunk 1", 0, [0.1] * 768)]

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [(11,)]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None

        with patch.object(db_module.db, 'get_connection') as mock_get_conn:
            chunk_ids = db_module.db.insert_chunks_batch(chunks_data, conn=mock_conn)

            assert chunk_ids == [11]
            mock_conn.commit.assert_not_called()
            mock_get_conn.assert_not_called()

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
            ("chunk text 1", "doc1.pdf", 0, 0.95, {}, 1),
            ("chunk text 2", "doc1.pdf", 1, 0.85, {}, 2),
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
            ("chunk 1", "doc.pdf", 0, 0.95, {}, 1),
            ("chunk 2", "doc.pdf", 1, 0.90, {}, 2),
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


class TestLexicalSearch:
    """Test the independent full-text lexical search arm (hybrid retrieval fix)."""

    def test_search_lexical_chunks_returns_results(self):
        """Lexical search returns the same 6-tuple shape as vector search."""
        from src import db as db_module

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("chunk text 1", "doc1.pdf", 0, 0.55, {}, 1),
            ("chunk text 2", "doc1.pdf", 1, 0.30, {}, 2),
        ]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None

        with patch.object(db_module.db, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_get_conn.return_value.__exit__.return_value = None

            results = db_module.db.search_lexical_chunks(query="exact code ABC-123", top_k=5)

            assert len(results) == 2
            assert results[0] == ("chunk text 1", "doc1.pdf", 0, 0.55, {}, 1)

    def test_search_lexical_chunks_handles_empty_results(self):
        """No lexical matches returns an empty list, not None or an error."""
        from src import db as db_module

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None

        with patch.object(db_module.db, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_get_conn.return_value.__exit__.return_value = None

            results = db_module.db.search_lexical_chunks(query="nothing matches this")

            assert results == []

    def test_search_lexical_chunks_returns_empty_for_blank_query(self):
        """A blank/whitespace-only query short-circuits before hitting the DB."""
        from src import db as db_module

        with patch.object(db_module.db, 'get_connection') as mock_get_conn:
            results = db_module.db.search_lexical_chunks(query="   ")

            assert results == []
            mock_get_conn.assert_not_called()

    def test_search_lexical_chunks_applies_filename_filter(self):
        """filename_filter is forwarded as a query parameter, not silently dropped."""
        from src import db as db_module

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None

        with patch.object(db_module.db, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_get_conn.return_value.__exit__.return_value = None

            db_module.db.search_lexical_chunks(query="term", filename_filter=["a.pdf", "b.pdf"])

            executed_sql, params = mock_cursor.execute.call_args.args
            assert "d.filename = ANY(%s)" in executed_sql
            assert ["a.pdf", "b.pdf"] in params


class TestErrorHandling:
    """Test error handling in database operations."""

    def test_document_exists_handles_db_error(self):
        """Test error handling in document_exists."""
        from src import db as db_module

        # is_connected has to be patched too. Without it the "Database is not
        # connected" guard fires first and get_connection is never called, so the
        # test named after a connection error never reached one.
        with patch.object(db_module.db, 'is_connected', True),              patch.object(db_module.db, 'get_connection',
                          side_effect=psycopg.OperationalError("DB Error")):
            with pytest.raises(psycopg.OperationalError):
                db_module.db.document_exists("test.pdf")

    def test_search_handles_connection_error(self):
        """Test search with connection error."""
        from src import db as db_module

        with patch.object(db_module.db, 'is_connected', True),              patch.object(db_module.db, 'get_connection',
                          side_effect=psycopg.OperationalError("Connection failed")):
            # The specific type, so this cannot pass on any exception at all — and
            # so it records that search does not swallow a failed connection into
            # an empty result set, which would read as "no matching documents".
            with pytest.raises(psycopg.OperationalError):
                db_module.db.search_similar_chunks(query_embedding=[0.1] * 768)


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
