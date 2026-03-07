"""
Comprehensive Validation Tests - Week 3 Day 2
=============================================

Tests the Pydantic validation models from src/models.py.
Target: 15+ tests, high coverage on models.py

Run: pytest tests/test_validation_comprehensive.py -v --cov=src.models --cov-report=term-missing
"""

import pytest
import os
from unittest.mock import patch
from pydantic import ValidationError as PydanticValidationError

# Mark all tests
pytestmark = [pytest.mark.unit, pytest.mark.validation]

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
# CHATREQUEST VALIDATION TESTS (5 tests)
# ============================================================================

class TestChatRequestValidation:
    """Test ChatRequest validation model."""
    
    def test_chat_request_valid(self):
        """Should create valid ChatRequest."""
        from src.models import ChatRequest
        
        request = ChatRequest(
            message="What is in the documents?",
            use_rag=True,
            history=[]
        )
        
        assert request.message == "What is in the documents?"
        assert request.use_rag is True
        assert request.history == []
    
    def test_chat_request_strips_whitespace(self):
        """Should strip whitespace from message."""
        from src.models import ChatRequest
        
        request = ChatRequest(message="  Hello  ")
        
        assert request.message == "Hello"
    
    def test_chat_request_empty_message_fails(self):
        """Should reject empty message."""
        from src.models import ChatRequest
        
        with pytest.raises(PydanticValidationError) as exc_info:
            ChatRequest(message="")
        
        # Pydantic returns "string_too_short" error
        assert ("cannot be empty" in str(exc_info.value).lower() or 
                "at least 1 character" in str(exc_info.value).lower())
    
    def test_chat_request_whitespace_only_fails(self):
        """Should reject whitespace-only message."""
        from src.models import ChatRequest
        
        with pytest.raises(PydanticValidationError) as exc_info:
            ChatRequest(message="   ")
        
        assert "cannot be empty" in str(exc_info.value).lower() or "whitespace" in str(exc_info.value).lower()
    
    def test_chat_request_invalid_history_format(self):
        """Should reject invalid history format."""
        from src.models import ChatRequest
        
        # Missing 'content' field
        with pytest.raises(PydanticValidationError):
            ChatRequest(
                message="test",
                history=[{"role": "user"}]  # Missing content
            )
        
        # Invalid role
        with pytest.raises(PydanticValidationError):
            ChatRequest(
                message="test",
                history=[{"role": "invalid", "content": "test"}]
            )


# ============================================================================
# DOCUMENTUPLOADREQUEST VALIDATION TESTS (4 tests)
# ============================================================================

class TestDocumentUploadRequestValidation:
    """Test DocumentUploadRequest validation model."""
    
    def test_document_upload_valid(self):
        """Should create valid DocumentUploadRequest."""
        from src.models import DocumentUploadRequest
        
        request = DocumentUploadRequest(
            filename="document.pdf",
            file_size=1024000
        )
        
        assert request.filename == "document.pdf"
        assert request.file_size == 1024000
    
    def test_document_upload_invalid_extension(self):
        """Should reject invalid file extension."""
        from src.models import DocumentUploadRequest
        
        with pytest.raises(PydanticValidationError) as exc_info:
            DocumentUploadRequest(
                filename="document.exe",  # Invalid extension
                file_size=1024
            )
        
        assert "not supported" in str(exc_info.value).lower()
    
    def test_document_upload_file_too_large(self):
        """Should reject file that's too large."""
        from src.models import DocumentUploadRequest
        
        with pytest.raises(PydanticValidationError):
            DocumentUploadRequest(
                filename="document.pdf",
                file_size=20 * 1024 * 1024  # 20MB (over 16MB limit)
            )
    
    def test_document_upload_file_size_zero(self):
        """Should reject zero file size."""
        from src.models import DocumentUploadRequest
        
        with pytest.raises(PydanticValidationError):
            DocumentUploadRequest(
                filename="document.pdf",
                file_size=0
            )


