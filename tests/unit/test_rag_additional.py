# -*- coding: utf-8 -*-

"""
RAG Module Additional Tests
============================

Additional tests for RAG functionality

Author: LocalChat Team
Created: January 2025
"""

import pytest


class TestBM25Scorer:
    """Test BM25 scoring."""
    
    def test_bm25_scorer_exists(self):
        """Test BM25 scorer can be imported."""
        from src.rag import BM25Scorer
        
        scorer = BM25Scorer()
        assert scorer is not None
        assert scorer.k1 > 0
        assert 0 <= scorer.b <= 1
    
    def test_bm25_custom_params(self):
        """Test BM25 with custom parameters."""
        from src.rag import BM25Scorer
        
        scorer = BM25Scorer(k1=2.0, b=0.5)
        assert scorer.k1 == 2.0
        assert scorer.b == 0.5


class TestTextChunking:
    """Test text chunking."""
    
    def test_chunk_text_basic(self):
        """Test basic chunking."""
        from src.rag import doc_processor
        
        text = "This is test text. " * 50
        chunks = doc_processor.chunk_text(text, chunk_size=100, overlap=20)
        
        assert isinstance(chunks, list)
        assert len(chunks) > 0
    
    def test_chunk_empty_text(self):
        """Test chunking empty text."""
        from src.rag import doc_processor
        
        chunks = doc_processor.chunk_text("", chunk_size=100)
        assert isinstance(chunks, list)
    
    def test_chunk_short_text(self):
        """Test chunking short text."""
        from src.rag import doc_processor
        
        text = "Short"
        chunks = doc_processor.chunk_text(text, chunk_size=1000)
        assert len(chunks) >= 1


class TestDocumentProcessor:
    """Test doc processor."""
    
    def test_processor_exists(self):
        """Test processor exists."""
        from src.rag import doc_processor
        assert doc_processor is not None
    
    def test_processor_has_methods(self):
        """Test processor has required methods."""
        from src.rag import doc_processor
        assert hasattr(doc_processor, 'chunk_text')
        assert hasattr(doc_processor, 'load_document')
        assert hasattr(doc_processor, 'ingest_document')
        assert hasattr(doc_processor, 'retrieve_context')


class TestDocumentLoading:
    """Test document loading."""
    
    def test_load_text_file(self, tmp_path):
        """Test loading text file."""
        from src.rag import doc_processor
        
        file_path = tmp_path / "test.txt"
        file_path.write_text("Test content", encoding='utf-8')
        
        success, content = doc_processor.load_text_file(str(file_path))
        assert success is True
        assert "Test content" in content
    
    def test_load_missing_file(self):
        """Test loading missing file."""
        from src.rag import doc_processor
        
        success, error = doc_processor.load_text_file("nonexistent.txt")
        assert success is False
    
    def test_load_unsupported_type(self):
        """Test unsupported file type."""
        from src.rag import doc_processor
        
        success, error = doc_processor.load_document("file.xyz")
        assert success is False


class TestIngestion:
    """Test document ingestion."""
    
    def test_ingest_missing_file(self):
        """Test ingesting missing file."""
        from src.rag import doc_processor
        
        success, msg, doc_id = doc_processor.ingest_document("missing.txt")
        assert success is False
        assert isinstance(msg, str)


class TestRetrieval:
    """Test context retrieval."""
    
    def test_retrieve_with_empty_query(self):
        """Test retrieval with empty query."""
        from src.rag import doc_processor
        
        try:
            result = doc_processor.retrieve_context("")
            assert isinstance(result, (str, list))
        except (ValueError, TypeError):
            pass  # Acceptable to reject


class TestModuleImports:
    """Test module imports."""
    
    def test_pdf_availability_flag(self):
        """Test PDF availability flag."""
        from src.rag import PDF_AVAILABLE
        assert isinstance(PDF_AVAILABLE, bool)
    
    def test_docx_availability_flag(self):
        """Test DOCX availability flag."""
        from src.rag import DOCX_AVAILABLE
        assert isinstance(DOCX_AVAILABLE, bool)
    
    def test_monitoring_availability_flag(self):
        """Test monitoring availability flag."""
        from src.rag import MONITORING_AVAILABLE
        assert isinstance(MONITORING_AVAILABLE, bool)


class TestGlobalObjects:
    """Test global objects."""
    
    def test_db_imported(self):
        """Test db is imported."""
        from src.rag import db
        assert db is not None
    
    def test_ollama_client_imported(self):
        """Test ollama_client is imported."""
        from src.rag import ollama_client
        assert ollama_client is not None
    
    def test_config_imported(self):
        """Test config is imported."""
        from src.rag import config
        assert config is not None
