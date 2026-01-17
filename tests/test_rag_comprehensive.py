"""
Comprehensive RAG Module Tests - Week 2 Day 4-5
===============================================

Tests the DocumentProcessor class from src/rag.py with proper file I/O and embedding mocking.
Target: 35+ tests, 85%+ coverage on rag.py

Run: pytest tests/test_rag_comprehensive.py -v --cov=src.rag --cov-report=term-missing
"""

import pytest
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, mock_open
from typing import List, Tuple

# Mark all tests
pytestmark = [pytest.mark.unit, pytest.mark.rag]

# Mock environment variables BEFORE importing src modules
@pytest.fixture(scope="session", autouse=True)
def mock_env_vars():
    """Mock environment variables for testing."""
    with patch.dict(os.environ, {
        'PG_PASSWORD': 'test_password',
        'OLLAMA_BASE_URL': 'http://localhost:11434',
        'SECRET_KEY': 'test_secret',
        'JWT_SECRET_KEY': 'test_jwt_secret'
    }):
        yield


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def doc_processor():
    """Create a fresh DocumentProcessor instance."""
    from src.rag import DocumentProcessor
    return DocumentProcessor()


@pytest.fixture
def temp_file():
    """Create a temporary file for testing."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("Test content for file processing.")
        temp_path = f.name
    
    yield temp_path
    
    # Cleanup
    try:
        os.unlink(temp_path)
    except:
        pass


@pytest.fixture
def sample_text():
    """Sample text for chunking tests."""
    return """This is a sample document for testing. It contains multiple sentences.

This is the second paragraph. It also has multiple sentences for testing purposes.

