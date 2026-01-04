"""
Comprehensive Exception Tests - Week 3 Day 1
============================================

Tests the custom exception classes from src/exceptions.py.
Target: 15+ tests, 100% coverage on exceptions.py

Run: pytest tests/test_exceptions_comprehensive.py -v --cov=src.exceptions --cov-report=term-missing
"""

import pytest
import os
from unittest.mock import patch, Mock
from typing import Dict, Any

# Mark all tests
pytestmark = [pytest.mark.unit, pytest.mark.exceptions]

# Mock environment variables BEFORE importing src modules
@pytest.fixture(scope="session", autouse=True)
def mock_env_vars():
    """Mock environment variables for testing."""
    with patch.dict(os.environ, {
        'PG_PASSWORD': 'test_password',
        'OLLAMA_BASE_URL': 'http://localhost:11434',
        'SECRET_KEY': 'test_secret',
        'JWT_SECRET_KEY': 'test_jwt_secret'
    }):
        yield


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def sample_error_details():
    """Sample error details dictionary."""
    return {
        'field': 'test_field',
        'value': 'invalid_value',
        'constraint': 'min_length'
    }


# ============================================================================
# EXCEPTION CREATION TESTS (10 tests)
# ============================================================================

class TestExceptionCreation:
    """Test exception creation and initialization."""
    
    def test_localchat_exception_basic(self):
        """Should create basic LocalChatException."""
        from src.exceptions import LocalChatException
        
        exc = LocalChatException("Test error message")
        
        assert exc.message == "Test error message"
        assert exc.details == {}
        assert str(exc) == "Test error message"
    
    def test_localchat_exception_with_details(self, sample_error_details):
        """Should create LocalChatException with details."""
        from src.exceptions import LocalChatException
        
        exc = LocalChatException("Test error", details=sample_error_details)
        
        assert exc.message == "Test error"
        assert exc.details == sample_error_details
        assert exc.details['field'] == 'test_field'
    
    def test_ollama_connection_error(self):
        """Should create OllamaConnectionError."""
        from src.exceptions import OllamaConnectionError
        
        details = {'url': 'http://localhost:11434', 'timeout': 5}
        exc = OllamaConnectionError("Cannot connect to Ollama", details=details)
        
        assert exc.message == "Cannot connect to Ollama"
        assert exc.details['url'] == 'http://localhost:11434'
        assert exc.details['timeout'] == 5
    
    def test_database_connection_error(self):
        """Should create DatabaseConnectionError."""
        from src.exceptions import DatabaseConnectionError
        
        details = {'host': 'localhost', 'error': 'Connection refused'}
        exc = DatabaseConnectionError("Failed to connect to database", details=details)
        
        assert exc.message == "Failed to connect to database"
        assert exc.details['host'] == 'localhost'
    
    def test_document_processing_error(self):
        """Should create DocumentProcessingError."""
        from src.exceptions import DocumentProcessingError
        
        details = {'filename': 'test.pdf', 'error': 'Parse failed'}
        exc = DocumentProcessingError("Failed to process document", details=details)
        
        assert exc.message == "Failed to process document"
        assert exc.details['filename'] == 'test.pdf'
    
    def test_embedding_generation_error(self):
        """Should create EmbeddingGenerationError."""
        from src.exceptions import EmbeddingGenerationError
        
        details = {'model': 'nomic-embed-text', 'text_length': 1000}
        exc = EmbeddingGenerationError("Failed to generate embedding", details=details)
        
        assert exc.message == "Failed to generate embedding"
        assert exc.details['model'] == 'nomic-embed-text'
    
    def test_invalid_model_error(self):
        """Should create InvalidModelError."""
        from src.exceptions import InvalidModelError
        
        details = {'requested': 'unknown-model', 'available': ['llama3.2']}
        exc = InvalidModelError("Model not found", details=details)
        
        assert exc.message == "Model not found"
        assert exc.details['requested'] == 'unknown-model'
    
    def test_validation_error(self):
        """Should create ValidationError."""
        from src.exceptions import ValidationError
        
        details = {'field': 'message', 'constraint': 'min_length'}
        exc = ValidationError("Message cannot be empty", details=details)
        
        assert exc.message == "Message cannot be empty"
        assert exc.details['field'] == 'message'
    
    def test_configuration_error(self):
        """Should create ConfigurationError."""
        from src.exceptions import ConfigurationError
        
        details = {'env_var': 'PG_PASSWORD'}
        exc = ConfigurationError("Database password not configured", details=details)
        
        assert exc.message == "Database password not configured"
        assert exc.details['env_var'] == 'PG_PASSWORD'
    
    def test_file_upload_error(self):
        """Should create FileUploadError."""
        from src.exceptions import FileUploadError
        
        details = {'size': 20000000, 'max': 16000000}
        exc = FileUploadError("File too large", details=details)
        
        assert exc.message == "File too large"
        assert exc.details['size'] == 20000000


