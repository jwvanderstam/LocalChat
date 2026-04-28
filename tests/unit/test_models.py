"""
Unit tests for models.py (Pydantic validation models)

Tests all Pydantic models and their validators.
"""


import pytest
from pydantic import ValidationError

from src.models import (
    ChatRequest,
    ChunkingParameters,
    DocumentUploadRequest,
    ErrorResponse,
    ModelDeleteRequest,
    ModelPullRequest,
    ModelRequest,
    RetrievalRequest,
)

# ============================================================================
# CHATREQUEST TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.validation
class TestChatRequest:
    """Tests for ChatRequest model."""

    def test_creates_valid_chat_request(self):
        """Should create valid chat request."""
        request = ChatRequest(
            message="What is this about?",
            use_rag=True,
            history=[]
        )
        assert request.message == "What is this about?"
        assert request.use_rag is True
        assert request.history == []

    def test_rejects_empty_message(self):
        """Should reject empty message."""
        with pytest.raises(ValidationError):
            ChatRequest(message="", use_rag=True)

    def test_rejects_whitespace_only_message(self):
        """Should reject whitespace-only message."""
        with pytest.raises(ValidationError):
            ChatRequest(message="   ", use_rag=True)

    def test_trims_message_whitespace(self):
        """Should trim message whitespace."""
        request = ChatRequest(message="  Hello  ", use_rag=True)
        assert request.message == "Hello"

    def test_rejects_message_too_long(self):
        """Should reject message exceeding max length."""
        long_message = "a" * 6000
        with pytest.raises(ValidationError):
            ChatRequest(message=long_message, use_rag=True)

    def test_use_rag_defaults_to_true(self):
        """Should default use_rag to True."""
        request = ChatRequest(message="Hello")
        assert request.use_rag is True

    def test_history_defaults_to_empty_list(self):
        """Should default history to empty list."""
        request = ChatRequest(message="Hello")
        assert request.history == []

    def test_validates_history_format(self):
        """Should validate history message format."""
        valid_history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"}
        ]
        request = ChatRequest(message="Test", history=valid_history)
        assert len(request.history) == 2

    def test_rejects_invalid_history_format(self):
        """Should reject invalid history format."""
        invalid_history = [{"invalid": "format"}]
        with pytest.raises(ValidationError):
            ChatRequest(message="Test", history=invalid_history)

    def test_rejects_invalid_role_in_history(self):
        """Should reject invalid role in history."""
        invalid_history = [{"role": "invalid", "content": "Test"}]
        with pytest.raises(ValidationError):
            ChatRequest(message="Test", history=invalid_history)

    def test_rejects_history_too_long(self):
        """Should reject history exceeding max length."""
        long_history = [
            {"role": "user", "content": f"Message {i}"}
            for i in range(51)
        ]
        with pytest.raises(ValidationError):
            ChatRequest(message="Test", history=long_history)


# ============================================================================
# DOCUMENTUPLOADREQUEST TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.validation
class TestDocumentUploadRequest:
    """Tests for DocumentUploadRequest model."""

    def test_creates_valid_upload_request(self):
        """Should create valid upload request."""
        request = DocumentUploadRequest(
            filename="document.pdf",
            file_size=1024000
        )
        assert request.filename == "document.pdf"
        assert request.file_size == 1024000

    def test_rejects_empty_filename(self):
        """Should reject empty filename."""
        with pytest.raises(ValidationError):
            DocumentUploadRequest(filename="", file_size=1000)

    def test_rejects_unsupported_extension(self):
        """Should reject unsupported file extension."""
        with pytest.raises(ValidationError):
            DocumentUploadRequest(filename="file.exe", file_size=1000)

    def test_accepts_pdf_extension(self):
        """Should accept PDF files."""
        request = DocumentUploadRequest(filename="doc.pdf", file_size=1000)
        assert request.filename == "doc.pdf"

    def test_accepts_txt_extension(self):
        """Should accept TXT files."""
        request = DocumentUploadRequest(filename="doc.txt", file_size=1000)
        assert request.filename == "doc.txt"

    def test_accepts_docx_extension(self):
        """Should accept DOCX files."""
        request = DocumentUploadRequest(filename="doc.docx", file_size=1000)
        assert request.filename == "doc.docx"

    def test_rejects_zero_file_size(self):
        """Should reject zero file size."""
        with pytest.raises(ValidationError):
            DocumentUploadRequest(filename="doc.pdf", file_size=0)

    def test_rejects_negative_file_size(self):
        """Should reject negative file size."""
        with pytest.raises(ValidationError):
            DocumentUploadRequest(filename="doc.pdf", file_size=-1)

    def test_rejects_file_too_large(self):
        """Should reject files larger than 16MB."""
        with pytest.raises(ValidationError):
            DocumentUploadRequest(
                filename="doc.pdf",
                file_size=17 * 1024 * 1024
            )


