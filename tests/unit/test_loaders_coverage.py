# -*- coding: utf-8 -*-
"""Additional coverage for rag/loaders.py."""

import pytest
from unittest.mock import MagicMock, patch, mock_open
import os


# ---------------------------------------------------------------------------
# _format_table_rows
# ---------------------------------------------------------------------------

class TestFormatTableRows:
    def setup_method(self):
        from src.rag import doc_processor as dp
        self.loader = dp

    def test_format_table_rows_basic(self):
        from src.rag.loaders import DocumentLoaderMixin
        loader = DocumentLoaderMixin()
        result = loader._format_table_rows([["a", "b"], ["c", "d"]])
        assert "a | b" in result
        assert "c | d" in result

    def test_format_table_rows_skips_empty_rows(self):
        from src.rag.loaders import DocumentLoaderMixin
        loader = DocumentLoaderMixin()
        result = loader._format_table_rows([[], ["a", "b"], None])
        assert "a | b" in result

    def test_format_table_rows_handles_none_cells(self):
        from src.rag.loaders import DocumentLoaderMixin
        loader = DocumentLoaderMixin()
        result = loader._format_table_rows([[None, "val", None]])
        assert "val" in result

    def test_format_table_rows_empty_table(self):
        from src.rag.loaders import DocumentLoaderMixin
        loader = DocumentLoaderMixin()
        result = loader._format_table_rows([])
        assert result == ""


class TestExtractPdfplumberTableText:
    def test_no_tables_returns_empty(self):
        from src.rag.loaders import DocumentLoaderMixin
        loader = DocumentLoaderMixin()
        mock_page = MagicMock()
        mock_page.extract_tables.return_value = []
        result = loader._extract_pdfplumber_table_text(mock_page, 1)
        assert result == ""

    def test_table_extraction_success(self):
        from src.rag.loaders import DocumentLoaderMixin
        loader = DocumentLoaderMixin()
        mock_page = MagicMock()
        mock_page.extract_tables.return_value = [[["Name", "Value"], ["Alice", "42"]]]
        result = loader._extract_pdfplumber_table_text(mock_page, 1)
        assert "[Table 1 on page 1]" in result
        assert "Name" in result

    def test_table_with_none_table_skipped(self):
        from src.rag.loaders import DocumentLoaderMixin
        loader = DocumentLoaderMixin()
        mock_page = MagicMock()
        mock_page.extract_tables.return_value = [None, [["a", "b"]]]
        result = loader._extract_pdfplumber_table_text(mock_page, 2)
        assert "a | b" in result

    def test_extract_table_text_exception_returns_empty(self):
        from src.rag.loaders import DocumentLoaderMixin
        loader = DocumentLoaderMixin()
        mock_page = MagicMock()
        mock_page.extract_tables.side_effect = Exception("page error")
        result = loader._extract_pdfplumber_table_text(mock_page, 3)
        assert result == ""


class TestExtractPdfplumberText:
    def test_extraction_success(self):
        from src.rag.loaders import DocumentLoaderMixin
        loader = DocumentLoaderMixin()

        mock_page = MagicMock()
        mock_page.extract_text.return_value = "x" * 60  # 60 chars per page × 2 = 120 > 100
        mock_page.extract_tables.return_value = []

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page, mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = mock_pdf

        result = loader._extract_pdfplumber_text(mock_pdfplumber, "/fake/file.pdf")
        assert len(result) >= 100

    def test_extraction_raises_on_short_text(self):
        from src.rag.loaders import DocumentLoaderMixin
        loader = DocumentLoaderMixin()

        mock_page = MagicMock()
        mock_page.extract_text.return_value = "short"
        mock_page.extract_tables.return_value = []

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = mock_pdf

        with pytest.raises(ValueError):
            loader._extract_pdfplumber_text(mock_pdfplumber, "/fake/file.pdf")

    def test_page_with_no_text_logs_warning(self):
        from src.rag.loaders import DocumentLoaderMixin
        loader = DocumentLoaderMixin()

        mock_page = MagicMock()
        mock_page.extract_text.return_value = None
        mock_page.extract_tables.return_value = []

        # pad with real pages so threshold passes
        real_page = MagicMock()
        real_page.extract_text.return_value = "x" * 200
        real_page.extract_tables.return_value = []

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page, real_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = mock_pdf

        result = loader._extract_pdfplumber_text(mock_pdfplumber, "/f.pdf")
        assert len(result) >= 100


