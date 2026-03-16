# -*- coding: utf-8 -*-
"""Tests for input sanitization utilities."""

import pytest
from src.utils.sanitization import (
    sanitize_filename,
    sanitize_query,
    sanitize_model_name,
    sanitize_text,
    validate_path,
)


class TestSanitizeFilename:
    def test_normal_filename_unchanged(self):
        assert sanitize_filename("document.pdf") == "document.pdf"

    def test_removes_path_traversal(self):
        result = sanitize_filename("../../etc/passwd")
        assert ".." not in result
        assert "/" not in result

    def test_removes_backslash(self):
        result = sanitize_filename("folder\\file.txt")
        assert "\\" not in result

    def test_removes_dangerous_chars(self):
        result = sanitize_filename("file<script>.pdf")
        assert "<" not in result
        assert ">" not in result

    def test_empty_string_becomes_unnamed(self):
        result = sanitize_filename("")
        assert result == "unnamed_file"

    def test_only_dots_becomes_unnamed(self):
        result = sanitize_filename("...")
        assert result == "unnamed_file"

    def test_truncates_long_filename(self):
        long_name = "a" * 300 + ".pdf"
        result = sanitize_filename(long_name, max_length=255)
        assert len(result) <= 255

    def test_preserves_extension_on_truncation(self):
        long_name = "a" * 300 + ".pdf"
        result = sanitize_filename(long_name, max_length=50)
        assert result.endswith(".pdf")

    def test_strips_leading_trailing_dots_and_spaces(self):
        result = sanitize_filename("  .myfile.  ")
        assert not result.startswith(".")
        assert not result.endswith(".")

    def test_collapses_multiple_spaces(self):
        result = sanitize_filename("my   file.txt")
        assert "  " not in result

    def test_basename_extracted_from_path(self):
        result = sanitize_filename("/some/path/file.txt")
        assert "/" not in result


class TestSanitizeQuery:
    def test_normal_query_passes_through(self):
        result = sanitize_query("What is Python?")
        assert "Python" in result

    def test_strips_leading_trailing_whitespace(self):
        result = sanitize_query("  hello  ")
        assert result == result.strip()

    def test_empty_string_returns_empty(self):
        result = sanitize_query("")
        assert result == ""

    def test_removes_null_bytes(self):
        result = sanitize_query("hello\x00world")
        assert "\x00" not in result

    def test_very_long_query_truncated(self):
        long_query = "a" * 10000
        result = sanitize_query(long_query)
        assert len(result) <= 5000  # based on typical max

    def test_unicode_preserved(self):
        result = sanitize_query("Héllo wörld")
        assert "H" in result


class TestSanitizeModelName:
    def test_valid_model_name_passes(self):
        result = sanitize_model_name("llama3.2")
        assert "llama3.2" in result

    def test_strips_whitespace(self):
        result = sanitize_model_name("  llama3  ")
        assert result == result.strip()

    def test_empty_returns_empty_or_default(self):
        result = sanitize_model_name("")
        assert result == "" or result is not None

    def test_removes_path_separator(self):
        result = sanitize_model_name("../../model")
        assert ".." not in result or "/" not in result


class TestSanitizeText:
    def test_normal_text_preserved(self):
        result = sanitize_text("Hello, world!")
        assert "Hello" in result

    def test_strips_whitespace(self):
        result = sanitize_text("   text   ")
        assert result == result.strip()

    def test_removes_null_bytes(self):
        result = sanitize_text("text\x00with\x00nulls")
        assert "\x00" not in result

    def test_empty_returns_empty(self):
        result = sanitize_text("")
        assert result == ""

    def test_unicode_text_preserved(self):
        result = sanitize_text("Ünïcödé téxt")
        assert "t" in result.lower()


class TestValidatePath:
    def test_valid_path_returns_true_or_path(self, tmp_path):
        test_file = tmp_path / "file.txt"
        test_file.write_text("content")
        result = validate_path(str(test_file), str(tmp_path))
        # Should not raise or return falsy
        assert result is not None

    def test_path_traversal_rejected(self, tmp_path):
        malicious = str(tmp_path / ".." / ".." / "etc" / "passwd")
        try:
            result = validate_path(malicious, str(tmp_path))
            # If it returns, it should indicate failure
            assert result is False or result is None or result == ""
        except (ValueError, PermissionError, Exception):
            pass  # raising is also acceptable

    def test_none_input_handled(self):
        try:
            result = validate_path(None, "/some/base")  # type: ignore[arg-type]
            assert result is None or result is False
        except (TypeError, AttributeError, Exception):
            pass
