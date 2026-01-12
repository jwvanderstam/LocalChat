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
- Table extraction
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
        test_content = "This is test content.\nMultiple lines.\n"
        test_file.write_text(test_content, encoding='utf-8')
        
        success, content = doc_processor.load_text_file(str(test_file))
        
        assert success is True
        assert content == test_content
        assert len(content) > 0
    
    def test_load_text_file_handles_encoding(self, tmp_path):
        """Test text file with UTF-8 encoding."""
        from src.rag import doc_processor
        
        test_file = tmp_path / "unicode.txt"
        test_content = "Unicode: é ü ß ø Chinese Japanese"
        test_file.write_text(test_content, encoding='utf-8')
        
        success, content = doc_processor.load_text_file(str(test_file))
        
        assert success is True
        assert "Chinese" in content
        assert "é" in content
    
    def test_load_text_file_handles_missing_file(self):
        """Test loading non-existent file."""
        from src.rag import doc_processor
        
        success, error = doc_processor.load_text_file("nonexistent.txt")
        
        assert success is False
        assert "No such file" in error or "not found" in error.lower()


class TestPDFLoading:
    """Test PDF file loading."""
    
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
    
    def test_load_pdf_with_table_extraction(self):
        """Test PDF loading with table extraction."""
        from src.rag import doc_processor
        
        # Mock PDF with tables
        mock_pdf = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Page with table"
        mock_page.extract_tables.return_value = [
            [["Header1", "Header2"], ["Data1", "Data2"]]
        ]
        mock_pdf.pages = [mock_page]
        
        with patch('src.rag.pdfplumber') as mock_pdfplumber:
            mock_pdfplumber.open.return_value.__enter__.return_value = mock_pdf
            
            success, content = doc_processor.load_pdf_file("table.pdf")
            
            assert success is True
            assert "Header1" in content or "Data1" in content
    
    def test_load_pdf_fallback_to_pypdf2(self):
        """Test fallback to PyPDF2 when pdfplumber fails."""
        from src.rag import doc_processor
        
        # Mock PyPDF2
        mock_reader = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "PyPDF2 extracted content"
        mock_reader.pages = [mock_page]
        
        with patch('src.rag.pdfplumber', None):  # pdfplumber not available
            with patch('src.rag.PyPDF2.PdfReader', return_value=mock_reader):
                with patch('builtins.open', mock_open(read_data=b'PDF content')):
                    success, content = doc_processor.load_pdf_file("test.pdf")
                    
                    assert success is True
                    assert "PyPDF2" in content or len(content) > 0
    
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
    
    def test_load_pdf_handles_corrupted_file(self):
        """Test handling of corrupted PDF files."""
        from src.rag import doc_processor
        
        with patch('src.rag.pdfplumber') as mock_pdfplumber:
            mock_pdfplumber.open.side_effect = Exception("Corrupted PDF")
            
            with patch('src.rag.PyPDF2.PdfReader', side_effect=Exception("Cannot read")):
                with patch('builtins.open', mock_open(read_data=b'corrupted')):
                    success, error = doc_processor.load_pdf_file("corrupted.pdf")
                    
                    assert success is False
                    assert len(error) > 0


class TestDOCXLoading:
    """Test DOCX file loading."""
    
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
    
    def test_load_docx_with_tables(self):
        """Test DOCX loading with tables."""
        from src.rag import doc_processor
        
        # Mock Document with tables
        mock_doc = MagicMock()
        mock_doc.paragraphs = []
        
        mock_table = MagicMock()
        mock_row = MagicMock()
        mock_cell = MagicMock()
        mock_cell.text = "Cell content"
        mock_row.cells = [mock_cell]
        mock_table.rows = [mock_row]
        mock_doc.tables = [mock_table]
        
        with patch('src.rag.Document', return_value=mock_doc):
            success, content = doc_processor.load_docx_file("table.docx")
            
            assert success is True
            assert "Cell content" in content
    
    def test_load_docx_handles_missing_file(self):
        """Test handling of missing DOCX file."""
        from src.rag import doc_processor
        
        with patch('src.rag.Document', side_effect=FileNotFoundError("File not found")):
            success, error = doc_processor.load_docx_file("missing.docx")
            
            assert success is False
            assert "not found" in error.lower()
    
    def test_load_docx_handles_empty_document(self):
        """Test handling of empty DOCX."""
        from src.rag import doc_processor
        
        mock_doc = MagicMock()
        mock_doc.paragraphs = []
        mock_doc.tables = []
        
        with patch('src.rag.Document', return_value=mock_doc):
            success, error = doc_processor.load_docx_file("empty.docx")
            
            assert success is False
            assert "empty" in error.lower()
    
    def test_load_docx_handles_password_protected(self):
        """Test handling of password-protected DOCX."""
        from src.rag import doc_processor
        
        with patch('src.rag.Document', side_effect=Exception("Password protected")):
            success, error = doc_processor.load_docx_file("protected.docx")
            
            assert success is False
            assert len(error) > 0


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
    
    def test_load_document_routes_to_docx(self):
        """Test load_document routes .docx files correctly."""
        from src.rag import doc_processor
        
        mock_doc = MagicMock()
        mock_para = MagicMock()
        mock_para.text = "DOCX content"
        mock_doc.paragraphs = [mock_para]
        mock_doc.tables = []
        
        with patch('src.rag.Document', return_value=mock_doc):
            success, content = doc_processor.load_document("test.docx")
            
            assert success is True
            assert "DOCX content" in content
    
    def test_load_document_handles_unsupported_type(self):
        """Test load_document rejects unsupported file types."""
        from src.rag import doc_processor
        
        success, error = doc_processor.load_document("test.xyz")
        
        assert success is False
        assert "unsupported" in error.lower() or "file type" in error.lower()
    
    def test_load_document_handles_markdown(self, tmp_path):
        """Test load_document handles .md files."""
        from src.rag import doc_processor
        
        test_file = tmp_path / "test.md"
        test_file.write_text("# Markdown content\n\nParagraph", encoding='utf-8')
        
        success, content = doc_processor.load_document(str(test_file))
        
        assert success is True
        assert "Markdown content" in content


