"""
Unit tests for exceptions.py

Tests all 11 custom exception classes and helper functions.
"""

import pytest
from src.exceptions import (
    LocalChatException,
    OllamaConnectionError,
    DatabaseConnectionError,
    DocumentProcessingError,
    EmbeddingGenerationError,
    InvalidModelError,
    ValidationError,
    ConfigurationError,
    ChunkingError,
    SearchError,
    FileUploadError,
    get_status_code
)


# ============================================================================
# BASE EXCEPTION TESTS
# ============================================================================

@pytest.mark.unit
class TestLocalChatException:
    """Tests for LocalChatException base class."""
    
    def test_creates_exception_with_message(self):
        """Should create exception with message."""
        exc = LocalChatException("Test error")
        assert str(exc) == "Test error"
        assert exc.message == "Test error"
    
    def test_creates_exception_with_details(self):
        """Should create exception with details."""
        details = {"key": "value", "code": 123}
        exc = LocalChatException("Test error", details=details)
        assert exc.details == details
    
    def test_exception_is_instance_of_exception(self):
        """Should be instance of Exception."""
        exc = LocalChatException("Test")
        assert isinstance(exc, Exception)
    
    def test_to_dict_method(self):
        """Should convert to dictionary."""
        exc = LocalChatException("Test", details={"key": "value"})
        result = exc.to_dict()
        
        assert isinstance(result, dict)
        assert result["error"] == "LocalChatException"
        assert result["message"] == "Test"
        assert result["details"] == {"key": "value"}
    
    def test_to_dict_without_details(self):
        """Should convert to dict without details."""
        exc = LocalChatException("Test")
        result = exc.to_dict()
        
        assert result["error"] == "LocalChatException"
        assert result["message"] == "Test"
        assert result["details"] == {}


# ============================================================================
# OLLAMA EXCEPTION TESTS
# ============================================================================

@pytest.mark.unit
class TestOllamaConnectionError:
    """Tests for OllamaConnectionError."""
    
    def test_creates_ollama_error(self):
        """Should create Ollama connection error."""
        exc = OllamaConnectionError("Cannot connect to Ollama")
        assert str(exc) == "Cannot connect to Ollama"
    
    def test_is_subclass_of_local_chat_exception(self):
        """Should be subclass of LocalChatException."""
        exc = OllamaConnectionError("Test")
        assert isinstance(exc, LocalChatException)
    
    def test_preserves_details(self):
        """Should preserve error details."""
        details = {"url": "http://localhost:11434", "timeout": 5}
        exc = OllamaConnectionError("Connection failed", details=details)
        assert exc.details == details
    
    def test_to_dict_has_correct_error_name(self):
        """Should have correct error name in dict."""
        exc = OllamaConnectionError("Test")
        result = exc.to_dict()
        assert result["error"] == "OllamaConnectionError"


# ============================================================================
# DATABASE EXCEPTION TESTS
# ============================================================================

@pytest.mark.unit
class TestDatabaseConnectionError:
    """Tests for DatabaseConnectionError."""
    
    def test_creates_database_error(self):
        """Should create database connection error."""
        exc = DatabaseConnectionError("Cannot connect to database")
        assert str(exc) == "Cannot connect to database"
    
    def test_is_subclass_of_local_chat_exception(self):
        """Should be subclass of LocalChatException."""
        exc = DatabaseConnectionError("Test")
        assert isinstance(exc, LocalChatException)
    
    def test_includes_connection_details(self):
        """Should include connection details."""
        details = {"host": "localhost", "port": 5432, "database": "localchat"}
        exc = DatabaseConnectionError("Connection failed", details=details)
        assert exc.details["host"] == "localhost"
        assert exc.details["port"] == 5432


# ============================================================================
# DOCUMENT PROCESSING EXCEPTION TESTS
# ============================================================================

