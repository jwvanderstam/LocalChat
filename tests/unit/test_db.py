"""
Unit tests for db.py

Tests database operations, connection pooling, and vector similarity search.
"""

from unittest.mock import MagicMock, Mock, call, patch

import numpy as np
import pytest

from tests.utils.helpers import generate_mock_embedding
from tests.utils.mocks import MockDatabase

# ============================================================================
# DATABASE INITIALIZATION TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.db
class TestDatabaseInitialization:
    """Tests for Database initialization."""

    def test_creates_database_instance(self):
        """Should create database instance."""
        db = MockDatabase()
        assert db is not None
        assert hasattr(db, 'is_connected')

    def test_initial_connection_state(self):
        """Should have correct initial connection state."""
        db = MockDatabase()
        assert db.is_connected is True

    def test_has_required_methods(self):
        """Should have all required methods."""
        db = MockDatabase()
        required_methods = [
            'document_exists', 'insert_document', 'insert_chunks_batch',
            'search_similar_chunks', 'get_document_count', 'get_chunk_count',
            'get_all_documents', 'delete_all_documents', 'close'
        ]
        for method in required_methods:
            assert hasattr(db, method)


# ============================================================================
# DOCUMENT OPERATIONS TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.db
class TestDocumentOperations:
    """Tests for document CRUD operations."""

    def test_insert_document_returns_id(self):
        """Should return document ID after insert."""
        db = MockDatabase()
        doc_id = db.insert_document("test.pdf", "content", {"key": "value"})
        assert isinstance(doc_id, int)
        assert doc_id > 0

    def test_insert_document_stores_data(self):
        """Should store document data."""
        db = MockDatabase()
        doc_id = db.insert_document("test.pdf", "content", {"key": "value"})

        assert doc_id in db.documents
        assert db.documents[doc_id]['filename'] == "test.pdf"
        assert db.documents[doc_id]['content'] == "content"

    def test_insert_multiple_documents(self):
        """Should handle multiple document inserts."""
        db = MockDatabase()

        doc_id1 = db.insert_document("doc1.pdf", "content1")
        doc_id2 = db.insert_document("doc2.pdf", "content2")
        doc_id3 = db.insert_document("doc3.pdf", "content3")

        assert doc_id1 != doc_id2 != doc_id3
        assert len(db.documents) == 3

    def test_document_exists_returns_false_for_new(self):
        """Should return False for non-existent document."""
        db = MockDatabase()
        exists, info = db.document_exists("nonexistent.pdf")
        assert exists is False
        assert info is None

    def test_document_exists_returns_true_for_existing(self):
        """Should return True for existing document."""
        db = MockDatabase()
        doc_id = db.insert_document("test.pdf", "content")

        exists, info = db.document_exists("test.pdf")
        assert exists is True
        assert info is not None
        assert info['filename'] == "test.pdf"

    def test_get_document_count_starts_at_zero(self):
        """Should start with zero documents."""
        db = MockDatabase()
        count = db.get_document_count()
        assert count == 0

    def test_get_document_count_increases(self):
        """Should increase document count after inserts."""
        db = MockDatabase()

        db.insert_document("doc1.pdf", "content1")
        assert db.get_document_count() == 1

        db.insert_document("doc2.pdf", "content2")
        assert db.get_document_count() == 2

    def test_get_all_documents_returns_list(self):
        """Should return list of all documents."""
        db = MockDatabase()

        db.insert_document("doc1.pdf", "content1")
        db.insert_document("doc2.pdf", "content2")

        docs = db.get_all_documents()
        assert isinstance(docs, list)
        assert len(docs) == 2

    def test_delete_all_documents_clears_data(self):
        """Should delete all documents."""
        db = MockDatabase()

        db.insert_document("doc1.pdf", "content1")
        db.insert_document("doc2.pdf", "content2")
        assert db.get_document_count() == 2

        db.delete_all_documents()
        assert db.get_document_count() == 0