# ============================================================================
# MODELREQUEST TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.validation
class TestModelRequest:
    """Tests for ModelRequest model."""

    def test_creates_valid_model_request(self):
        """Should create valid model request."""
        request = ModelRequest(model="llama3.2")
        assert request.model == "llama3.2"

    def test_rejects_empty_model_name(self):
        """Should reject empty model name."""
        with pytest.raises(ValidationError):
            ModelRequest(model="")

    def test_rejects_whitespace_only_model(self):
        """Should reject whitespace-only model name."""
        with pytest.raises(ValidationError):
            ModelRequest(model="   ")

    def test_trims_model_whitespace(self):
        """Should trim model name whitespace."""
        request = ModelRequest(model="  llama3.2  ")
        assert request.model == "llama3.2"

    def test_rejects_dangerous_characters(self):
        """Should reject dangerous characters in model name."""
        dangerous_names = [
            "../model",
            "model/path",
            "model\\path",
            "model<script>",
            "model|pipe",
            "model&ampersand"
        ]
        for name in dangerous_names:
            with pytest.raises(ValidationError):
                ModelRequest(model=name)

    def test_accepts_valid_model_names(self):
        """Should accept valid model names."""
        valid_names = [
            "llama3.2",
            "llama3.2:latest",
            "model-name",
            "model_name",
            "model.v1.2.3"
        ]
        for name in valid_names:
            request = ModelRequest(model=name)
            assert request.model == name


# ============================================================================
# RETRIEVALREQUEST TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.validation
class TestRetrievalRequest:
    """Tests for RetrievalRequest model."""

    def test_creates_valid_retrieval_request(self):
        """Should create valid retrieval request."""
        request = RetrievalRequest(
            query="What is this about?",
            top_k=10,
            min_similarity=0.25
        )
        assert request.query == "What is this about?"
        assert request.top_k == 10
        assert request.min_similarity == 0.25

    def test_rejects_empty_query(self):
        """Should reject empty query."""
        with pytest.raises(ValidationError):
            RetrievalRequest(query="")

    def test_trims_query_whitespace(self):
        """Should trim query whitespace."""
        request = RetrievalRequest(query="  test query  ")
        assert request.query == "test query"

    def test_top_k_defaults_to_10(self):
        """Should default top_k to 10."""
        request = RetrievalRequest(query="test")
        assert request.top_k == 10

    def test_rejects_top_k_zero(self):
        """Should reject top_k of zero."""
        with pytest.raises(ValidationError):
            RetrievalRequest(query="test", top_k=0)

    def test_rejects_top_k_negative(self):
        """Should reject negative top_k."""
        with pytest.raises(ValidationError):
            RetrievalRequest(query="test", top_k=-1)

    def test_rejects_top_k_too_large(self):
        """Should reject top_k larger than 50."""
        with pytest.raises(ValidationError):
            RetrievalRequest(query="test", top_k=51)

    def test_min_similarity_defaults_to_025(self):
        """Should default min_similarity to 0.25."""
        request = RetrievalRequest(query="test")
        assert request.min_similarity == 0.25

    def test_rejects_min_similarity_negative(self):
        """Should reject negative min_similarity."""
        with pytest.raises(ValidationError):
            RetrievalRequest(query="test", min_similarity=-0.1)

    def test_rejects_min_similarity_greater_than_one(self):
        """Should reject min_similarity greater than 1.0."""
        with pytest.raises(ValidationError):
            RetrievalRequest(query="test", min_similarity=1.1)

    def test_accepts_valid_file_type_filter(self):
        """Should accept valid file type filter."""
        request = RetrievalRequest(query="test", file_type_filter=".pdf")
        assert request.file_type_filter == ".pdf"

    def test_rejects_file_type_without_dot(self):
        """Should reject file type filter without dot."""
        with pytest.raises(ValidationError):
            RetrievalRequest(query="test", file_type_filter="pdf")

    def test_rejects_unsupported_file_type(self):
        """Should reject unsupported file type."""
        with pytest.raises(ValidationError):
            RetrievalRequest(query="test", file_type_filter=".exe")


# ============================================================================
# MODELPULLREQUEST TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.validation
class TestModelPullRequest:
    """Tests for ModelPullRequest model."""

    def test_creates_valid_pull_request(self):
        """Should create valid pull request."""
        request = ModelPullRequest(model="llama3.2")
        assert request.model == "llama3.2"

    def test_rejects_empty_model_name(self):
        """Should reject empty model name."""
        with pytest.raises(ValidationError):
            ModelPullRequest(model="")

    def test_accepts_model_with_tag(self):
        """Should accept model with version tag."""
        request = ModelPullRequest(model="mistral:7b-instruct")
        assert request.model == "mistral:7b-instruct"

    def test_rejects_invalid_characters(self):
        """Should reject invalid characters."""
        with pytest.raises(ValidationError):
            ModelPullRequest(model="model<script>")


# ============================================================================
# MODELDELETEREQUEST TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.validation
class TestModelDeleteRequest:
    """Tests for ModelDeleteRequest model."""

    def test_creates_valid_delete_request(self):
        """Should create valid delete request."""
        request = ModelDeleteRequest(model="old-model")
        assert request.model == "old-model"

    def test_rejects_empty_model_name(self):
        """Should reject empty model name."""
        with pytest.raises(ValidationError):
            ModelDeleteRequest(model="")

    def test_trims_model_whitespace(self):
        """Should trim model whitespace."""
        request = ModelDeleteRequest(model="  model  ")
        assert request.model == "model"