# ============================================================================
# EXCEPTION HIERARCHY TESTS (3 tests)
# ============================================================================

class TestExceptionHierarchy:
    """Test exception inheritance hierarchy."""
    
    def test_all_exceptions_inherit_from_base(self):
        """Should verify all custom exceptions inherit from LocalChatException."""
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
            FileUploadError
        )
        
        exceptions = [
            OllamaConnectionError("test"),
            DatabaseConnectionError("test"),
            DocumentProcessingError("test"),
            EmbeddingGenerationError("test"),
            InvalidModelError("test"),
            ValidationError("test"),
            ConfigurationError("test"),
            ChunkingError("test"),
            SearchError("test"),
            FileUploadError("test")
        ]
        
        for exc in exceptions:
            assert isinstance(exc, LocalChatException)
            assert isinstance(exc, Exception)
    
    def test_exception_isinstance_checks(self):
        """Should verify isinstance checks work correctly."""
        from src.exceptions import (
            LocalChatException,
            OllamaConnectionError,
            ValidationError
        )
        
        ollama_exc = OllamaConnectionError("test")
        validation_exc = ValidationError("test")
        
        # Positive checks
        assert isinstance(ollama_exc, OllamaConnectionError)
        assert isinstance(ollama_exc, LocalChatException)
        assert isinstance(validation_exc, ValidationError)
        assert isinstance(validation_exc, LocalChatException)
        
        # Negative checks
        assert not isinstance(ollama_exc, ValidationError)
        assert not isinstance(validation_exc, OllamaConnectionError)
    
    def test_exception_base_class_functionality(self):
        """Should verify base class methods work for all exceptions."""
        from src.exceptions import (
            OllamaConnectionError,
            ValidationError,
            DocumentProcessingError
        )
        
        exceptions = [
            OllamaConnectionError("test 1", details={'key': 'value1'}),
            ValidationError("test 2", details={'key': 'value2'}),
            DocumentProcessingError("test 3", details={'key': 'value3'})
        ]
        
        for exc in exceptions:
            # All should have message attribute
            assert hasattr(exc, 'message')
            assert isinstance(exc.message, str)
            
            # All should have details attribute
            assert hasattr(exc, 'details')
            assert isinstance(exc.details, dict)
            
            # All should have to_dict method
            assert hasattr(exc, 'to_dict')
            assert callable(exc.to_dict)


# ============================================================================
# EXCEPTION TO_DICT TESTS (3 tests)
# ============================================================================

class TestExceptionToDictMethod:
    """Test exception to_dict() method."""
    
    def test_to_dict_basic_exception(self):
        """Should convert exception to dictionary."""
        from src.exceptions import LocalChatException
        
        exc = LocalChatException("Test error")
        result = exc.to_dict()
        
        assert isinstance(result, dict)
        assert result['error'] == 'LocalChatException'
        assert result['message'] == 'Test error'
        assert result['details'] == {}
    
    def test_to_dict_with_details(self, sample_error_details):
        """Should convert exception with details to dictionary."""
        from src.exceptions import ValidationError
        
        exc = ValidationError("Invalid input", details=sample_error_details)
        result = exc.to_dict()
        
        assert result['error'] == 'ValidationError'
        assert result['message'] == 'Invalid input'
        assert result['details'] == sample_error_details
        assert result['details']['field'] == 'test_field'
    
    def test_to_dict_preserves_all_fields(self):
        """Should preserve all fields in dictionary conversion."""
        from src.exceptions import DatabaseConnectionError
        
        details = {
            'host': 'localhost',
            'port': 5432,
            'database': 'test_db',
            'error_code': 'CONN_REFUSED'
        }
        exc = DatabaseConnectionError("Connection failed", details=details)
        result = exc.to_dict()
        
        assert result['error'] == 'DatabaseConnectionError'
        assert result['message'] == 'Connection failed'
        assert len(result['details']) == 4
        assert result['details']['host'] == 'localhost'
        assert result['details']['port'] == 5432


# ============================================================================
# STATUS CODE MAPPING TESTS (2 tests)
# ============================================================================

