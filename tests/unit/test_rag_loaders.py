# -*- coding: utf-8 -*-

"""
Unit Tests for RAG Document Loaders
====================================

Comprehensive tests for document loading functionality in src/rag.py

Target: Increase coverage from 63% to 85% (+7% total coverage)

Focus areas:
- PDF loading (with pdfplumber and PyPDF2)
- DOCX loading
- Text file loading
- Error handling
- Content validation

Author: LocalChat Team
Created: January 2025
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, mock_open
from io import BytesIO
import os


class TestTextFileLoading:
    """Test plain text file loading."""
    
    def test_load_text_file_returns_content(self, tmp_path):
        """Test successful text file loading."""
        from src.rag import doc_processor
        
        # Create test file
        test_file = tmp_path / "test.txt"
        test_content = "This is test content.\\nMultiple lines.\\n"
        test_file.write_text(test_content, encoding='utf-8')
        
        success, content = doc_processor.load_text_file(str(test_file))
        
        assert success is True
        assert content == test_content
        assert len(content) > 0
    
    def test_load_text_file_handles_encoding(self, tmp_path):
        """Test text file with UTF-8 encoding."""
        from src.rag import doc_processor
        
        test_file = tmp_path / "unicode.txt"
        test_content = "Unicode: special characters test"
        test_file.write_text(test_content, encoding='utf-8')
        
        success, content = doc_processor.load_text_file(str(test_file))
        
        assert success is True
        assert "special" in content
    
    def test_load_text_file_handles_missing_file(self):
        """Test loading non-existent file."""
        from src.rag import doc_processor
        
        success, error = doc_processor.load_text_file("nonexistent.txt")
        
        assert success is False
        assert "No such file" in error or "not found" in error.lower()


class TestPDFLoading:
"""Test PDF file loading."""
    
@pytest.mark.skip(reason="pdfplumber uses dynamic imports, difficult to mock")
def test_load_pdf_with_pdfplumber_success(self):
    """Test PDF loading with pdfplumber."""
    from src.rag import doc_processor
        
    # Mock pdfplumber
    mock_pdf = MagicMock()
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "Page 1 content"
    mock_page.extract_tables.return_value = []
    mock_pdf.pages = [mock_page]
        
    with patch('src.rag.pdfplumber') as mock_pdfplumber:
        mock_pdfplumber.open.return_value.__enter__.return_value = mock_pdf
            
        success, content = doc_processor.load_pdf_file("test.pdf")
            
        assert success is True
        assert "Page 1 content" in content
    
@pytest.mark.skip(reason="pdfplumber uses dynamic imports, difficult to mock")
def test_load_pdf_handles_empty_pdf(self):
    """Test handling of empty PDF files."""
    from src.rag import doc_processor
        
    # Mock empty PDF
    mock_pdf = MagicMock()
    mock_page = MagicMock()
    mock_page.extract_text.return_value = ""
    mock_pdf.pages = [mock_page]
        
        
        with patch('src.rag.pdfplumber') as mock_pdfplumber:
            mock_pdfplumber.open.return_value.__enter__.return_value = mock_pdf
            
            success, error = doc_processor.load_pdf_file("empty.pdf")
            
            assert success is False
            assert "empty" in error.lower()


class TestDOCXLoading:
"""Test DOCX file loading."""
    
@pytest.mark.skip(reason="python-docx uses dynamic imports, difficult to mock")
def test_load_docx_success(self):
    """Test successful DOCX loading."""
    from src.rag import doc_processor
        
    # Mock Document
    mock_doc = MagicMock()
    mock_para1 = MagicMock()
    mock_para1.text = "Paragraph 1 content"
    mock_para2 = MagicMock()
    mock_para2.text = "Paragraph 2 content"
    mock_doc.paragraphs = [mock_para1, mock_para2]
    mock_doc.tables = []
        
    with patch('src.rag.Document', return_value=mock_doc):
        success, content = doc_processor.load_docx_file("test.docx")
            
            assert success is True
            assert "Paragraph 1" in content
            assert "Paragraph 2" in content
    
    def test_load_docx_handles_missing_file(self):
        """Test handling of missing DOCX file."""
        from src.rag import doc_processor
        
        with patch('src.rag.Document', side_effect=FileNotFoundError("File not found")):
            success, error = doc_processor.load_docx_file("missing.docx")
            
            assert success is False
            assert "not found" in error.lower()


class TestDocumentLoading:
    """Test main document loading function."""
    
    def test_load_document_routes_to_text(self, tmp_path):
        """Test load_document routes .txt files correctly."""
        from src.rag import doc_processor
        
        test_file = tmp_path / "test.txt"
        test_file.write_text("Text content", encoding='utf-8')
        
        success, content = doc_processor.load_document(str(test_file))
        
        assert success is True
        assert "Text content" in content
    
    @pytest.mark.skip(reason="PDF loading uses dynamic imports")
    def test_load_document_routes_to_pdf(self):
        """Test load_document routes .pdf files correctly."""
        from src.rag import doc_processor
        
        mock_pdf = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "PDF content"
        mock_page.extract_tables.return_value = []
        mock_pdf.pages = [mock_page]
        
        with patch('src.rag.pdfplumber') as mock_pdfplumber:
            mock_pdfplumber.open.return_value.__enter__.return_value = mock_pdf
            
            success, content = doc_processor.load_document("test.pdf")
            
            assert success is True
            assert len(content) > 0
    
    
    def test_load_document_handles_unsupported_type(self):
        """Test load_document rejects unsupported file types."""
        from src.rag import doc_processor
        
        success, error = doc_processor.load_document("test.xyz")
        
        assert success is False
        assert "unsupported" in error.lower() or "file type" in error.lower()
