# Python 3.14 compatibility: Use string annotations to avoid __annotate__ issues
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

_MODEL_NAME_EMPTY = 'Model name cannot be empty'
_MODEL_NAME_INVALID_CHARS = 'Model name contains invalid characters'
from . import config
from .utils.logging_config import get_logger

logger = get_logger(__name__)


class ChatRequest(BaseModel):

    message: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="User's chat message"
    )
    use_rag: bool = Field(
        default=True,
        description="Whether to use RAG mode for document context"
    )
    enhance: bool = Field(
        default=False,
        description="Whether to enrich RAG context with web search results"
    )
    history: list[dict[str, str]] = Field(
        default_factory=list,
        max_length=50,
        description="Chat conversation history"
    )
    conversation_id: str | None = Field(
        default=None,
        description="Conversation UUID for persistent memory (omit to start a new conversation)"
    )
    images: list[str] | None = Field(
        default=None,
        description="Optional list of base64-encoded images for vision-capable models"
    )
    temperature: float = Field(
        default=config.DEFAULT_TEMPERATURE,
        ge=0.0,
        le=2.0,
        description="Sampling temperature (0 = deterministic, 2 = very creative)"
    )
    model_override: str | None = Field(
        default=None,
        max_length=100,
        description="Override the model router selection — use this exact Ollama model ID"
    )
    additional_workspace_ids: list[str] | None = Field(
        default=None,
        description="Additional workspace UUIDs to include in cross-workspace retrieval"
    )
    active_source_ids: list[str] | None = Field(
        default=None,
        description="Connector or source IDs to restrict retrieval to; omit for all sources"
    )

    @field_validator('conversation_id')
    @classmethod
    def valid_uuid(cls, v: str | None) -> str | None:
        """Validate conversation_id is a well-formed UUID if provided."""
        import uuid as _uuid
        if v is not None:
            try:
                _uuid.UUID(v)
            except ValueError as e:
                raise ValueError('conversation_id must be a valid UUID') from e
        return v

    @field_validator('message')
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError('Message cannot be empty or whitespace only')
        return v.strip()

    @field_validator('history')
    @classmethod
    def validate_history(cls, v: list[dict[str, str]]) -> list[dict[str, str]]:
        for msg in v:
            if 'role' not in msg or 'content' not in msg:
                raise ValueError('History messages must have "role" and "content" fields')
            if msg['role'] not in ['user', 'assistant']:
                raise ValueError('Role must be "user" or "assistant"')
        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "message": "What is in the documents?",
                    "use_rag": True,
                    "history": [
                        {"role": "user", "content": "Hello"},
                        {"role": "assistant", "content": "Hi! How can I help?"}
                    ]
                }
            ]
        }
    }


class DocumentUploadRequest(BaseModel):

    filename: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Document filename"
    )
    file_size: int = Field(
        ...,
        gt=0,
        lt=16 * 1024 * 1024,  # 16MB
        description="File size in bytes"
    )

    @field_validator('filename')
    @classmethod
    def valid_extension(cls, v: str) -> str:
        if not any(v.lower().endswith(ext) for ext in config.SUPPORTED_EXTENSIONS):
            raise ValueError(
                f'File type not supported. Allowed: {", ".join(config.SUPPORTED_EXTENSIONS)}'
            )
        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "filename": "document.pdf",
                    "file_size": 1024000
                }
            ]
        }
    }


class ModelRequest(BaseModel):

    model: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Model name"
    )

    @field_validator('model')
    @classmethod
    def model_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError(_MODEL_NAME_EMPTY)
        # Remove potentially dangerous characters
        if any(char in v for char in ['/', '\\', '..', '<', '>', '|', '&']):
            raise ValueError(_MODEL_NAME_INVALID_CHARS)
        return v.strip()

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"model": "llama3.2:latest"},
                {"model": "nomic-embed-text"}
            ]
        }
    }


class RetrievalRequest(BaseModel):

    query: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Search query"
    )
    top_k: int | None = Field(
        default=10,
        ge=1,
        le=50,
        description="Number of results to retrieve"
    )
    min_similarity: float | None = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Minimum similarity threshold"
    )
    file_type_filter: str | None = Field(
        default=None,
        description="File type filter (e.g., '.pdf')"
    )

    @field_validator('query')
    @classmethod
    def query_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError('Query cannot be empty')
        return v.strip()

    @field_validator('file_type_filter')
    @classmethod
    def valid_file_type(cls, v: str | None) -> str | None:
        if v is not None:
            if not v.startswith('.'):
                raise ValueError('File type filter must start with a dot (e.g., ".pdf")')
            if v not in config.SUPPORTED_EXTENSIONS:
                raise ValueError(
                    f'Unsupported file type. Allowed: {", ".join(config.SUPPORTED_EXTENSIONS)}'
                )
        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "query": "What is this document about?",
                    "top_k": 10,
                    "min_similarity": 0.25,
                    "file_type_filter": None
                }
            ]
        }
    }


class ModelPullRequest(BaseModel):

    model: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Model name to pull"
    )

    @field_validator('model')
    @classmethod
    def valid_model_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError(_MODEL_NAME_EMPTY)
        # Basic validation for model name format
        if not all(c.isalnum() or c in ['-', '_', '.', ':'] for c in v):
            raise ValueError(_MODEL_NAME_INVALID_CHARS)
        return v.strip()

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"model": "llama3.2"},
                {"model": "mistral:7b-instruct"}
            ]
        }
    }


class ModelDeleteRequest(BaseModel):

    model: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Model name to delete"
    )

    @field_validator('model')
    @classmethod
    def model_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError(_MODEL_NAME_EMPTY)
        return v.strip()


class ChunkingParameters(BaseModel):

    chunk_size: int = Field(
        default=768,
        ge=100,
        le=2000,
        description="Chunk size in characters"
    )
    chunk_overlap: int = Field(
        default=128,
        ge=0,
        le=500,
        description="Overlap between chunks"
    )

    @model_validator(mode='after')
    def validate_overlap_less_than_size(self) -> ChunkingParameters:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError('Chunk overlap must be less than chunk size')
        return self


class ErrorResponse(BaseModel):
    """Standard error response shape for all API error returns."""

    success: bool = Field(default=False, description="Success status")
    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Error message")
    details: dict[str, Any] | None = Field(
        default_factory=dict,
        description="Additional error details"
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="Error timestamp in ISO format"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": False,
                    "error": "ValidationError",
                    "message": "Message cannot be empty",
                    "details": {"field": "message"},
                    "timestamp": "2024-12-27T10:30:00.000Z"
                }
            ]
        }
    }


logger.info("Validation models loaded")