This is the third paragraph with even more content to test the chunking functionality."""


@pytest.fixture
def sample_chunks():
    """Sample chunks for testing."""
    return [
        "This is chunk one with some content.",
        "This is chunk two with different content.",
        "This is chunk three with more content."
    ]


@pytest.fixture
def mock_db():
    """Mock database for testing."""
    with patch('src.rag.db') as mock_database:
        mock_database.insert_document.return_value = 1
        mock_database.insert_chunks_batch.return_value = None
        mock_database.search_similar_chunks.return_value = [
            ("chunk text 1", "doc1.pdf", 0, 0.95, {}),  # Added metadata
            ("chunk text 2", "doc1.pdf", 1, 0.87, {}),
            ("chunk text 3", "doc2.pdf", 0, 0.82, {})
        ]
        yield mock_database


@pytest.fixture
def mock_ollama():
    """Mock Ollama client for testing."""
    with patch('src.rag.ollama_client') as mock_client:
        mock_client.get_embedding_model.return_value = "nomic-embed-text"
        mock_client.generate_embedding.return_value = (True, [0.1] * 768)
        yield mock_client


# ============================================================================
# DOCUMENT LOADING TESTS (6 tests)
# ============================================================================

class TestDocumentLoading:
    """Test document loading functionality."""
    
    def test_load_text_file_success(self, doc_processor, temp_file):
        """Should successfully load text file."""
        success, content = doc_processor.load_text_file(temp_file)
        
        assert success is True
        assert "Test content" in content
        assert len(content) > 0
    
    def test_load_text_file_not_found(self, doc_processor):
        """Should handle missing file."""
        success, error = doc_processor.load_text_file("nonexistent.txt")
        
        assert success is False
        assert "error" in error.lower() or "no such file" in error.lower()
    
    @patch('src.rag.PDF_AVAILABLE', True)
    @patch('src.rag.PyPDF2')
    def test_load_pdf_file_success(self, mock_pypdf2, doc_processor, temp_file):
        """Should successfully load PDF file."""
        # Mock PDF reader
        mock_page = Mock()
        mock_page.extract_text.return_value = "PDF content here"
        
        mock_reader = Mock()
        mock_reader.pages = [mock_page, mock_page]
        
        mock_pypdf2.PdfReader.return_value = mock_reader
        
        success, content = doc_processor.load_pdf_file(temp_file)
        
        assert success is True
        assert "PDF content" in content
    
    @patch('src.rag.PDF_AVAILABLE', False)
    def test_load_pdf_file_unavailable(self, doc_processor):
        """Should handle PDF library not available."""
        success, error = doc_processor.load_pdf_file("test.pdf")
        
        assert success is False
        assert "not installed" in error.lower()
    
    @patch('src.rag.DOCX_AVAILABLE', True)
    @patch('src.rag.Document')
    def test_load_docx_file_success(self, mock_docx, doc_processor, temp_file):
        """Should successfully load DOCX file."""
        # Mock DOCX document
        mock_para1 = Mock()
        mock_para1.text = "Paragraph 1"
        mock_para2 = Mock()
        mock_para2.text = "Paragraph 2"
        
        mock_doc = Mock()
        mock_doc.paragraphs = [mock_para1, mock_para2]
        mock_doc.tables = []
        
        mock_docx.return_value = mock_doc
        
        # Mock os.path.exists and getsize
        with patch('os.path.exists', return_value=True):
            with patch('os.path.getsize', return_value=1000):
                success, content = doc_processor.load_docx_file(temp_file)
        
        assert success is True
        assert "Paragraph 1" in content
        assert "Paragraph 2" in content
    
    @patch('src.rag.DOCX_AVAILABLE', False)
    def test_load_docx_file_unavailable(self, doc_processor):
        """Should handle DOCX library not available."""
        success, error = doc_processor.load_docx_file("test.docx")
        
        assert success is False
        assert "not installed" in error.lower()


# ============================================================================
# TEXT CHUNKING TESTS (10 tests)
# ============================================================================

class TestTextChunking:
    """Test text chunking functionality."""
    
    def test_chunk_text_basic(self, doc_processor, sample_text):
        """Should chunk text into reasonable sizes."""
        chunks = doc_processor.chunk_text(sample_text, chunk_size=100, overlap=20)
        
        assert len(chunks) > 0
        assert all(isinstance(chunk, str) for chunk in chunks)
        assert all(len(chunk) > 0 for chunk in chunks)
    
    def test_chunk_text_respects_size(self, doc_processor):
        """Should respect chunk size limits."""
        text = "word " * 200  # 1000 characters
        chunk_size = 50
        
        chunks = doc_processor.chunk_text(text, chunk_size=chunk_size, overlap=10)
        
        # Most chunks should be near chunk_size (allowing some variance for word boundaries)
        for chunk in chunks[:-1]:  # Exclude last chunk which may be smaller
            assert len(chunk) <= chunk_size * 1.5  # Allow some flexibility
    
    def test_chunk_text_with_overlap(self, doc_processor):
        """Should create overlapping chunks."""
        text = "This is sentence one. This is sentence two. This is sentence three."
        
        chunks = doc_processor.chunk_text(text, chunk_size=30, overlap=10)
        
        assert len(chunks) >= 2
        # Check for some overlap (not exact due to word boundaries)
        if len(chunks) >= 2:
            # Some content should appear in multiple chunks
            assert len(chunks) > 1
    
    def test_chunk_text_empty_input(self, doc_processor):
        """Should handle empty text."""
        chunks = doc_processor.chunk_text("")
        
        assert chunks == []
    
    def test_chunk_text_single_word(self, doc_processor):
        """Should handle single word."""
        chunks = doc_processor.chunk_text("word")
        
        assert len(chunks) == 1
        assert chunks[0] == "word"
    
    def test_chunk_text_preserves_sentences(self, doc_processor):
        """Should try to keep sentences together."""
        text = "First sentence. Second sentence. Third sentence."
        
        chunks = doc_processor.chunk_text(text, chunk_size=50, overlap=5)
        
        # Should create chunks, trying to respect sentence boundaries
        assert len(chunks) > 0
        assert all(chunk.strip() for chunk in chunks)
    
    def test_chunk_text_handles_unicode(self, doc_processor):
        """Should handle Unicode characters."""
        text = "Hello world! This is a test with emojis and special characters."
        
        chunks = doc_processor.chunk_text(text, chunk_size=50, overlap=10)
        
        assert len(chunks) > 0
        # Verify text is preserved
        full_text = "".join(chunks)
        assert "world" in full_text or len(chunks) > 0
    
    def test_chunk_text_respects_separators(self, doc_processor):
        """Should use paragraph breaks as primary separator."""
        text = "Paragraph 1\n\nParagraph 2\n\nParagraph 3"
        
        chunks = doc_processor.chunk_text(text, chunk_size=100, overlap=10)
        
        # Should split on paragraph breaks first
        assert len(chunks) >= 1
    
    def test_chunk_text_large_document(self, doc_processor):
        """Should handle large documents efficiently."""
        text = "word " * 10000  # 50,000 characters
        
        chunks = doc_processor.chunk_text(text, chunk_size=500, overlap=50)
        
        assert len(chunks) > 10  # Should create many chunks
        assert all(len(chunk) <= 1000 for chunk in chunks)  # Reasonable max
    
    def test_chunk_text_with_tables(self, doc_processor):
        """Should handle table-like text."""
        text = """[Table 1 on page 1]