@pytest.mark.unit
class TestDocumentProcessingError:
    """Tests for DocumentProcessingError."""
    
    def test_creates_document_error(self):
        """Should create document processing error."""
        exc = DocumentProcessingError("Failed to process document")
        assert "process document" in str(exc)
    
    def test_includes_document_info(self):
        """Should include document information."""
        details = {"filename": "report.pdf", "page": 5}
        exc = DocumentProcessingError("Processing failed", details=details)
        assert exc.details["filename"] == "report.pdf"
        assert exc.details["page"] == 5


# ============================================================================
# EMBEDDING EXCEPTION TESTS
# ============================================================================

@pytest.mark.unit
class TestEmbeddingGenerationError:
    """Tests for EmbeddingGenerationError."""
    
    def test_creates_embedding_error(self):
        """Should create embedding generation error."""
        exc = EmbeddingGenerationError("Failed to generate embedding")
        assert "embedding" in str(exc).lower()
    
    def test_includes_model_info(self):
        """Should include model information."""
        details = {"model": "nomic-embed-text", "text_length": 1000}
        exc = EmbeddingGenerationError("Generation failed", details=details)
        assert exc.details["model"] == "nomic-embed-text"


# ============================================================================
# MODEL EXCEPTION TESTS
# ============================================================================

@pytest.mark.unit
class TestInvalidModelError:
    """Tests for InvalidModelError."""
    
    def test_creates_invalid_model_error(self):
        """Should create invalid model error."""
        exc = InvalidModelError("Model not found")
        assert "not found" in str(exc).lower()
    
    def test_includes_model_name(self):
        """Should include model name in details."""
        details = {"requested": "llama99", "available": ["llama3.2", "llama2"]}
        exc = InvalidModelError("Invalid model", details=details)
        assert exc.details["requested"] == "llama99"
        assert len(exc.details["available"]) == 2


# ============================================================================
# VALIDATION EXCEPTION TESTS
# ============================================================================

@pytest.mark.unit
class TestValidationError:
    """Tests for ValidationError."""
    
    def test_creates_validation_error(self):
        """Should create validation error."""
        exc = ValidationError("Validation failed")
        assert "Validation" in str(exc)
    
    def test_includes_field_information(self):
        """Should include field information."""
        details = {"field": "message", "error": "too long", "max_length": 5000}
        exc = ValidationError("Invalid input", details=details)
        assert exc.details["field"] == "message"
        assert exc.details["max_length"] == 5000
    
    def test_includes_validation_errors(self):
        """Should include multiple validation errors."""
        details = {
            "errors": [
                {"field": "email", "message": "invalid format"},
                {"field": "age", "message": "must be positive"}
            ]
        }
        exc = ValidationError("Multiple errors", details=details)
        assert len(exc.details["errors"]) == 2


# ============================================================================
# CONFIGURATION EXCEPTION TESTS
# ============================================================================

@pytest.mark.unit
class TestConfigurationError:
    """Tests for ConfigurationError."""
    
    def test_creates_configuration_error(self):
        """Should create configuration error."""
        exc = ConfigurationError("Invalid configuration")
        assert "configuration" in str(exc).lower()
    
    def test_includes_config_key(self):
        """Should include configuration key."""
        details = {"key": "CHUNK_SIZE", "value": -1, "expected": "positive integer"}
        exc = ConfigurationError("Invalid value", details=details)
        assert exc.details["key"] == "CHUNK_SIZE"


# ============================================================================
# CHUNKING EXCEPTION TESTS
# ============================================================================

@pytest.mark.unit
class TestChunkingError:
    """Tests for ChunkingError."""
    
    def test_creates_chunking_error(self):
        """Should create chunking error."""
        exc = ChunkingError("Failed to chunk document")
        assert "chunk" in str(exc).lower()
    
    def test_includes_chunking_params(self):
        """Should include chunking parameters."""
        details = {"chunk_size": 500, "overlap": 50, "text_length": 0}
        exc = ChunkingError("No chunks generated", details=details)
        assert exc.details["chunk_size"] == 500
        assert exc.details["overlap"] == 50


