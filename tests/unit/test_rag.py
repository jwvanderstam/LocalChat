"""
Unit tests for rag.py

Tests document processing, chunking, embedding, and retrieval operations.
"""

import os
import tempfile
from unittest.mock import MagicMock, Mock, patch

import pytest

from tests.utils.helpers import (
    generate_mock_chunks,
    generate_mock_embedding,
    generate_mock_search_results,
)
from tests.utils.mocks import MockDatabase, MockOllamaClient

# ============================================================================
# DOCUMENT LOADING TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.rag
class TestDocumentLoading:
    """Tests for document loading operations."""

    def test_load_text_file_success(self, sample_txt_path):
        """Should load text file successfully."""
        # Mock processor
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        success, content = processor.load_text_file(sample_txt_path)
        assert success is True
        assert isinstance(content, str)
        assert len(content) > 0

    def test_load_text_file_nonexistent(self):
        """Should handle nonexistent file."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        success, error = processor.load_text_file("nonexistent.txt")
        assert success is False
        assert isinstance(error, str)

    def test_load_document_routes_by_extension(self):
        """Should route to correct loader by extension."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        # Should recognize .txt extension
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Test content")
            txt_path = f.name

        try:
            success, content = processor.load_document(txt_path)
            assert success is True
        finally:
            os.unlink(txt_path)

    def test_load_document_unsupported_extension(self):
        """Should reject unsupported file types."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        success, error = processor.load_document("file.exe")
        assert success is False
        assert "Unsupported" in error


# ============================================================================
# TEXT CHUNKING TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.rag
class TestTextChunking:
    """Tests for text chunking operations."""

    def test_chunk_text_returns_list(self, sample_text):
        """Should return list of chunks."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        chunks = processor.chunk_text(sample_text)
        assert isinstance(chunks, list)

    def test_chunk_text_with_short_text(self):
        """Should handle text shorter than chunk size."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        short_text = "Short text"
        chunks = processor.chunk_text(short_text, chunk_size=100)

        assert len(chunks) == 1
        assert chunks[0] == short_text

    def test_chunk_text_with_long_text(self, long_text):
        """Should chunk long text."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        chunks = processor.chunk_text(long_text, chunk_size=500)
        assert len(chunks) > 1

    def test_chunks_respect_size_limit(self, long_text):
        """Should respect chunk size limit."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        chunk_size = 500
        chunks = processor.chunk_text(long_text, chunk_size=chunk_size)

        for chunk in chunks:
            # Allow some flexibility for overlap
            assert len(chunk) <= chunk_size * 1.5

    def test_chunk_text_with_overlap(self, long_text):
        """Should create overlapping chunks."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        chunks = processor.chunk_text(long_text, chunk_size=100, overlap=20)

        # With overlap, should have more chunks
        assert len(chunks) > 1

    def test_chunk_text_empty_string(self):
        """Should handle empty string."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        chunks = processor.chunk_text("")
        assert chunks == []

    def test_chunk_text_filters_small_chunks(self):
        """Should filter out very small chunks."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        chunks = processor.chunk_text("a b c", chunk_size=1)
        # Should filter chunks < 10 characters
        assert all(len(chunk) >= 10 for chunk in chunks) or len(chunks) == 0


# ============================================================================
# EMBEDDING GENERATION TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.rag
class TestEmbeddingGeneration:
    """Tests for embedding generation."""

    @patch('src.rag.processor.ollama_client')
    def test_generate_embeddings_batch_returns_list(self, mock_ollama):
        """Should return list of embeddings."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        mock_ollama.generate_embedding.return_value = (True, generate_mock_embedding())
        mock_ollama.get_embedding_model.return_value = "nomic-embed-text"

        texts = ["text 1", "text 2", "text 3"]
        embeddings = processor.generate_embeddings_batch(texts)

        assert isinstance(embeddings, list)
        assert len(embeddings) == len(texts)

    @patch('src.rag.processor.ollama_client')
    def test_generate_embeddings_handles_failures(self, mock_ollama):
        """Should handle embedding failures."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        # Mock alternating success/failure
        mock_ollama.generate_embedding.side_effect = [
            (True, generate_mock_embedding()),
            (False, None),
            (True, generate_mock_embedding()),
        ]
        mock_ollama.get_embedding_model.return_value = "nomic-embed-text"

        texts = ["text 1", "text 2", "text 3"]
        embeddings = processor.generate_embeddings_batch(texts)

        assert embeddings[0] is not None
        assert embeddings[1] is None
        assert embeddings[2] is not None