# ============================================================================
# CHUNKINGPARAMETERS TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.validation
class TestChunkingParameters:
    """Tests for ChunkingParameters model."""

    def test_creates_with_defaults(self):
        """Should create with default values."""
        params = ChunkingParameters()
        assert params.chunk_size == 768
        assert params.chunk_overlap == 128

    def test_creates_with_custom_values(self):
        """Should create with custom values."""
        params = ChunkingParameters(chunk_size=500, chunk_overlap=50)
        assert params.chunk_size == 500
        assert params.chunk_overlap == 50

    def test_rejects_chunk_size_too_small(self):
        """Should reject chunk size below minimum."""
        with pytest.raises(ValidationError):
            ChunkingParameters(chunk_size=50)

    def test_rejects_chunk_size_too_large(self):
        """Should reject chunk size above maximum."""
        with pytest.raises(ValidationError):
            ChunkingParameters(chunk_size=3000)

    def test_rejects_negative_overlap(self):
        """Should reject negative overlap."""
        with pytest.raises(ValidationError):
            ChunkingParameters(chunk_overlap=-1)

    def test_rejects_overlap_equal_to_size(self):
        """Should reject overlap equal to chunk size."""
        with pytest.raises(ValidationError):
            ChunkingParameters(chunk_size=500, chunk_overlap=500)

    def test_rejects_overlap_greater_than_size(self):
        """Should reject overlap greater than chunk size."""
        with pytest.raises(ValidationError):
            ChunkingParameters(chunk_size=500, chunk_overlap=600)


# ============================================================================
# ERRORRESPONSE TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.validation
class TestErrorResponse:
    """Tests for ErrorResponse model."""

    def test_creates_valid_error_response(self):
        """Should create valid error response."""
        error = ErrorResponse(
            error="ValidationError",
            message="Invalid input"
        )
        assert error.success is False
        assert error.error == "ValidationError"
        assert error.message == "Invalid input"

    def test_success_always_false(self):
        """Should always set success to False."""
        error = ErrorResponse(error="Error", message="Message")
        assert error.success is False

    def test_includes_timestamp(self):
        """Should include timestamp."""
        error = ErrorResponse(error="Error", message="Message")
        # timestamp is serialized as an ISO string
        assert isinstance(error.timestamp, str)
        assert "T" in error.timestamp  # ISO 8601 format

    def test_includes_optional_details(self):
        """Should include optional details."""
        error = ErrorResponse(
            error="ValidationError",
            message="Invalid",
            details={"field": "message"}
        )
        assert error.details == {"field": "message"}

    def test_details_defaults_to_none(self):
        """Should default details to empty dict when not provided."""
        error = ErrorResponse(error="Error", message="Message")
        assert error.details == {} or error.details is None


# ============================================================================
# EDGE CASES
# ============================================================================

@pytest.mark.unit
@pytest.mark.validation
class TestModelsEdgeCases:
    """Edge case tests for Pydantic models."""

    def test_chat_request_with_unicode(self):
        """Should handle Unicode in chat message."""
        request = ChatRequest(message="Hello ?? ??")
        assert "??" in request.message

    def test_retrieval_request_with_very_long_query(self):
        """Should reject very long queries."""
        long_query = "a" * 1001
        with pytest.raises(ValidationError):
            RetrievalRequest(query=long_query)

    def test_document_upload_with_case_insensitive_extension(self):
        """Should handle case-insensitive extensions."""
        request = DocumentUploadRequest(filename="doc.PDF", file_size=1000)
        assert request.filename == "doc.PDF"

    def test_model_request_with_dots_and_colons(self):
        """Should accept dots and colons in model names."""
        request = ModelRequest(model="llama3.2:latest")
        assert request.model == "llama3.2:latest"

    def test_error_response_with_complex_details(self):
        """Should handle complex details object."""
        details = {
            "errors": [
                {"field": "message", "error": "too long"},
                {"field": "top_k", "error": "too large"}
            ],
            "count": 2
        }
        error = ErrorResponse(
            error="MultipleErrors",
            message="Multiple validation errors",
            details=details
        )
        assert error.details["count"] == 2


# ============================================================================
# DEFAULT_TEMPERATURE consistency
# ============================================================================

@pytest.mark.unit
class TestChatRequestTemperatureDefault:
    """Ensure ChatRequest temperature default matches config.DEFAULT_TEMPERATURE."""

    def test_default_temperature_matches_config(self):
        """ChatRequest().temperature must equal config.DEFAULT_TEMPERATURE."""
        from src import config
        request = ChatRequest(message="hello")
        assert request.temperature == config.DEFAULT_TEMPERATURE

    def test_explicit_temperature_overrides_default(self):
        """An explicitly provided temperature is not clamped to the config default."""
        request = ChatRequest(message="hello", temperature=0.9)
        assert request.temperature == 0.9