class TestStatusCodeMapping:
    """Test HTTP status code mapping for exceptions."""
    
    def test_get_status_code_for_exceptions(self):
        """Should return correct status codes for different exceptions."""
        from src.exceptions import (
            ValidationError,
            InvalidModelError,
            OllamaConnectionError,
            DatabaseConnectionError,
            LocalChatException,
            get_status_code
        )
        
        # Test specific status codes
        assert get_status_code(ValidationError("test")) == 400
        assert get_status_code(InvalidModelError("test")) == 404
        assert get_status_code(OllamaConnectionError("test")) == 503
        assert get_status_code(DatabaseConnectionError("test")) == 500
        assert get_status_code(LocalChatException("test")) == 500
    
    def test_get_status_code_default(self):
        """Should return 500 for unknown exceptions."""
        from src.exceptions import get_status_code
        
        # Standard Python exception
        generic_exc = Exception("generic error")
        assert get_status_code(generic_exc) == 500
        
        # Custom exception not in mapping
        class CustomException(Exception):
            pass
        
        custom_exc = CustomException("custom error")
        assert get_status_code(custom_exc) == 500


# ============================================================================
# EXCEPTION STRING REPRESENTATION TESTS (2 tests)
# ============================================================================

class TestExceptionStringRepresentation:
    """Test exception string representation."""
    
    def test_exception_str_method(self):
        """Should return message when converted to string."""
        from src.exceptions import ValidationError
        
        exc = ValidationError("Invalid message format")
        
        assert str(exc) == "Invalid message format"
        assert exc.message in str(exc)
    
    def test_exception_repr_contains_class_name(self):
        """Should contain class name in representation."""
        from src.exceptions import OllamaConnectionError
        
        exc = OllamaConnectionError("Connection failed")
        
        # repr should contain class name
        assert 'OllamaConnectionError' in repr(exc)


# ============================================================================
# ADDITIONAL EXCEPTION TESTS (3 tests)
# ============================================================================

class TestAdditionalExceptions:
    """Test additional exception types."""
    
    def test_chunking_error(self):
        """Should create ChunkingError."""
        from src.exceptions import ChunkingError
        
        details = {'chunk_size': 0}
        exc = ChunkingError("Invalid chunk size", details=details)
        
        assert exc.message == "Invalid chunk size"
        assert exc.details['chunk_size'] == 0
    
    def test_search_error(self):
        """Should create SearchError."""
        from src.exceptions import SearchError
        
        details = {'error': 'Query failed'}
        exc = SearchError("Failed to search similar chunks", details=details)
        
        assert exc.message == "Failed to search similar chunks"
        assert exc.details['error'] == 'Query failed'
    
    def test_exception_with_none_details(self):
        """Should handle None details gracefully."""
        from src.exceptions import LocalChatException
        
        exc = LocalChatException("Test error", details=None)
        
        assert exc.details == {}
        assert exc.to_dict()['details'] == {}


# ============================================================================
# EXCEPTION USAGE SCENARIOS (2 tests)
# ============================================================================

class TestExceptionUsageScenarios:
    """Test real-world exception usage scenarios."""
    
    def test_catch_specific_exception(self):
        """Should catch specific exception type."""
        from src.exceptions import ValidationError, LocalChatException
        
        def validate_input(value: str):
            if not value:
                raise ValidationError("Value cannot be empty")
            return value
        
        # Should catch ValidationError
        with pytest.raises(ValidationError) as exc_info:
            validate_input("")
        
        assert exc_info.value.message == "Value cannot be empty"
        
        # Should also be catchable as LocalChatException
        with pytest.raises(LocalChatException):
            validate_input("")
    
    def test_exception_chaining(self):
        """Should support exception chaining."""
        from src.exceptions import DocumentProcessingError
        
        def process_document():
            try:
                raise ValueError("Parse error")
            except ValueError as e:
                raise DocumentProcessingError(
                    "Failed to process document",
                    details={'original_error': str(e)}
                ) from e
        
        with pytest.raises(DocumentProcessingError) as exc_info:
            process_document()
        
        assert exc_info.value.message == "Failed to process document"
        assert 'Parse error' in exc_info.value.details['original_error']
        assert exc_info.value.__cause__ is not None


# ============================================================================
# SUMMARY
# ============================================================================

# Total tests: 18 comprehensive tests
# Coverage target: 100% on src/exceptions.py
# Test categories:
#   - Exception Creation: 10 tests
#   - Exception Hierarchy: 3 tests
#   - Exception to_dict: 3 tests
#   - Status Code Mapping: 2 tests
#   - String Representation: 2 tests
#   - Additional Exceptions: 3 tests
#   - Usage Scenarios: 2 tests

# Run with:
# pytest tests/test_exceptions_comprehensive.py -v --cov=src.exceptions --cov-report=term-missing
