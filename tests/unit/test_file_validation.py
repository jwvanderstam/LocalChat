"""
Unit tests for src/utils/file_validation.py

Tests cover:
- Valid magic bytes for each supported format
- Mismatched content vs. declared extension
- Edge cases: empty file, unknown extension, binary content in text file
"""

import io
import zipfile

import pytest

from src.utils.file_validation import validate_file_content


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(tmp_path, name: str, content: bytes) -> str:
    p = tmp_path / name
    p.write_bytes(content)
    return str(p)


def _make_docx(tmp_path, name: str, valid: bool = True) -> str:
    """Create a minimal ZIP file, optionally with a word/ entry."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        if valid:
            zf.writestr("word/document.xml", "<w:document/>")
        else:
            zf.writestr("not-word/something.xml", "data")
    return _write(tmp_path, name, buf.getvalue())


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

class TestPdf:
    def test_valid(self, tmp_path):
        path = _write(tmp_path, "doc.pdf", b"%PDF-1.4 content here")
        ok, err = validate_file_content(path, ".pdf")
        assert ok is True
        assert err == ""

    def test_html_content(self, tmp_path):
        path = _write(tmp_path, "fake.pdf", b"<html><body>not a pdf</body></html>")
        ok, err = validate_file_content(path, ".pdf")
        assert ok is False
        assert "PDF" in err

    def test_empty_file(self, tmp_path):
        path = _write(tmp_path, "empty.pdf", b"")
        ok, err = validate_file_content(path, ".pdf")
        assert ok is False


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------

class TestDocx:
    def test_valid(self, tmp_path):
        path = _make_docx(tmp_path, "doc.docx", valid=True)
        ok, err = validate_file_content(path, ".docx")
        assert ok is True
        assert err == ""

    def test_zip_without_word_dir(self, tmp_path):
        path = _make_docx(tmp_path, "notword.docx", valid=False)
        ok, err = validate_file_content(path, ".docx")
        assert ok is False
        assert "word/" in err

    def test_plain_text_as_docx(self, tmp_path):
        path = _write(tmp_path, "fake.docx", b"This is plain text, not a ZIP")
        ok, err = validate_file_content(path, ".docx")
        assert ok is False
        assert "ZIP" in err or "DOCX" in err


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------

class TestImages:
    def test_valid_png(self, tmp_path):
        path = _write(tmp_path, "img.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
        ok, err = validate_file_content(path, ".png")
        assert ok is True

    def test_valid_jpg(self, tmp_path):
        path = _write(tmp_path, "img.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 12)
        ok, err = validate_file_content(path, ".jpg")
        assert ok is True

    def test_valid_jpeg_alias(self, tmp_path):
        path = _write(tmp_path, "img.jpeg", b"\xff\xd8\xff\xe1" + b"\x00" * 12)
        ok, err = validate_file_content(path, ".jpeg")
        assert ok is True

    def test_valid_gif(self, tmp_path):
        path = _write(tmp_path, "img.gif", b"GIF89a" + b"\x00" * 10)
        ok, err = validate_file_content(path, ".gif")
        assert ok is True

    def test_valid_webp(self, tmp_path):
        # RIFF....WEBP
        path = _write(tmp_path, "img.webp", b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 4)
        ok, err = validate_file_content(path, ".webp")
        assert ok is True

    def test_wrong_bytes_for_png(self, tmp_path):
        path = _write(tmp_path, "fake.png", b"\xff\xd8\xff" + b"\x00" * 12)
        ok, err = validate_file_content(path, ".png")
        assert ok is False
        assert "PNG" in err


# ---------------------------------------------------------------------------
# Plain text / Markdown
# ---------------------------------------------------------------------------

class TestText:
    def test_valid_txt(self, tmp_path):
        path = _write(tmp_path, "readme.txt", b"Hello, world!")
        ok, err = validate_file_content(path, ".txt")
        assert ok is True

    def test_valid_md(self, tmp_path):
        path = _write(tmp_path, "readme.md", b"# Heading\n\nSome content.")
        ok, err = validate_file_content(path, ".md")
        assert ok is True

    def test_binary_as_txt(self, tmp_path):
        path = _write(tmp_path, "binary.txt", bytes(range(256)))
        ok, err = validate_file_content(path, ".txt")
        assert ok is False
        assert "UTF-8" in err or "binary" in err.lower()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_unknown_extension_passthrough(self, tmp_path):
        path = _write(tmp_path, "data.xyz", b"\x00\x01\x02\x03")
        ok, err = validate_file_content(path, ".xyz")
        assert ok is True
        assert err == ""

    def test_nonexistent_file(self, tmp_path):
        ok, err = validate_file_content(str(tmp_path / "ghost.pdf"), ".pdf")
        assert ok is False
        assert "not found" in err.lower()