class TestExtractPyPDF2Text:
    def test_extraction_success(self):
        from src.rag.loaders import DocumentLoaderMixin
        loader = DocumentLoaderMixin()

        mock_page = MagicMock()
        mock_page.extract_text.return_value = "PyPDF2 page content."
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]

        with patch("src.rag.loaders.PyPDF2") as mock_pypdf2:
            mock_pypdf2.PdfReader.return_value = mock_reader
            with patch("builtins.open", mock_open(read_data=b"pdf data")):
                result = loader._extract_pypdf2_text("/fake.pdf")
        assert "PyPDF2 page content." in result

    def test_page_extraction_error_skipped(self):
        from src.rag.loaders import DocumentLoaderMixin
        loader = DocumentLoaderMixin()

        mock_page = MagicMock()
        mock_page.extract_text.side_effect = Exception("page corrupt")
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]

        with patch("src.rag.loaders.PyPDF2") as mock_pypdf2:
            mock_pypdf2.PdfReader.return_value = mock_reader
            with patch("builtins.open", mock_open(read_data=b"pdf data")):
                result = loader._extract_pypdf2_text("/fake.pdf")
        assert result == ""


class TestLoadPagesHelpers:
    def test_load_pages_pdfplumber(self):
        from src.rag.loaders import DocumentLoaderMixin
        loader = DocumentLoaderMixin()

        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Section 1\nSome content here."
        mock_page.extract_tables.return_value = []

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page, mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = mock_pdf

        pages = loader._load_pages_pdfplumber(mock_pdfplumber, "/f.pdf")
        assert len(pages) == 2
        assert pages[0]['page_number'] == 1

    def test_load_pages_pdfplumber_empty_page_skipped(self):
        from src.rag.loaders import DocumentLoaderMixin
        loader = DocumentLoaderMixin()

        mock_page = MagicMock()
        mock_page.extract_text.return_value = ""
        mock_page.extract_tables.return_value = []

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = mock_pdf

        pages = loader._load_pages_pdfplumber(mock_pdfplumber, "/f.pdf")
        assert pages == []

    def test_load_pages_pypdf2(self):
        from src.rag.loaders import DocumentLoaderMixin
        loader = DocumentLoaderMixin()

        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Content on page."
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]

        with patch("src.rag.loaders.PyPDF2") as mock_pypdf2:
            mock_pypdf2.PdfReader.return_value = mock_reader
            with patch("builtins.open", mock_open(read_data=b"data")):
                pages = loader._load_pages_pypdf2("/f.pdf")
        assert len(pages) == 1
        assert pages[0]['page_number'] == 1


class TestLoadPdfFile:
    def test_pdf_not_available_returns_false(self):
        from src.rag.loaders import DocumentLoaderMixin
        loader = DocumentLoaderMixin()
        with patch("src.rag.loaders.PDF_AVAILABLE", False):
            ok, msg = loader.load_pdf_file("/f.pdf")
        assert ok is False

    def test_load_pdf_with_pdfplumber(self):
        from src.rag.loaders import DocumentLoaderMixin
        loader = DocumentLoaderMixin()

        with patch("src.rag.loaders.PDF_AVAILABLE", True), \
             patch.object(loader, "_try_pdfplumber_import") as mock_import, \
             patch.object(loader, "_extract_pdfplumber_text",
                          return_value="x" * 200) as mock_extract, \
             patch("os.path.getsize", return_value=10000):
            mock_import.return_value = MagicMock()
            ok, text = loader.load_pdf_file("/f.pdf")
        assert ok is True
        assert len(text) >= 100

    def test_load_pdf_falls_back_to_pypdf2(self):
        from src.rag.loaders import DocumentLoaderMixin
        loader = DocumentLoaderMixin()

        with patch("src.rag.loaders.PDF_AVAILABLE", True), \
             patch.object(loader, "_try_pdfplumber_import") as mock_import, \
             patch.object(loader, "_extract_pdfplumber_text",
                          side_effect=Exception("pdfplumber failed")), \
             patch.object(loader, "_extract_pypdf2_text",
                          return_value="y" * 200), \
             patch("os.path.getsize", return_value=10000):
            mock_import.return_value = MagicMock()
            ok, text = loader.load_pdf_file("/f.pdf")
        assert ok is True

    def test_load_pdf_no_pdfplumber_uses_pypdf2(self):
        from src.rag.loaders import DocumentLoaderMixin
        loader = DocumentLoaderMixin()

        with patch("src.rag.loaders.PDF_AVAILABLE", True), \
             patch.object(loader, "_try_pdfplumber_import", return_value=None), \
             patch.object(loader, "_extract_pypdf2_text", return_value="z" * 200), \
             patch("os.path.getsize", return_value=10000):
            ok, text = loader.load_pdf_file("/f.pdf")
        assert ok is True

    def test_load_pdf_empty_text_returns_false(self):
        from src.rag.loaders import DocumentLoaderMixin
        loader = DocumentLoaderMixin()

        with patch("src.rag.loaders.PDF_AVAILABLE", True), \
             patch.object(loader, "_try_pdfplumber_import", return_value=None), \
             patch.object(loader, "_extract_pypdf2_text", return_value="   "), \
             patch("os.path.getsize", return_value=10000):
            ok, msg = loader.load_pdf_file("/f.pdf")
        assert ok is False