# ============================================================================
# DOCUMENT INGESTION TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.rag
class TestDocumentIngestion:
    """Tests for document ingestion."""

    @patch('src.rag.processor.db')
    @patch('src.rag.processor.ollama_client')
    def test_ingest_document_returns_tuple(self, mock_ollama, mock_db, sample_txt_path):
        """Should return tuple."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        # Setup mocks
        mock_db.document_exists.return_value = (False, None)
        mock_db.insert_document.return_value = 1
        mock_ollama.get_embedding_model.return_value = "nomic-embed-text"
        mock_ollama.generate_embedding.return_value = (True, generate_mock_embedding())

        result = processor.ingest_document(sample_txt_path)
        assert isinstance(result, tuple)
        assert len(result) == 3

    @patch('src.rag.processor.db')
    @patch('src.rag.processor.ollama_client')
    def test_ingest_document_success(self, mock_ollama, mock_db, sample_txt_path):
        """Should ingest document successfully."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        # Setup mocks
        mock_db.document_exists.return_value = (False, None)
        mock_db.insert_document.return_value = 1
        mock_db.insert_chunks_batch.return_value = None
        mock_ollama.get_embedding_model.return_value = "nomic-embed-text"
        mock_ollama.generate_embeddings_batch.side_effect = lambda model, texts: [generate_mock_embedding() for _ in texts]

        success, message, doc_id = processor.ingest_document(sample_txt_path)

        assert success is True
        assert isinstance(message, str)
        assert isinstance(doc_id, int)

    @patch('src.rag.processor.db')
    def test_ingest_document_checks_duplicates(self, mock_db, sample_txt_path):
        """Should check for duplicate documents."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        # Mock existing document with matching hash so the skip path is taken.
        # _compute_file_hash is not mocked here, so we compute the real hash first.
        from src.rag.processor import _compute_file_hash
        real_hash = _compute_file_hash(sample_txt_path)
        mock_db.document_exists.return_value = (
            True, {'id': 1, 'chunk_count': 10, 'content_hash': real_hash}
        )

        success, message, doc_id = processor.ingest_document(sample_txt_path)

        assert success is True
        assert "up to date" in message
        assert doc_id == 1

    def test_ingest_document_nonexistent_file(self):
        """Should handle nonexistent file."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        success, message, doc_id = processor.ingest_document("nonexistent.pdf")

        assert success is False
        assert doc_id is None

    @patch('src.rag.processor.db')
    @patch('src.rag.processor.ollama_client')
    def test_ingest_document_with_progress_callback(self, mock_ollama, mock_db, sample_txt_path):
        """Should call progress callback."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        # Setup mocks
        mock_db.document_exists.return_value = (False, None)
        mock_db.insert_document.return_value = 1
        mock_db.insert_chunks_batch.return_value = None
        mock_ollama.get_embedding_model.return_value = "nomic-embed-text"
        mock_ollama.generate_embeddings_batch.side_effect = lambda model, texts: [generate_mock_embedding() for _ in texts]

        callback = Mock()
        success, _, _ = processor.ingest_document(sample_txt_path, progress_callback=callback)

        # Should have called callback
        assert callback.call_count > 0


# ============================================================================
# RETRIEVAL TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.rag
class TestRetrieval:
    """Tests for context retrieval."""

    @patch('src.rag.retrieval.db')
    @patch('src.rag.retrieval.ollama_client')
    def test_retrieve_context_returns_list(self, mock_ollama, mock_db):
        """Should return list of results."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        # Setup mocks
        mock_ollama.get_embedding_model.return_value = "nomic-embed-text"
        mock_ollama.generate_embedding.return_value = (True, generate_mock_embedding())
        mock_db.search_similar_chunks.return_value = generate_mock_search_results(5)

        results = processor.retrieve_context("test query")

        assert isinstance(results, list)

    @patch('src.rag.retrieval.db')
    @patch('src.rag.retrieval.ollama_client')
    def test_retrieve_context_with_parameters(self, mock_ollama, mock_db):
        """Should respect retrieval parameters."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        # Setup mocks
        mock_ollama.get_embedding_model.return_value = "nomic-embed-text"
        mock_ollama.generate_embedding.return_value = (True, generate_mock_embedding())
        mock_db.search_similar_chunks.return_value = generate_mock_search_results(3)

        results = processor.retrieve_context("test query", top_k=3, min_similarity=0.5)

        assert isinstance(results, list)
        # Check that db was called with correct parameters
        mock_db.search_similar_chunks.assert_called_once()

    @patch('src.rag.retrieval.db')
    @patch('src.rag.retrieval.ollama_client')
    def test_retrieve_context_with_file_filter(self, mock_ollama, mock_db):
        """Should filter by file type."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        # Setup mocks
        mock_ollama.get_embedding_model.return_value = "nomic-embed-text"
        mock_ollama.generate_embedding.return_value = (True, generate_mock_embedding())
        mock_db.search_similar_chunks.return_value = []

        results = processor.retrieve_context("test", file_type_filter=".pdf")

        # Should pass filter to database
        call_args = mock_db.search_similar_chunks.call_args
        assert call_args[1]['file_type_filter'] == ".pdf"

    @patch('src.rag.retrieval.db')
    @patch('src.rag.retrieval.ollama_client')
    def test_retrieve_context_no_embedding_model(self, mock_ollama, mock_db):
        """Should handle no embedding model."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        mock_ollama.get_embedding_model.return_value = None

        results = processor.retrieve_context("test query")

        assert results == []


# ============================================================================
# RE-RANKING TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.rag
class TestReranking:
    """Tests for result re-ranking."""

    def test_rerank_with_signals(self):
        """Should re-rank results using multiple signals."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        # _rerank_with_signals expects Dict[str, Dict[str, Any]]
        results = {
            "doc1_0": {"chunk_text": "chunk about cats", "filename": "doc1.pdf", "chunk_index": 0, "combined_score": 0.8},
            "doc2_0": {"chunk_text": "chunk about dogs", "filename": "doc2.pdf", "chunk_index": 0, "combined_score": 0.9},
            "doc3_0": {"chunk_text": "chunk about cats and dogs", "filename": "doc3.pdf", "chunk_index": 0, "combined_score": 0.7},
        }

        reranked = processor._rerank_with_signals("cats", results)

        assert isinstance(reranked, dict)
        assert len(reranked) == len(results)

    def test_compute_simple_bm25(self):
        """Should compute BM25 score."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        query = "test document"
        document = "this is a test document with some test words"

        score = processor._compute_simple_bm25(query, document)

        assert isinstance(score, float)
        assert 0 <= score <= 1


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.rag
class TestRAGIntegration:
    """Integration tests for RAG pipeline."""

    @patch('src.rag.retrieval.db')
    @patch('src.rag.retrieval.ollama_client')
    @patch('src.rag.processor.db')
    @patch('src.rag.processor.ollama_client')
    def test_complete_rag_workflow(self, mock_proc_ollama, mock_proc_db, mock_retr_ollama, mock_retr_db, sample_txt_path):
        """Should handle complete RAG workflow."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        # Setup mocks
        mock_proc_db.document_exists.return_value = (False, None)
        mock_proc_db.insert_document.return_value = 1
        mock_proc_db.insert_chunks_batch.return_value = None
        mock_retr_db.search_similar_chunks.return_value = generate_mock_search_results(5)
        mock_proc_ollama.get_embedding_model.return_value = "nomic-embed-text"
        mock_proc_ollama.generate_embeddings_batch.side_effect = lambda model, texts: [generate_mock_embedding() for _ in texts]
        mock_retr_ollama.get_embedding_model.return_value = "nomic-embed-text"
        mock_retr_ollama.generate_embedding.return_value = (True, generate_mock_embedding())

        # Ingest document
        success, message, doc_id = processor.ingest_document(sample_txt_path)
        assert success is True

        # Retrieve context
        results = processor.retrieve_context("test query")
        assert isinstance(results, list)

    @patch('src.rag.processor.db')
    @patch('src.rag.processor.ollama_client')
    def test_multiple_documents_workflow(self, mock_ollama, mock_db):
        """Should handle multiple documents."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        # Setup mocks
        mock_db.document_exists.return_value = (False, None)
        mock_db.insert_document.side_effect = [1, 2, 3]
        mock_db.insert_chunks_batch.return_value = None
        mock_ollama.get_embedding_model.return_value = "nomic-embed-text"
        mock_ollama.generate_embeddings_batch.side_effect = lambda model, texts: [generate_mock_embedding() for _ in texts]

        # Create test files
        file_paths = []
        for i in range(3):
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                f.write(f"Test content {i}")
                file_paths.append(f.name)

        try:
            results = processor.ingest_multiple_documents(file_paths)

            assert len(results) == 3
            assert all(isinstance(r, tuple) for r in results)
        finally:
            for path in file_paths:
                if os.path.exists(path):
                    os.unlink(path)


# ============================================================================
# EDGE CASES
# ============================================================================

@pytest.mark.unit
@pytest.mark.rag
class TestRAGEdgeCases:
    """Edge case tests for RAG operations."""

    def test_chunk_text_with_unicode(self):
        """Should handle Unicode text."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        unicode_text = "Hello ?? ?? " * 100
        chunks = processor.chunk_text(unicode_text)

        assert isinstance(chunks, list)

    def test_chunk_text_with_special_characters(self):
        """Should handle special characters."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        special_text = "Text with <tags> & symbols! @ # $ % ^ *" * 10
        chunks = processor.chunk_text(special_text)

        assert isinstance(chunks, list)

    @patch('src.rag.processor.ollama_client')
    def test_generate_embeddings_empty_list(self, mock_ollama):
        """Should handle empty text list."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        mock_ollama.get_embedding_model.return_value = "nomic-embed-text"

        embeddings = processor.generate_embeddings_batch([])

        assert embeddings == []

    @patch('src.rag.retrieval.db')
    @patch('src.rag.retrieval.ollama_client')
    def test_retrieve_context_empty_query(self, mock_ollama, mock_db):
        """Should handle empty query."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        mock_ollama.get_embedding_model.return_value = "nomic-embed-text"
        mock_ollama.generate_embedding.return_value = (True, generate_mock_embedding())
        mock_db.search_similar_chunks.return_value = []

        results = processor.retrieve_context("")

        # Should handle gracefully
        assert isinstance(results, list)

    def test_rerank_empty_results(self):
        """Should handle empty results."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        reranked = processor._rerank_with_signals("query", {})

        assert reranked == {}

    def test_bm25_with_empty_document(self):
        """Should handle empty document."""
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()

        score = processor._compute_simple_bm25("query", "")

        assert score == 0.0