# ============================================================================
# MODELREQUEST VALIDATION TESTS (3 tests)
# ============================================================================

class TestModelRequestValidation:
    """Test ModelRequest validation model."""
    
    def test_model_request_valid(self):
        """Should create valid ModelRequest."""
        from src.models import ModelRequest
        
        request = ModelRequest(model="llama3.2:latest")
        
        assert request.model == "llama3.2:latest"
    
    def test_model_request_strips_whitespace(self):
        """Should strip whitespace from model name."""
        from src.models import ModelRequest
        
        request = ModelRequest(model="  llama3.2  ")
        
        assert request.model == "llama3.2"
    
    def test_model_request_invalid_characters(self):
        """Should reject model names with invalid characters."""
        from src.models import ModelRequest
        
        invalid_names = [
            "model/../etc",
            "model\\path",
            "model<script>",
            "model|command"
        ]
        
        for invalid_name in invalid_names:
            with pytest.raises(PydanticValidationError):
                ModelRequest(model=invalid_name)


# ============================================================================
# RETRIEVALREQUEST VALIDATION TESTS (5 tests)
# ============================================================================

class TestRetrievalRequestValidation:
    """Test RetrievalRequest validation model."""
    
    def test_retrieval_request_valid(self):
        """Should create valid RetrievalRequest."""
        from src.models import RetrievalRequest
        
        request = RetrievalRequest(
            query="What is this about?",
            top_k=10,
            min_similarity=0.25
        )
        
        assert request.query == "What is this about?"
        assert request.top_k == 10
        assert request.min_similarity == 0.25
    
    def test_retrieval_request_default_values(self):
        """Should use default values when not specified."""
        from src.models import RetrievalRequest
        
        request = RetrievalRequest(query="test query")
        
        assert request.top_k == 10  # Default
        assert request.min_similarity == 0.25  # Default
        assert request.file_type_filter is None  # Default
    
    def test_retrieval_request_invalid_top_k(self):
        """Should reject invalid top_k values."""
        from src.models import RetrievalRequest
        
        # top_k too small
        with pytest.raises(PydanticValidationError):
            RetrievalRequest(query="test", top_k=0)
        
        # top_k too large
        with pytest.raises(PydanticValidationError):
            RetrievalRequest(query="test", top_k=100)
    
    def test_retrieval_request_invalid_similarity(self):
        """Should reject invalid similarity threshold."""
        from src.models import RetrievalRequest
        
        # Similarity too low
        with pytest.raises(PydanticValidationError):
            RetrievalRequest(query="test", min_similarity=-0.1)
        
        # Similarity too high
        with pytest.raises(PydanticValidationError):
            RetrievalRequest(query="test", min_similarity=1.5)
    
    def test_retrieval_request_invalid_file_type(self):
        """Should reject invalid file type filter."""
        from src.models import RetrievalRequest
        
        # Missing dot
        with pytest.raises(PydanticValidationError):
            RetrievalRequest(query="test", file_type_filter="pdf")
        
        # Unsupported extension
        with pytest.raises(PydanticValidationError):
            RetrievalRequest(query="test", file_type_filter=".exe")


# ============================================================================
# MODELPULLREQUEST VALIDATION TESTS (2 tests)
# ============================================================================

class TestModelPullRequestValidation:
    """Test ModelPullRequest validation model."""
    
    def test_model_pull_request_valid(self):
        """Should create valid ModelPullRequest."""
        from src.models import ModelPullRequest
        
        request = ModelPullRequest(model="llama3.2")
        
        assert request.model == "llama3.2"
    
    def test_model_pull_request_invalid_characters(self):
        """Should reject model names with invalid characters."""
        from src.models import ModelPullRequest
        
        with pytest.raises(PydanticValidationError):
            ModelPullRequest(model="model@invalid")


# ============================================================================
# CHUNKINGPARAMETERS VALIDATION TESTS (3 tests)
# ============================================================================