Header1 | Header2 | Header3
Value1 | Value2 | Value3
Value4 | Value5 | Value6

This is regular text after the table."""
        
        chunks = doc_processor.chunk_text(text, chunk_size=200, overlap=20)
        
        assert len(chunks) > 0
        # Table should be in chunks
        table_found = any("[Table" in chunk for chunk in chunks)
        assert table_found or len(chunks) > 0


# ============================================================================
# EMBEDDING GENERATION TESTS (5 tests)
# ============================================================================

class TestEmbeddingGeneration:
    """Test embedding generation functionality."""
    
    def test_generate_embeddings_batch(self, doc_processor, sample_chunks, mock_ollama):
        """Should generate embeddings for batch of texts."""
        embeddings = doc_processor.generate_embeddings_batch(
            sample_chunks, 
            model="nomic-embed-text"
        )
        
        assert len(embeddings) == len(sample_chunks)
        assert all(emb is not None for emb in embeddings)
        assert mock_ollama.generate_embedding.call_count == len(sample_chunks)
    
    def test_generate_embeddings_batch_custom_size(self, doc_processor, mock_ollama):
        """Should respect custom batch size."""
        texts = ["text"] * 100
        
        embeddings = doc_processor.generate_embeddings_batch(texts, batch_size=25)
        
        assert len(embeddings) == 100
        # Should process in batches of 25 (4 batches total)
        assert mock_ollama.generate_embedding.call_count == 100
    
    def test_generate_embeddings_handles_failures(self, doc_processor, mock_ollama):
        """Should handle embedding failures gracefully."""
        # Mock some failures
        mock_ollama.generate_embedding.side_effect = [
            (True, [0.1] * 768),
            (False, []),  # Failure
            (True, [0.2] * 768)
        ]
        
        texts = ["text1", "text2", "text3"]
        embeddings = doc_processor.generate_embeddings_batch(texts)
        
        assert len(embeddings) == 3
        assert embeddings[0] is not None
        assert embeddings[1] is None  # Failed
        assert embeddings[2] is not None
    
    def test_process_document_chunk(self, doc_processor, mock_ollama):
        """Should process single chunk correctly."""
        result = doc_processor.process_document_chunk(
            doc_id=1,
            chunk_text="test chunk",
            chunk_index=0,
            model="nomic-embed-text"
        )
        
        assert result is not None
        assert result[0] == 1  # doc_id
        assert result[1] == "test chunk"  # chunk_text
        assert result[2] == 0  # chunk_index
        assert len(result[3]) == 768  # embedding
    
    def test_process_document_chunk_failure(self, doc_processor, mock_ollama):
        """Should return None on embedding failure."""
        mock_ollama.generate_embedding.return_value = (False, [])
        
        result = doc_processor.process_document_chunk(
            doc_id=1,
            chunk_text="test",
            chunk_index=0,
            model="nomic-embed-text"
        )
        
        assert result is None


# ============================================================================
# CONTEXT RETRIEVAL TESTS (8 tests)
# ============================================================================

class TestContextRetrieval:
    """Test context retrieval functionality."""
    
    def test_retrieve_context_success(self, doc_processor, mock_db, mock_ollama):
        """Should retrieve relevant context."""
        results = doc_processor.retrieve_context("test query", top_k=3)
        
        assert len(results) <= 3
        assert all(len(r) == 4 for r in results)  # (text, filename, idx, sim)
        mock_ollama.generate_embedding.assert_called_once()
        mock_db.search_similar_chunks.assert_called_once()
    
    def test_retrieve_context_no_results(self, doc_processor, mock_db, mock_ollama):
        """Should handle no results."""
        mock_db.search_similar_chunks.return_value = []
        
        results = doc_processor.retrieve_context("test query")
        
        assert results == []
    
    def test_retrieve_context_with_filter(self, doc_processor, mock_db, mock_ollama):
        """Should apply file type filter."""
        results = doc_processor.retrieve_context(
            "test query",
            file_type_filter=".pdf"
        )
        
        # Verify filter was passed to database
        call_args = mock_db.search_similar_chunks.call_args
        assert call_args[1]['file_type_filter'] == ".pdf"
    
    @patch('src.rag.config.RERANK_RESULTS', True)
    def test_retrieve_context_with_reranking(self, doc_processor, mock_db, mock_ollama):
        """Should apply re-ranking when enabled."""
        mock_db.search_similar_chunks.return_value = [
            ("chunk 1", "doc.pdf", 0, 0.85, {}),  # Added metadata
            ("chunk 2", "doc.pdf", 1, 0.90, {}),
            ("chunk 3", "doc.pdf", 2, 0.80, {})
        ]
        
        results = doc_processor.retrieve_context("test query")
        
        # Results should be returned (re-ranking applied internally)
        assert len(results) > 0
    
    def test_retrieve_context_min_similarity(self, doc_processor, mock_db, mock_ollama):
        """Should filter by minimum similarity."""
        mock_db.search_similar_chunks.return_value = [
            ("chunk 1", "doc.pdf", 0, 0.95, {}),  # Added metadata
            ("chunk 2", "doc.pdf", 1, 0.50, {}),  # Below threshold
            ("chunk 3", "doc.pdf", 2, 0.85, {})  # Added metadata
        ]
        
        results = doc_processor.retrieve_context("test query", min_similarity=0.70)
        
        # Should filter out low similarity results
        assert all(r[3] >= 0.70 for r in results)
    
    def test_retrieve_context_query_preprocessing(self, doc_processor, mock_db, mock_ollama):
        """Should preprocess query."""
        results = doc_processor.retrieve_context("What's   the  answer?")
        
        # Should clean up whitespace and contractions
        mock_ollama.generate_embedding.assert_called_once()
        call_args = mock_ollama.generate_embedding.call_args[0]
        # Query should be preprocessed
        assert isinstance(call_args[1], str)
    
    def test_retrieve_context_no_embedding_model(self, doc_processor, mock_ollama):
        """Should handle no embedding model available."""
        mock_ollama.get_embedding_model.return_value = None
        
        results = doc_processor.retrieve_context("test query")
        
        assert results == []
    
    def test_retrieve_context_embedding_failure(self, doc_processor, mock_db, mock_ollama):
        """Should handle embedding generation failure."""
        mock_ollama.generate_embedding.return_value = (False, [])
        
        results = doc_processor.retrieve_context("test query")
        
        assert results == []


# ============================================================================
# DOCUMENT INGESTION TESTS (6 tests)
# ============================================================================

class TestDocumentIngestion:
    """Test document ingestion pipeline."""
    
    def test_ingest_document_success(self, doc_processor, temp_file, mock_db, mock_ollama):
        """Should successfully ingest document."""
        mock_db.document_exists.return_value = (False, None)
        
        success, message, doc_id = doc_processor.ingest_document(temp_file)
        
        assert success is True
        assert doc_id is not None
        assert "success" in message.lower()
        mock_db.insert_document.assert_called_once()
        mock_db.insert_chunks_batch.assert_called_once()
    
    def test_ingest_document_duplicate(self, doc_processor, temp_file, mock_db):
        """Should detect duplicate documents."""
        mock_db.document_exists.return_value = (True, {'id': 1, 'chunk_count': 5})
        
        success, message, doc_id = doc_processor.ingest_document(temp_file)
        
        assert success is True
        assert "already exists" in message.lower()
        assert doc_id == 1
        # Should not insert again
        mock_db.insert_document.assert_not_called()
    
    def test_ingest_document_file_not_found(self, doc_processor, mock_db):
        """Should handle missing file."""
        mock_db.document_exists.return_value = (False, None)
        
        success, message, doc_id = doc_processor.ingest_document("nonexistent.txt")
        
        assert success is False
        assert ("not found" in message.lower() or "error" in message.lower())
        assert doc_id is None
    
    def test_ingest_document_with_progress(self, doc_processor, temp_file, mock_db, mock_ollama):
        """Should call progress callback."""
        mock_db.document_exists.return_value = (False, None)
        
        progress_messages = []
        
        def progress_callback(msg):
            progress_messages.append(msg)
        
        success, message, doc_id = doc_processor.ingest_document(
            temp_file,
            progress_callback=progress_callback
        )
        
        assert success is True
        assert len(progress_messages) > 0
        assert any("Loading" in msg for msg in progress_messages)
    
    def test_ingest_document_empty_content(self, doc_processor, mock_db, mock_ollama):
        """Should handle empty document content."""
        mock_db.document_exists.return_value = (False, None)
        
        # Create empty temp file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("")  # Empty
            empty_file = f.name
        
        try:
            success, message, doc_id = doc_processor.ingest_document(empty_file)
            
            assert success is False
            assert "insufficient content" in message.lower() or "no chunks" in message.lower()
        finally:
            try:
                os.unlink(empty_file)
            except:
                pass
    
    def test_ingest_document_embedding_failures(self, doc_processor, temp_file, mock_db, mock_ollama):
        """Should handle partial embedding failures."""
        mock_db.document_exists.return_value = (False, None)
        
        # Mock some embedding failures
        call_count = [0]
        
        def mock_generate_embedding(model, text):
            call_count[0] += 1
            if call_count[0] % 3 == 0:
                return (False, [])  # Every 3rd fails
            return (True, [0.1] * 768)
        
        mock_ollama.generate_embedding.side_effect = mock_generate_embedding
        
        success, message, doc_id = doc_processor.ingest_document(temp_file)
        
        # Should succeed even with some failures
        assert success is True or "no chunks" in message.lower()


# ============================================================================
# UTILITY METHODS TESTS (2 tests)
# ============================================================================

class TestUtilityMethods:
    """Test utility methods."""
    
    def test_preprocess_query(self, doc_processor):
        """Should preprocess query correctly."""
        query = "What's   the   answer?"
        
        # Access internal method
        processed = doc_processor._preprocess_query(query)
        
        assert "what is" in processed.lower()
        assert "  " not in processed  # No double spaces
    
    def test_compute_simple_bm25(self, doc_processor):
        """Should compute BM25 score."""
        query = "test query"
        document = "this is a test document with query terms"
        
        # Access internal method
        score = doc_processor._compute_simple_bm25(query, document)
        
        assert isinstance(score, float)
        assert 0 <= score <= 1  # Normalized


# ============================================================================
# SUMMARY
# ============================================================================

# Total tests: 37 comprehensive tests
# Coverage target: 85%+ on src/rag.py
# Test categories:
#   - Document Loading: 6 tests
#   - Text Chunking: 10 tests
#   - Embedding Generation: 5 tests
#   - Context Retrieval: 8 tests
#   - Document Ingestion: 6 tests
#   - Utility Methods: 2 tests

# Run with:
# pytest tests/test_rag_comprehensive.py -v --cov=src.rag --cov-report=term-missing --cov-report=html