# ============================================================================
# SEARCH EXCEPTION TESTS
# ============================================================================

@pytest.mark.unit
class TestSearchError:
    """Tests for SearchError."""
    
    def test_creates_search_error(self):
        """Should create search error."""
        exc = SearchError("Search failed")
        assert "Search" in str(exc)
    
    def test_includes_query_info(self):
        """Should include query information."""
        details = {"query": "test query", "top_k": 5, "error": "no results"}
        exc = SearchError("No results found", details=details)
        assert exc.details["query"] == "test query"
        assert exc.details["top_k"] == 5


# ============================================================================
# FILE UPLOAD EXCEPTION TESTS
# ============================================================================

@pytest.mark.unit
class TestFileUploadError:
    """Tests for FileUploadError."""
    
    def test_creates_file_upload_error(self):
        """Should create file upload error."""
        exc = FileUploadError("Upload failed")
        assert "Upload" in str(exc) or "failed" in str(exc)
    
    def test_includes_file_info(self):
        """Should include file information."""
        details = {"filename": "large.pdf", "size": 50000000, "max_size": 16000000}
        exc = FileUploadError("File too large", details=details)
        assert exc.details["filename"] == "large.pdf"
        assert exc.details["size"] > exc.details["max_size"]


# ============================================================================
# STATUS CODE MAPPING TESTS
# ============================================================================

@pytest.mark.unit
class TestGetStatusCode:
    """Tests for get_status_code helper function."""
    
    def test_returns_400_for_validation_error(self):
        """Should return 400 for validation errors."""
        exc = ValidationError("Invalid input")
        assert get_status_code(exc) == 400
    
    def test_returns_404_for_invalid_model(self):
        """Should return 404 for invalid model."""
        exc = InvalidModelError("Model not found")
        assert get_status_code(exc) == 404
    
    def test_returns_500_for_database_error(self):
        """Should return 500 for database errors."""
        exc = DatabaseConnectionError("Connection failed")
        assert get_status_code(exc) == 500
    
    def test_returns_503_for_ollama_error(self):
        """Should return 503 for Ollama errors."""
        exc = OllamaConnectionError("Service unavailable")
        assert get_status_code(exc) == 503
    
    def test_returns_500_for_document_processing_error(self):
        """Should return 500 for document processing errors."""
        exc = DocumentProcessingError("Processing failed")
        assert get_status_code(exc) == 500
    
    def test_returns_500_for_embedding_error(self):
        """Should return 500 for embedding errors."""
        exc = EmbeddingGenerationError("Generation failed")
        assert get_status_code(exc) == 500
    
    def test_returns_500_for_configuration_error(self):
        """Should return 500 for configuration errors."""
        exc = ConfigurationError("Invalid config")
        assert get_status_code(exc) == 500
    
    def test_returns_500_for_chunking_error(self):
        """Should return 500 for chunking errors."""
        exc = ChunkingError("Chunking failed")
        assert get_status_code(exc) == 500
    
    def test_returns_500_for_search_error(self):
        """Should return 500 for search errors."""
        exc = SearchError("Search failed")
        assert get_status_code(exc) == 500
    
    def test_returns_400_for_file_upload_error(self):
        """Should return 400 for file upload errors."""
        exc = FileUploadError("Upload failed")
        assert get_status_code(exc) == 400
    
    def test_returns_500_for_base_exception(self):
        """Should return 500 for base LocalChatException."""
        exc = LocalChatException("Unknown error")
        assert get_status_code(exc) == 500


# ============================================================================
# EXCEPTION CHAINING TESTS
# ============================================================================

