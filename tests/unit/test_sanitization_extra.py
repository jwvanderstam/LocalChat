# -*- coding: utf-8 -*-
"""Additional sanitization tests for uncovered functions."""

import pytest
from pathlib import Path


class TestSanitizeTextExtra:
    def test_removes_html_tags(self):
        from src.utils.sanitization import sanitize_text
        result = sanitize_text("<script>alert('xss')</script>Hello world")
        assert "<" not in result
        assert "Hello" in result

    def test_remove_html_false_preserves_tags(self):
        from src.utils.sanitization import sanitize_text
        result = sanitize_text("<b>bold</b>", remove_html=False)
        assert "<b>" in result

    def test_truncates_at_max_length(self):
        from src.utils.sanitization import sanitize_text
        result = sanitize_text("a" * 200, max_length=50)
        assert len(result) == 50

    def test_removes_control_chars(self):
        from src.utils.sanitization import sanitize_text
        result = sanitize_text("hello\x01\x02world")
        assert "\x01" not in result
        assert "\x02" not in result

    def test_preserves_newlines_and_tabs(self):
        from src.utils.sanitization import sanitize_text
        result = sanitize_text("line1\nline2\ttab")
        assert "\n" in result

    def test_collapses_excessive_newlines(self):
        from src.utils.sanitization import sanitize_text
        result = sanitize_text("a\n\n\n\n\nb")
        assert "\n\n\n" not in result


class TestValidatePath:
    def test_valid_path_inside_base_returns_true(self, tmp_path):
        from src.utils.sanitization import validate_path
        sub = tmp_path / "sub" / "file.txt"
        sub.parent.mkdir()
        sub.touch()
        assert validate_path(str(sub), str(tmp_path)) is True

    def test_traversal_path_returns_false(self, tmp_path):
        from src.utils.sanitization import validate_path
        malicious = str(tmp_path / ".." / ".." / "etc" / "passwd")
        result = validate_path(malicious, str(tmp_path))
        assert result is False

    def test_oserror_path_returns_false(self):
        from src.utils.sanitization import validate_path
        result = validate_path("\x00invalid", "/some/base")
        assert result is False


class TestSanitizeFileExtension:
    def test_allowed_extension_returns_true(self):
        from src.utils.sanitization import sanitize_file_extension
        assert sanitize_file_extension("doc.pdf", [".pdf", ".txt"]) is True

    def test_disallowed_extension_returns_false(self):
        from src.utils.sanitization import sanitize_file_extension
        assert sanitize_file_extension("malware.exe", [".pdf", ".txt"]) is False

    def test_case_insensitive(self):
        from src.utils.sanitization import sanitize_file_extension
        assert sanitize_file_extension("DOC.PDF", [".pdf"]) is True

    def test_no_extension_returns_false(self):
        from src.utils.sanitization import sanitize_file_extension
        assert sanitize_file_extension("noextension", [".pdf"]) is False


class TestSanitizeJsonKeys:
    def test_removes_dangerous_chars_from_keys(self):
        from src.utils.sanitization import sanitize_json_keys
        result = sanitize_json_keys({"user<script>": "value"})
        assert "user<script>" not in result
        assert any("user" in k for k in result)

    def test_preserves_safe_keys(self):
        from src.utils.sanitization import sanitize_json_keys
        result = sanitize_json_keys({"safe_key": "value", "another-key": 42})
        assert "safe_key" in result
        assert result["safe_key"] == "value"

    def test_nested_dict_sanitized(self):
        from src.utils.sanitization import sanitize_json_keys
        data = {"outer": {"inner<>": "v"}}
        result = sanitize_json_keys(data)
        assert isinstance(result["outer"], dict)

    def test_list_values_preserved(self):
        from src.utils.sanitization import sanitize_json_keys
        data = {"items": [1, 2, 3]}
        result = sanitize_json_keys(data)
        assert result["items"] == [1, 2, 3]

    def test_max_depth_stops_recursion(self):
        from src.utils.sanitization import sanitize_json_keys
        deep = {"a": {"b": {"c": "deep"}}}
        result = sanitize_json_keys(deep, max_depth=1)
        assert result is not None

    def test_nested_list_of_dicts(self):
        from src.utils.sanitization import sanitize_json_keys
        data = {"items": [{"key<>": "val"}]}
        result = sanitize_json_keys(data)
        assert isinstance(result["items"][0], dict)


class TestEscapeSqlLike:
    def test_escapes_percent(self):
        from src.utils.sanitization import escape_sql_like
        result = escape_sql_like("100%")
        assert "\\%" in result

    def test_escapes_underscore(self):
        from src.utils.sanitization import escape_sql_like
        result = escape_sql_like("some_value")
        assert "\\_" in result

    def test_escapes_brackets(self):
        from src.utils.sanitization import escape_sql_like
        result = escape_sql_like("[test]")
        assert "\\[" in result
        assert "\\]" in result

    def test_plain_text_unchanged(self):
        from src.utils.sanitization import escape_sql_like
        result = escape_sql_like("hello world")
        assert result == "hello world"


class TestTruncateText:
    def test_short_text_not_truncated(self):
        from src.utils.sanitization import truncate_text
        result = truncate_text("short", 100)
        assert result == "short"

    def test_long_text_truncated_with_suffix(self):
        from src.utils.sanitization import truncate_text
        result = truncate_text("a" * 50, 10)
        assert result.endswith("...")
        assert len(result) == 10

    def test_custom_suffix(self):
        from src.utils.sanitization import truncate_text
        result = truncate_text("hello world long text", 8, suffix=" [cut]")
        assert result.endswith(" [cut]")

    def test_exact_length_not_truncated(self):
        from src.utils.sanitization import truncate_text
        text = "exact"
        result = truncate_text(text, 5)
        assert result == text


class TestRemoveNullBytes:
    def test_removes_null_bytes(self):
        from src.utils.sanitization import remove_null_bytes
        result = remove_null_bytes("test\x00data")
        assert "\x00" not in result
        assert result == "testdata"

    def test_no_null_bytes_unchanged(self):
        from src.utils.sanitization import remove_null_bytes
        result = remove_null_bytes("clean string")
        assert result == "clean string"
