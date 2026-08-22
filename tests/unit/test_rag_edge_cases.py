
"""
RAG Edge Cases and Advanced Tests
==================================

Edge cases and advanced scenarios for RAG

Author: LocalChat Team
Created: January 2025
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def retrieval_stack():
    """A retrievable database and embedder, so a query reaches the search layer.

    Without this the three retrieval tests below died on the "Database is not
    connected" guard, several layers before the query shape they name was ever
    looked at — and each sat inside `except Exception: pass`, so that never showed.
    """
    from src.rag import doc_processor
    from src.rag.cache import embedding_cache

    # The embedding cache is a module-level LRU that outlives every test. Another
    # test in the suite leaves an entry under this exact key — `sanitize_query`
    # caps at 5000 characters, so "word " * 1000 and "word " * 10000 preprocess to
    # the same 1000 words — and the hit meant generate_embedding was never called.
    # These tests passed alone and failed in the full run for that reason.
    embedding_cache.clear()

    ollama = MagicMock()
    ollama.get_embedding_model.return_value = "nomic-embed-text"
    ollama.generate_embedding.return_value = (True, [0.1] * 768)
    mock_db = MagicMock()
    mock_db.is_connected = True
    mock_db.search_similar_chunks.return_value = [
        ("chunk text", "doc.pdf", 0, 0.95, {}, 1),
    ]
    # Patched on the instance, not the module: doc_processor is a singleton that
    # bound self._db and self._ollama_client at construction, so patching
    # src.rag.retrieval.db leaves it talking to the real ones — which is how the
    # first version of this fixture still reached localhost:11434.
    with patch.object(doc_processor, "_db", mock_db),          patch.object(doc_processor, "_ollama_client", ollama):
        yield mock_db, ollama



class TestChunkingEdgeCases:
    """Test text chunking edge cases."""

    def test_chunk_with_very_small_size(self):
        """Test chunking with very small chunk size."""
        from src.rag import doc_processor

        text = "Hello world test"
        chunks = doc_processor.chunk_text(text, chunk_size=5, overlap=0)

        assert isinstance(chunks, list)

    def test_chunk_with_zero_overlap(self):
        """Test chunking with no overlap."""
        from src.rag import doc_processor

        text = "A" * 100
        chunks = doc_processor.chunk_text(text, chunk_size=20, overlap=0)

        # Should create at least one chunk
        assert len(chunks) >= 1

    def test_chunk_with_large_overlap(self):
        """Test chunking with large overlap."""
        from src.rag import doc_processor

        text = "B" * 100
        chunks = doc_processor.chunk_text(text, chunk_size=30, overlap=25)

        assert len(chunks) > 0

    def test_chunk_unicode_text(self):
        """Test chunking Unicode text."""
        from src.rag import doc_processor

        text = "Hello world " * 20
        chunks = doc_processor.chunk_text(text, chunk_size=50)

        assert all(isinstance(c, str) for c in chunks)

    def test_chunk_with_newlines(self):
        """Test chunking preserves/handles newlines."""
        from src.rag import doc_processor

        text = "Line 1\nLine 2\nLine 3\n" * 10
        chunks = doc_processor.chunk_text(text, chunk_size=50)

        assert len(chunks) > 0


class TestDocumentProcessorMethods:
    """Test DocumentProcessor methods."""

    def test_processor_has_chunk_method(self):
        """Test processor has chunk_text method."""
        from src.rag import doc_processor

        assert hasattr(doc_processor, 'chunk_text')
        assert callable(doc_processor.chunk_text)

    def test_processor_has_load_methods(self):
        """Test processor has document loading methods."""
        from src.rag import doc_processor

        assert hasattr(doc_processor, 'load_document')
        assert hasattr(doc_processor, 'load_text_file')

    def test_processor_has_ingest_method(self):
        """Test processor has ingest_document method."""
        from src.rag import doc_processor

        assert hasattr(doc_processor, 'ingest_document')
        assert callable(doc_processor.ingest_document)

    def test_processor_has_retrieve_method(self):
        """Test processor has retrieve_context method."""
        from src.rag import doc_processor

        assert hasattr(doc_processor, 'retrieve_context')
        assert callable(doc_processor.retrieve_context)


class TestFileTypeDetection:
    """Test file type detection."""

    def test_pdf_file_recognized(self):
        """Test PDF files are recognized."""
        from src.rag import doc_processor

        # PDF should be recognized even if file doesn't exist
        success, result = doc_processor.load_document("test.pdf")

        # Should attempt PDF loading (will fail on missing file)
        assert success is False

    def test_txt_file_recognized(self, tmp_path):
        """Test TXT files are recognized."""
        from src.rag import doc_processor

        file_path = tmp_path / "test.txt"
        file_path.write_text("Content")

        success, content = doc_processor.load_document(str(file_path))

        assert success is True

    def test_docx_file_recognized(self):
        """Test DOCX files are recognized."""
        from src.rag import doc_processor

        success, result = doc_processor.load_document("test.docx")

        # Should attempt DOCX loading
        assert success is False  # Fails on missing file

    def test_md_file_treated_as_text(self, tmp_path):
        """Test Markdown files treated as text."""
        from src.rag import doc_processor

        file_path = tmp_path / "test.md"
        file_path.write_text("# Header\nContent")

        success, content = doc_processor.load_document(str(file_path))

        assert success is True
        assert "Header" in content


class TestIngestionValidation:
    """Test document ingestion validation."""

    def test_ingest_rejects_empty_path(self):
        """Test ingestion rejects empty file path."""
        from src.rag import doc_processor

        success, message, doc_id = doc_processor.ingest_document("")

        assert success is False
        assert doc_id is None or doc_id == 0

    def test_ingest_rejects_nonexistent_file(self):
        """Test ingestion rejects nonexistent file."""
        from src.rag import doc_processor

        success, msg, doc_id = doc_processor.ingest_document("/nonexistent/file.txt")

        assert success is False

    def test_ingest_rejects_directory(self, tmp_path):
        """Test ingestion rejects directory."""
        from src.rag import doc_processor

        success, msg, doc_id = doc_processor.ingest_document(str(tmp_path))

        assert success is False


class TestRetrievalEdgeCases:
    """Test context retrieval edge cases."""

    def test_retrieve_with_none_query(self):
        """Test retrieval handles None query."""
        from src.rag import doc_processor

        try:
            result = doc_processor.retrieve_context(None)
            assert isinstance(result, (str, list))
        except (TypeError, AttributeError):
            pass  # Acceptable to reject None

    def test_a_very_long_query_reaches_the_embedder_whole(self, retrieval_stack):
        """1000 words in, 1000 words embedded.

        `sanitize_query` caps a query at 5000 characters, so this one sits exactly
        on that boundary. Silent truncation would change which chunks come back
        with nothing in the answer saying the question had been shortened.
        """
        from src.rag import doc_processor

        _, ollama = retrieval_stack
        doc_processor.retrieve_context("word " * 1000)

        embedded = ollama.generate_embedding.call_args[0][1]
        assert len(embedded.split()) == 1000

    def test_special_characters_are_stripped_before_the_lexical_arm(self, retrieval_stack):
        """`<>&"'` do not survive `_preprocess_query`, by design — the lexical arm
        builds a tsquery from this text, and that is where such characters break.

        Asserted as the exact resulting string. The version this replaces checked
        `isinstance(result, (str, list))` inside `except Exception: pass`, which
        would have held just as well if the query had arrived unfiltered.
        """
        from src.rag import doc_processor

        mock_db, _ = retrieval_stack
        doc_processor.retrieve_context("test <>&\"' query")

        assert mock_db.search_lexical_chunks.call_args[0][0] == "test query"


class TestModuleConstants:
    """Test module-level constants and flags."""

    def test_pdf_available_is_boolean(self):
        """Test PDF_AVAILABLE flag is boolean."""
        from src.rag import PDF_AVAILABLE

        assert isinstance(PDF_AVAILABLE, bool)

    def test_docx_available_is_boolean(self):
        """Test DOCX_AVAILABLE flag is boolean."""
        from src.rag import DOCX_AVAILABLE

        assert isinstance(DOCX_AVAILABLE, bool)

    def test_monitoring_available_is_boolean(self):
        """Test MONITORING_AVAILABLE flag is boolean."""
        from src.rag import MONITORING_AVAILABLE

        assert isinstance(MONITORING_AVAILABLE, bool)

    def test_logger_exists(self):
        """Test logger is initialized."""
        from src.rag import logger

        assert logger is not None