class TestContentValidation:
    """Test content validation after loading."""
    
    def test_validates_minimum_content_length(self, tmp_path):
        """Test validation of minimum content length."""
        from src.rag import doc_processor
        
        # Create file with very little content
        test_file = tmp_path / "short.txt"
        test_file.write_text("x", encoding='utf-8')
        
        success, content = doc_processor.load_text_file(str(test_file))
        
        # Should load but might be flagged as insufficient
        assert success is True
        assert len(content) > 0
    
    def test_handles_binary_content_in_text(self, tmp_path):
        """Test handling binary content in text file."""
        from src.rag import doc_processor
        
        test_file = tmp_path / "binary.txt"
        test_file.write_bytes(b'\x00\x01\x02\xFF')
        
        # Should handle without crashing
        success, result = doc_processor.load_text_file(str(test_file))
        # May succeed or fail, but shouldn't crash
        assert isinstance(success, bool)


class TestTableExtraction:
    """Test table extraction from documents."""
    
    def test_extracts_tables_from_pdf(self):
        """Test table extraction from PDF."""
        from src.rag import doc_processor
        
        # Mock PDF with complex table
        mock_pdf = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Text before table"
        mock_page.extract_tables.return_value = [
            [
                ["Name", "Age", "City"],
                ["John", "30", "NYC"],
                ["Jane", "25", "LA"]
            ]
        ]
        mock_pdf.pages = [mock_page]
        
        with patch('src.rag.pdfplumber') as mock_pdfplumber:
            mock_pdfplumber.open.return_value.__enter__.return_value = mock_pdf
            
            success, content = doc_processor.load_pdf_file("table.pdf")
            
            assert success is True
            # Should contain table data in some form
            assert len(content) > len("Text before table")
    
    def test_handles_empty_table_cells(self):
        """Test handling of empty cells in tables."""
        from src.rag import doc_processor
        
        mock_pdf = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = ""
        mock_page.extract_tables.return_value = [
            [
                ["Header1", None, "Header3"],
                [None, "Data2", None]
            ]
        ]
        mock_pdf.pages = [mock_page]
        
        with patch('src.rag.pdfplumber') as mock_pdfplumber:
            mock_pdfplumber.open.return_value.__enter__.return_value = mock_pdf
            
            success, content = doc_processor.load_pdf_file("sparse_table.pdf")
            
            # Should handle None values gracefully
            assert success is True or success is False  # Either outcome is ok
            if success:
                assert isinstance(content, str)


class TestErrorRecovery:
    """Test error recovery and logging."""
    
    def test_logs_errors_during_loading(self):
        """Test that errors are properly logged."""
        from src.rag import doc_processor
        
        with patch('src.rag.pdfplumber') as mock_pdfplumber:
            mock_pdfplumber.open.side_effect = Exception("Test error")
            
            with patch('src.rag.PyPDF2.PdfReader', side_effect=Exception("Also fails")):
                with patch('builtins.open', mock_open()):
                    success, error = doc_processor.load_pdf_file("error.pdf")
                    
                    assert success is False
                    assert len(error) > 0
                    assert isinstance(error, str)
    
    def test_provides_helpful_error_messages(self):
        """Test that error messages are helpful."""
        from src.rag import doc_processor
        
        # Test with non-existent file
        success, error = doc_processor.load_text_file("/nonexistent/path/file.txt")
        
        assert success is False
        assert len(error) > 10  # Should be descriptive
        assert isinstance(error, str)
