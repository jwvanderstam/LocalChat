"""
Unit tests for models.py (Pydantic validation models)

Tests all Pydantic models and their validators.
"""


import pytest
from pydantic import ValidationError

from src.models import (
    ChatRequest,
    ChunkingParameters,
    ModelDeleteRequest,
    ModelPullRequest,
    ModelRequest,
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

    def test_model_request_with_dots_and_colons(self):
        """Should accept dots and colons in model names."""
        request = ModelRequest(model="llama3.2:latest")
        assert request.model == "llama3.2:latest"


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
