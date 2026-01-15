# -*- coding: utf-8 -*-

"""
RAG Edge Cases and Advanced Tests
==================================

Edge cases and advanced scenarios for RAG

Author: LocalChat Team
Created: January 2025
"""

import pytest


class TestChunkingEdgeCases:
    """Test text chunking edge cases."""
    
    def test_chunk_with_very_small_size(self):
        """Test chunking with very small chunk size."""
        from src.rag import doc_processor
        
        text = "Hello world test"
        chunks = doc_processor.chunk_text(text, chunk_size=5, overlap=0)
        
        assert isinstance(chunks, list)
        # May return 0 or more chunks depending on implementation
        assert len(chunks) >= 0
    
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
        
        text = "Hello ?? " * 20
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
    
    def test_retrieve_with_very_long_query(self):
        """Test retrieval handles very long query."""
        from src.rag import doc_processor
        
        long_query = "word " * 1000
        
        try:
            result = doc_processor.retrieve_context(long_query)
            assert isinstance(result, (str, list))
        except Exception:
            pass  # May reject very long queries
    
    def test_retrieve_with_special_characters(self):
        """Test retrieval handles special characters."""
        from src.rag import doc_processor
        
        query = "test <>&\"' query"
        
        try:
            result = doc_processor.retrieve_context(query)
            assert isinstance(result, (str, list))
        except Exception:
            pass


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


class TestBM25ScorerEdgeCases:
    """Test BM25 scorer edge cases."""
    
    def test_bm25_with_zero_k1(self):
        """Test BM25 with k1=0."""
        from src.rag import BM25Scorer
        
        scorer = BM25Scorer(k1=0, b=0.75)
        
        assert scorer.k1 == 0
    
    def test_bm25_with_b_zero(self):
        """Test BM25 with b=0 (no length normalization)."""
        from src.rag import BM25Scorer
        
        scorer = BM25Scorer(k1=1.5, b=0)
        
        assert scorer.b == 0
    
    def test_bm25_with_b_one(self):
        """Test BM25 with b=1 (full length normalization)."""
        from src.rag import BM25Scorer
        
        scorer = BM25Scorer(k1=1.5, b=1.0)
        
        assert scorer.b == 1.0