@pytest.mark.unit
class TestExceptionChaining:
    """Tests for exception chaining and context."""
    
    def test_can_chain_exceptions(self):
        """Should support exception chaining."""
        try:
            try:
                raise ValueError("Original error")
            except ValueError as e:
                raise DocumentProcessingError("Processing failed") from e
        except DocumentProcessingError as exc:
            assert exc.__cause__ is not None
            assert isinstance(exc.__cause__, ValueError)
    
    def test_preserves_original_exception_info(self):
        """Should preserve original exception information."""
        try:
            raise DatabaseConnectionError("Connection failed", 
                                        details={"host": "localhost"})
        except DatabaseConnectionError as exc:
            assert exc.message == "Connection failed"
            assert exc.details["host"] == "localhost"


# ============================================================================
# ERROR CONTEXT TESTS
# ============================================================================

@pytest.mark.unit
class TestErrorContext:
    """Tests for error context and details."""
    
    def test_error_with_multiple_details(self):
        """Should handle multiple detail fields."""
        details = {
            "filename": "doc.pdf",
            "page": 5,
            "error_type": "parsing",
            "timestamp": "2024-12-27T10:00:00",
            "user": "test_user"
        }
        exc = DocumentProcessingError("Processing failed", details=details)
        
        assert len(exc.details) == 5
        assert exc.details["filename"] == "doc.pdf"
        assert exc.details["page"] == 5
    
    def test_error_with_nested_details(self):
        """Should handle nested detail structures."""
        details = {
            "request": {
                "model": "llama3.2",
                "message": "test"
            },
            "response": {
                "status": "error",
                "code": 500
            }
        }
        exc = OllamaConnectionError("Request failed", details=details)
        
        assert "request" in exc.details
        assert "response" in exc.details
        assert exc.details["request"]["model"] == "llama3.2"


# ============================================================================
# EXCEPTION REPRESENTATION TESTS
# ============================================================================

@pytest.mark.unit
class TestExceptionRepresentation:
    """Tests for exception string representation."""
    
    def test_str_representation(self):
        """Should have meaningful string representation."""
        exc = ValidationError("Field validation failed")
        assert "Field validation failed" in str(exc)
    
    def test_repr_representation(self):
        """Should have meaningful repr."""
        exc = InvalidModelError("Model not found")
        repr_str = repr(exc)
        assert "InvalidModelError" in repr_str
    
    def test_to_dict_contains_all_info(self):
        """Should include all information in to_dict."""
        details = {"key": "value", "count": 42}
        exc = SearchError("Search failed", details=details)
        result = exc.to_dict()
        
        assert "error" in result
        assert "message" in result
        assert "details" in result
        assert result["error"] == "SearchError"
        assert result["message"] == "Search failed"
        assert result["details"] == details


# ============================================================================
# EDGE CASES
# ============================================================================

@pytest.mark.unit
class TestExceptionEdgeCases:
    """Edge case tests for exceptions."""
    
    def test_exception_with_empty_message(self):
        """Should handle empty message."""
        exc = LocalChatException("")
        assert exc.message == ""
        assert str(exc) == ""
    
    def test_exception_with_none_details(self):
        """Should handle None details."""
        exc = LocalChatException("Test", details=None)
        assert exc.details == {}
    
    def test_exception_with_very_long_message(self):
        """Should handle very long messages."""
        long_message = "Error: " + "a" * 10000
        exc = DocumentProcessingError(long_message)
        assert len(exc.message) == len(long_message)
    
    def test_exception_with_unicode_message(self):
        """Should handle Unicode in messages."""
        exc = ValidationError("???: Invalid ?? ??")
        assert "???" in str(exc)
    
    def test_exception_with_special_characters_in_details(self):
        """Should handle special characters in details."""
        details = {"path": "C:\\Windows\\System32", "query": "a'OR'1'='1"}
        exc = SearchError("Error", details=details)
        assert exc.details["path"] == "C:\\Windows\\System32"
        assert exc.details["query"] == "a'OR'1'='1"