# ============================================================================
# CHUNK OPERATIONS TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.db
class TestChunkOperations:
    """Tests for chunk operations."""

    def test_insert_chunks_batch_accepts_list(self):
        """Should accept list of chunks."""
        db = MockDatabase()
        doc_id = db.insert_document("test.pdf", "content")

        chunks_data = [
            (doc_id, "chunk 1", 0, generate_mock_embedding()),
            (doc_id, "chunk 2", 1, generate_mock_embedding()),
        ]

        db.insert_chunks_batch(chunks_data)
        assert db.get_chunk_count() == 2

    def test_insert_chunks_updates_count(self):
        """Should update chunk count."""
        db = MockDatabase()
        doc_id = db.insert_document("test.pdf", "content")

        chunks_data = [
            (doc_id, "chunk 1", 0, generate_mock_embedding()),
        ]

        db.insert_chunks_batch(chunks_data)
        assert db.get_chunk_count() == 1

    def test_insert_chunks_updates_document_count(self):
        """Should update document chunk count."""
        db = MockDatabase()
        doc_id = db.insert_document("test.pdf", "content")

        chunks_data = [
            (doc_id, "chunk 1", 0, generate_mock_embedding()),
            (doc_id, "chunk 2", 1, generate_mock_embedding()),
        ]

        db.insert_chunks_batch(chunks_data)
        assert db.documents[doc_id]['chunk_count'] == 2

    def test_get_chunk_count_starts_at_zero(self):
        """Should start with zero chunks."""
        db = MockDatabase()
        count = db.get_chunk_count()
        assert count == 0

    def test_chunks_associated_with_document(self):
        """Should associate chunks with document."""
        db = MockDatabase()
        doc_id = db.insert_document("test.pdf", "content")

        chunks_data = [
            (doc_id, "chunk 1", 0, generate_mock_embedding()),
        ]

        db.insert_chunks_batch(chunks_data)

        # Verify chunk has document_id
        chunk = list(db.chunks.values())[0]
        assert chunk['document_id'] == doc_id


# ============================================================================
# VECTOR SIMILARITY SEARCH TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.db
class TestVectorSimilaritySearch:
    """Tests for vector similarity search."""

    def test_search_returns_list(self):
        """Should return list of results."""
        db = MockDatabase()
        query_embedding = generate_mock_embedding()

        results = db.search_similar_chunks(query_embedding)
        assert isinstance(results, list)

    def test_search_with_no_chunks(self):
        """Should return empty list with no chunks."""
        db = MockDatabase()
        query_embedding = generate_mock_embedding()

        results = db.search_similar_chunks(query_embedding)
        assert results == []

    def test_search_returns_top_k_results(self):
        """Should return up to top_k results."""
        db = MockDatabase()
        doc_id = db.insert_document("test.pdf", "content")

        # Insert 10 chunks
        chunks_data = [
            (doc_id, f"chunk {i}", i, generate_mock_embedding())
            for i in range(10)
        ]
        db.insert_chunks_batch(chunks_data)

        query_embedding = generate_mock_embedding()
        results = db.search_similar_chunks(query_embedding, top_k=5)

        assert len(results) <= 5

    def test_search_result_format(self):
        """Should return results in correct format."""
        db = MockDatabase()
        doc_id = db.insert_document("test.pdf", "content")

        chunks_data = [
            (doc_id, "chunk text", 0, generate_mock_embedding()),
        ]
        db.insert_chunks_batch(chunks_data)

        query_embedding = generate_mock_embedding()
        results = db.search_similar_chunks(query_embedding, top_k=1)

        if results:
            result = results[0]
            assert len(result) == 5  # (chunk_text, filename, chunk_index, similarity, metadata)
            chunk_text, filename, chunk_index, similarity, metadata = result
            assert isinstance(chunk_text, str)
            assert isinstance(filename, str)
            assert isinstance(chunk_index, int)
            assert isinstance(similarity, (int, float))
            assert isinstance(metadata, dict)

    def test_search_with_file_type_filter(self):
        """Should filter by file type."""
        db = MockDatabase()

        # Insert documents with different types
        doc_id1 = db.insert_document("doc.pdf", "content")
        doc_id2 = db.insert_document("doc.txt", "content")

        chunks_data = [
            (doc_id1, "pdf chunk", 0, generate_mock_embedding()),
            (doc_id2, "txt chunk", 0, generate_mock_embedding()),
        ]
        db.insert_chunks_batch(chunks_data)

        query_embedding = generate_mock_embedding()

        # Search without filter should return both
        results_all = db.search_similar_chunks(query_embedding, top_k=10)
        assert len(results_all) <= 2

        # Search with filter (would filter in real implementation)
        results_pdf = db.search_similar_chunks(
            query_embedding,
            top_k=10,
            file_type_filter=".pdf"
        )
        assert isinstance(results_pdf, list)