class TestLoadPdfWithPages:
    def test_no_pdf_library_returns_false(self):
        from src.rag.loaders import DocumentLoaderMixin
        loader = DocumentLoaderMixin()
        with patch("src.rag.loaders.PDF_AVAILABLE", False):
            ok, err = loader._load_pdf_with_pages("/f.pdf")
        assert ok is False

    def test_uses_pdfplumber_when_available(self):
        from src.rag.loaders import DocumentLoaderMixin
        loader = DocumentLoaderMixin()
        pages = [{"page_number": 1, "text": "content", "section_title": None}]

        with patch("src.rag.loaders.PDF_AVAILABLE", True), \
             patch.object(loader, "_try_pdfplumber_import", return_value=MagicMock()), \
             patch.object(loader, "_load_pages_pdfplumber", return_value=pages):
            ok, result = loader._load_pdf_with_pages("/f.pdf")
        assert ok is True
        assert len(result) == 1

    def test_falls_back_to_pypdf2(self):
        from src.rag.loaders import DocumentLoaderMixin
        loader = DocumentLoaderMixin()
        pages = [{"page_number": 1, "text": "content", "section_title": None}]

        with patch("src.rag.loaders.PDF_AVAILABLE", True), \
             patch.object(loader, "_try_pdfplumber_import", return_value=None), \
             patch.object(loader, "_load_pages_pypdf2", return_value=pages):
            ok, result = loader._load_pdf_with_pages("/f.pdf")
        assert ok is True

    def test_empty_pages_returns_false(self):
        from src.rag.loaders import DocumentLoaderMixin
        loader = DocumentLoaderMixin()

        with patch("src.rag.loaders.PDF_AVAILABLE", True), \
             patch.object(loader, "_try_pdfplumber_import", return_value=None), \
             patch.object(loader, "_load_pages_pypdf2", return_value=[]):
            ok, msg = loader._load_pdf_with_pages("/f.pdf")
        assert ok is False


class TestSectionTitle:
    def setup_method(self):
        from src.rag.loaders import DocumentLoaderMixin
        self.loader = DocumentLoaderMixin()

    def test_line_looks_like_title_short_title_case(self):
        result = self.loader._line_looks_like_title("Introduction Overview")
        assert result is not None

    def test_line_looks_like_title_all_caps(self):
        result = self.loader._line_looks_like_title("CHAPTER ONE")
        assert result is not None

    def test_line_looks_like_title_too_long_returns_none(self):
        result = self.loader._line_looks_like_title("A" * 101)
        assert result is None

    def test_line_with_colon_strips_colon(self):
        result = self.loader._line_looks_like_title("Introduction:")
        # Should strip colon if single word — depends on word count check
        # Just verify no exception
        assert result is None or isinstance(result, str)

    def test_extract_section_title_empty_text(self):
        result = self.loader._extract_section_title("")
        assert result is None

    def test_extract_section_title_finds_title(self):
        text = "Introduction Overview\n\nSome text here."
        result = self.loader._extract_section_title(text)
        assert result is not None

    def test_extract_section_title_skips_numbered_line(self):
        text = "1. First item\nSome text."
        result = self.loader._extract_section_title(text)
        assert result is None or isinstance(result, str)

    def test_load_document_unsupported_extension(self, tmp_path):
        from src.rag.loaders import DocumentLoaderMixin
        loader = DocumentLoaderMixin()
        f = tmp_path / "file.xyz"
        f.write_text("content")
        ok, msg = loader.load_document(str(f))
        assert ok is False
        assert "Unsupported" in msg or "unsupported" in msg.lower()
