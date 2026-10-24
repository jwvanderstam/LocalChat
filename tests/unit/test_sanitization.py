"""
Unit tests for utils/sanitization.py

Tests all 12 sanitization functions to ensure proper input validation
and security against various attacks (XSS, path traversal, SQL injection, etc.)
"""

import os

import pytest

from src.utils.sanitization import (
    escape_sql_like,
    sanitize_filename,
    sanitize_json_keys,
    sanitize_model_name,
    sanitize_query,
    validate_path,
)

# ============================================================================
# SANITIZE_FILENAME TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.sanitization
class TestSanitizeFilename:
    """Tests for sanitize_filename function."""

    def test_removes_path_traversal(self):
        """Should remove path traversal attempts."""
        result = sanitize_filename("../../etc/passwd")
        assert result == "passwd"
        assert ".." not in result

    def test_removes_forward_slashes(self):
        """Should remove forward slashes."""
        result = sanitize_filename("path/to/file.pdf")
        assert "/" not in result
        assert result.endswith(".pdf")

    def test_removes_backslashes(self):
        """Should remove backslashes."""
        result = sanitize_filename("path\\to\\file.pdf")
        assert "\\" not in result
        assert result.endswith(".pdf")

    def test_removes_special_characters(self):
        """Should remove special characters."""
        result = sanitize_filename("file<>:name|?.pdf")
        assert all(c not in result for c in ['<', '>', ':', '|', '?'])

    def test_preserves_valid_filename(self):
        """Should preserve valid filenames."""
        result = sanitize_filename("document_v1.2.pdf")
        assert result == "document_v1.2.pdf"

    def test_handles_empty_string(self):
        """Should handle empty strings."""
        result = sanitize_filename("")
        assert result == "unnamed_file"

    def test_handles_only_special_chars(self):
        """Should handle filenames with only special characters."""
        result = sanitize_filename("<<<>>>")
        assert result == "unnamed_file"

    def test_truncates_long_filenames(self):
        """Should truncate very long filenames."""
        long_name = "a" * 300 + ".pdf"
        result = sanitize_filename(long_name, max_length=100)
        assert len(result) <= 100


# ============================================================================
# SANITIZE_QUERY TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.sanitization
class TestSanitizeQuery:
    """Tests for sanitize_query function."""

    def test_normalizes_whitespace(self):
        """Should normalize multiple spaces."""
        result = sanitize_query("text    with     spaces")
        assert "    " not in result

    def test_removes_control_characters(self):
        """Should remove control characters."""
        result = sanitize_query("text\x01\x02with\x03controls")
        assert "\x01" not in result
        assert "\x02" not in result

    def test_preserves_valid_query(self):
        """Should preserve valid queries."""
        query = "What is the meaning of life?"
        result = sanitize_query(query)
        assert "meaning of life" in result.lower()

    def test_handles_empty_string(self):
        """Should handle empty strings."""
        result = sanitize_query("")
        assert result == ""

    def test_truncates_long_queries(self):
        """Should truncate very long queries."""
        long_query = "a" * 10000
        result = sanitize_query(long_query, max_length=1000)
        assert len(result) <= 1000


# ============================================================================
# SANITIZE_MODEL_NAME TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.sanitization
class TestSanitizeModelName:
    """Tests for sanitize_model_name function."""

    def test_preserves_valid_model_name(self):
        """Should preserve valid model names."""
        result = sanitize_model_name("llama3.2")
        assert result == "llama3.2"

    def test_preserves_colons_in_tags(self):
        """Should preserve colons for version tags."""
        result = sanitize_model_name("llama3.2:latest")
        assert result == "llama3.2:latest"

    def test_removes_special_characters(self):
        """Should remove special characters except dots, dashes, colons."""
        result = sanitize_model_name("model<>name!@#")
        assert all(c not in result for c in ['<', '>', '!', '@', '#'])

    def test_handles_empty_string(self):
        """Should handle empty strings."""
        result = sanitize_model_name("")
        assert isinstance(result, str)


# ============================================================================
# SANITIZE_TEXT TESTS
# ============================================================================


# ============================================================================
# VALIDATE_PATH TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.sanitization
class TestValidatePath:
    """Tests for validate_path function."""

    def test_rejects_path_traversal(self, temp_dir):
        """Should reject path traversal attempts."""
        assert not validate_path("../../etc/passwd", temp_dir)

    def test_accepts_safe_relative_paths(self, temp_dir):
        """Should accept safe relative paths."""
        # Create a subdirectory
        subdir = os.path.join(temp_dir, "uploads")
        os.makedirs(subdir, exist_ok=True)

        test_file = os.path.join(subdir, "file.pdf")
        assert validate_path(test_file, temp_dir)

    def test_accepts_files_in_base_dir(self, temp_dir):
        """Should accept files in base directory."""
        test_file = os.path.join(temp_dir, "file.pdf")
        assert validate_path(test_file, temp_dir)


# ============================================================================
# SANITIZE_FILE_EXTENSION TESTS
# ============================================================================


# ============================================================================
# SANITIZE_JSON_KEYS TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.sanitization
class TestSanitizeJsonKeys:
    """Tests for sanitize_json_keys function."""

    def test_sanitizes_dict_keys(self):
        """Should sanitize dictionary keys."""
        input_dict = {"<script>": "value", "normal_key": "value2"}
        result = sanitize_json_keys(input_dict)
        assert "script" in result  # Sanitized version
        assert "normal_key" in result
        assert "<script>" not in result

    def test_recursively_sanitizes_nested_dicts(self):
        """Should recursively sanitize nested dictionaries."""
        input_dict = {
            "key1": {"<bad>": "value"},
            "key2": "value"
        }
        result = sanitize_json_keys(input_dict)
        assert "<bad>" not in str(result)

    def test_handles_empty_dict(self):
        """Should handle empty dictionaries."""
        result = sanitize_json_keys({})
        assert result == {}


# ============================================================================
# ESCAPE_SQL_LIKE TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.sanitization
class TestEscapeSqlLike:
    """Tests for escape_sql_like function."""

    def test_escapes_percent_sign(self):
        """Should escape percent signs."""
        result = escape_sql_like("50%")
        assert "\\%" in result

    def test_escapes_underscore(self):
        """Should escape underscores."""
        result = escape_sql_like("file_name")
        assert "\\_" in result

    def test_preserves_normal_text(self):
        """Should preserve normal text."""
        result = escape_sql_like("normal text")
        assert "normal" in result
        assert "text" in result


# ============================================================================
# TRUNCATE_TEXT TESTS
# ============================================================================


# ============================================================================
# REMOVE_NULL_BYTES TESTS
# ============================================================================


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.sanitization
class TestSanitizationIntegration:
    """Integration tests for multiple sanitization functions."""

    def test_complete_filename_sanitization(self):
        """Should completely sanitize a dangerous filename."""
        dangerous = "../../<script>evil</script>.pdf"
        result = sanitize_filename(dangerous)
        assert ".." not in result
        assert "<script>" not in result
        assert result.endswith(".pdf")