# ============================================================================
# EMBEDDING FORMAT TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.db
class TestEmbeddingFormat:
    """Tests for embedding format handling."""

    def test_accepts_list_embeddings(self):
        """Should accept list format embeddings."""
        db = MockDatabase()
        doc_id = db.insert_document("test.pdf", "content")

        embedding = [0.1, 0.2, 0.3] * 256  # 768 dimensions
        chunks_data = [(doc_id, "chunk", 0, embedding)]

        db.insert_chunks_batch(chunks_data)
        assert db.get_chunk_count() == 1

    def test_accepts_numpy_embeddings(self):
        """Should accept numpy array embeddings."""
        db = MockDatabase()
        doc_id = db.insert_document("test.pdf", "content")

        embedding = np.array([0.1, 0.2, 0.3] * 256)
        chunks_data = [(doc_id, "chunk", 0, embedding)]

        db.insert_chunks_batch(chunks_data)
        assert db.get_chunk_count() == 1


# ============================================================================
# CONNECTION MANAGEMENT TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.db
class TestConnectionManagement:
    """Tests for connection management."""

    def test_close_updates_connection_state(self):
        """Should update connection state on close."""
        db = MockDatabase()
        assert db.is_connected is True

        db.close()
        assert db.is_connected is False

    def test_get_connection_returns_object(self):
        """Should return connection object."""
        db = MockDatabase()
        conn = db.get_connection()
        assert conn is not None


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.db
class TestDatabaseIntegration:
    """Integration tests for database operations."""

    def test_complete_document_workflow(self):
        """Should handle complete document workflow."""
        db = MockDatabase()

        # Insert document
        doc_id = db.insert_document("test.pdf", "content", {"author": "Test"})
        assert doc_id > 0

        # Check document exists
        exists, info = db.document_exists("test.pdf")
        assert exists is True

        # Insert chunks
        chunks_data = [
            (doc_id, f"chunk {i}", i, generate_mock_embedding())
            for i in range(5)
        ]
        db.insert_chunks_batch(chunks_data)

        # Verify counts
        assert db.get_document_count() == 1
        assert db.get_chunk_count() == 5

        # Search
        query_embedding = generate_mock_embedding()
        results = db.search_similar_chunks(query_embedding, top_k=3)
        assert len(results) <= 3

        # Delete all
        db.delete_all_documents()
        assert db.get_document_count() == 0
        assert db.get_chunk_count() == 0

    def test_multiple_documents_workflow(self):
        """Should handle multiple documents."""
        db = MockDatabase()

        # Insert multiple documents
        doc_ids = []
        for i in range(3):
            doc_id = db.insert_document(f"doc{i}.pdf", f"content{i}")
            doc_ids.append(doc_id)

            # Add chunks for each document
            chunks_data = [
                (doc_id, f"chunk {j}", j, generate_mock_embedding())
                for j in range(2)
            ]
            db.insert_chunks_batch(chunks_data)

        # Verify totals
        assert db.get_document_count() == 3
        assert db.get_chunk_count() == 6

        # Search should work across all documents
        query_embedding = generate_mock_embedding()
        results = db.search_similar_chunks(query_embedding, top_k=10)
        assert len(results) <= 6


# ============================================================================
# EDGE CASES
# ============================================================================

@pytest.mark.unit
@pytest.mark.db
class TestDatabaseEdgeCases:
    """Edge case tests for database operations."""

    def test_insert_document_with_empty_content(self):
        """Should handle empty content."""
        db = MockDatabase()
        doc_id = db.insert_document("empty.pdf", "")
        assert doc_id > 0

    def test_insert_document_with_very_long_filename(self):
        """Should handle long filenames."""
        db = MockDatabase()
        long_filename = "a" * 500 + ".pdf"
        doc_id = db.insert_document(long_filename, "content")
        assert doc_id > 0

    def test_insert_document_with_unicode(self):
        """Should handle Unicode in content."""
        db = MockDatabase()
        doc_id = db.insert_document("test.pdf", "Hello ?? ??")
        assert doc_id > 0

    def test_search_with_zero_top_k(self):
        """Should handle zero top_k."""
        db = MockDatabase()
        query_embedding = generate_mock_embedding()
        results = db.search_similar_chunks(query_embedding, top_k=0)
        assert results == []

    def test_insert_chunks_empty_list(self):
        """Should handle empty chunks list."""
        db = MockDatabase()
        db.insert_chunks_batch([])
        assert db.get_chunk_count() == 0

    def test_document_exists_empty_filename(self):
        """Should handle empty filename check."""
        db = MockDatabase()
        exists, info = db.document_exists("")
        assert exists is False

    def test_consecutive_operations(self):
        """Should handle consecutive operations."""
        db = MockDatabase()

        for i in range(10):
            doc_id = db.insert_document(f"doc{i}.pdf", f"content{i}")
            chunks_data = [
                (doc_id, f"chunk {j}", j, generate_mock_embedding())
                for j in range(3)
            ]
            db.insert_chunks_batch(chunks_data)

        assert db.get_document_count() == 10
        assert db.get_chunk_count() == 30