class TestChunkingParametersValidation:
    """Test ChunkingParameters validation model."""
    
    def test_chunking_parameters_valid(self):
        """Should create valid ChunkingParameters."""
        from src.models import ChunkingParameters
        
        params = ChunkingParameters(
            chunk_size=768,
            chunk_overlap=128
        )
        
        assert params.chunk_size == 768
        assert params.chunk_overlap == 128
    
    def test_chunking_parameters_defaults(self):
        """Should use default values."""
        from src.models import ChunkingParameters
        
        params = ChunkingParameters()
        
        assert params.chunk_size == 768
        assert params.chunk_overlap == 128
    
    def test_chunking_parameters_overlap_too_large(self):
        """Should reject overlap >= chunk_size."""
        from src.models import ChunkingParameters
        
        with pytest.raises(PydanticValidationError) as exc_info:
            ChunkingParameters(
                chunk_size=500,
                chunk_overlap=500  # Equal to chunk_size
            )
        
        assert "less than" in str(exc_info.value).lower()


# ============================================================================
# ERRORRESPONSE VALIDATION TESTS (2 tests)
# ============================================================================

class TestErrorResponseValidation:
    """Test ErrorResponse validation model."""
    
    def test_error_response_basic(self):
        """Should create basic ErrorResponse."""
        from src.models import ErrorResponse
        
        error = ErrorResponse(
            error="ValidationError",
            message="Invalid input"
        )
        
        assert error.success is False
        assert error.error == "ValidationError"
        assert error.message == "Invalid input"
        assert error.details == {}
        assert error.timestamp is not None
    
    def test_error_response_with_details(self):
        """Should create ErrorResponse with details."""
        from src.models import ErrorResponse
        
        details = {"field": "message", "constraint": "min_length"}
        error = ErrorResponse(
            error="ValidationError",
            message="Invalid input",
            details=details
        )
        
        assert error.details == details
        assert error.details["field"] == "message"


# ============================================================================
# EDGE CASE TESTS (3 tests)
# ============================================================================

class TestValidationEdgeCases:
    """Test edge cases in validation."""
    
    def test_message_max_length(self):
        """Should reject message exceeding max length."""
        from src.models import ChatRequest
        
        # Message just under limit should pass
        long_message = "a" * 5000
        request = ChatRequest(message=long_message)
        assert len(request.message) == 5000
        
        # Message over limit should fail
        with pytest.raises(PydanticValidationError):
            too_long = "a" * 5001
            ChatRequest(message=too_long)
    
    def test_valid_file_extensions(self):
        """Should accept all valid file extensions."""
        from src.models import DocumentUploadRequest
        
        valid_extensions = [".pdf", ".txt", ".docx", ".md"]
        
        for ext in valid_extensions:
            request = DocumentUploadRequest(
                filename=f"document{ext}",
                file_size=1024
            )
            assert request.filename.endswith(ext)
    
    def test_history_max_length(self):
        """Should reject history exceeding max length."""
        from src.models import ChatRequest
        
        # Create history with 51 messages (over limit of 50)
        long_history = [
            {"role": "user", "content": f"message {i}"}
            for i in range(51)
        ]
        
        with pytest.raises(PydanticValidationError):
            ChatRequest(message="test", history=long_history)


# ============================================================================
# SUMMARY
# ============================================================================

# Total tests: 27 comprehensive tests
# Coverage target: High coverage on src/models.py
# Test categories:
#   - ChatRequest: 5 tests
#   - DocumentUploadRequest: 4 tests
#   - ModelRequest: 3 tests
#   - RetrievalRequest: 5 tests
#   - ModelPullRequest: 2 tests
#   - ChunkingParameters: 3 tests
#   - ErrorResponse: 2 tests
#   - Edge Cases: 3 tests

# Run with:
# pytest tests/test_validation_comprehensive.py -v --cov=src.models --cov-report=term-missing
