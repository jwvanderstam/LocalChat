"""
Pydantic Validation Models
==========================

Defines Pydantic models for request validation in the LocalChat application.
Ensures data integrity and provides automatic validation for API endpoints.

Models:
    - ChatRequest: Chat message validation
    - DocumentUploadRequest: Document upload validation
    - ModelRequest: Model selection validation
    - RetrievalRequest: RAG retrieval validation
    - ModelPullRequest: Model pull validation

Example:
    >>> from models import ChatRequest
    >>> request = ChatRequest(message="Hello", use_rag=True)
    >>> print(request.message)
    Hello

Author: LocalChat Team
Last Updated: 2024-12-27
"""

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import List, Optional, Dict, Any
from datetime import datetime
from . import config
from .utils.logging_config import get_logger

logger = get_logger(__name__)


class ChatRequest(BaseModel):
    """
    Validation model for chat requests.
    
    Validates chat messages, RAG mode, and conversation history.
    
    Attributes:
        message: User's message (1-5000 chars)
        use_rag: Whether to use RAG mode (default: True)
        history: Chat history (max 50 messages)
    
    Example:
        >>> request = ChatRequest(
        ...     message="What is in the documents?",
        ...     use_rag=True,
        ...     history=[]
        ... )
    """
    
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
    history: List[Dict[str, str]] = Field(
        default_factory=list,
        max_length=50,
        description="Chat conversation history"
    )
    
    @field_validator('message')
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        """Validate message is not empty or whitespace only."""
        if not v.strip():
            raise ValueError('Message cannot be empty or whitespace only')
        return v.strip()
    
    @field_validator('history')
    @classmethod
    def validate_history(cls, v: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Validate chat history format."""
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
    """
    Validation model for document uploads.
    
    Validates filename and file size constraints.
    
    Attributes:
        filename: Document filename
        file_size: File size in bytes
    
    Example:
        >>> request = DocumentUploadRequest(
        ...     filename="document.pdf",
        ...     file_size=1024000
        ... )
    """
    
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
        """Validate file extension is supported."""
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
    """
    Validation model for model selection.
    
    Validates model name format and constraints.
    
    Attributes:
        model: Model name
    
    Example:
        >>> request = ModelRequest(model="llama3.2:latest")
    """
    
    model: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Model name"
    )
    
    @field_validator('model')
    @classmethod
    def model_not_empty(cls, v: str) -> str:
        """Validate model name is not empty."""
        if not v.strip():
            raise ValueError('Model name cannot be empty')
        # Remove potentially dangerous characters
        if any(char in v for char in ['/', '\\', '..', '<', '>', '|', '&']):
            raise ValueError('Model name contains invalid characters')
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
    """
    Validation model for RAG retrieval requests.
    
    Validates query parameters for document retrieval.
    
    Attributes:
        query: Search query
        top_k: Number of results to retrieve
        min_similarity: Minimum similarity threshold
        file_type_filter: Optional file type filter
    
    Example:
        >>> request = RetrievalRequest(
        ...     query="What is this about?",
        ...     top_k=10,
        ...     min_similarity=0.25
        ... )
    """
    
    query: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Search query"
    )
    top_k: Optional[int] = Field(
        default=10,
        ge=1,
        le=50,
        description="Number of results to retrieve"
    )
    min_similarity: Optional[float] = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Minimum similarity threshold"
    )
    file_type_filter: Optional[str] = Field(
        default=None,
        description="File type filter (e.g., '.pdf')"
    )
    
    @field_validator('query')
    @classmethod
    def query_not_empty(cls, v: str) -> str:
        """Validate query is not empty."""
        if not v.strip():
            raise ValueError('Query cannot be empty')
        return v.strip()
    
    @field_validator('file_type_filter')
    @classmethod
    def valid_file_type(cls, v: Optional[str]) -> Optional[str]:
        """Validate file type filter if provided."""
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
    """
    Validation model for model pull requests.
    
    Validates model name for pulling from Ollama registry.
    
    Attributes:
        model: Model name to pull
    
    Example:
        >>> request = ModelPullRequest(model="llama3.2")
    """
    
    model: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Model name to pull"
    )
    
    @field_validator('model')
    @classmethod
    def valid_model_name(cls, v: str) -> str:
        """Validate model name format."""
        if not v.strip():
            raise ValueError('Model name cannot be empty')
        # Basic validation for model name format
        if not all(c.isalnum() or c in ['-', '_', '.', ':'] for c in v):
            raise ValueError('Model name contains invalid characters')
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
    """
    Validation model for model deletion requests.
    
    Validates model name for deletion.
    
    Attributes:
        model: Model name to delete
    
    Example:
        >>> request = ModelDeleteRequest(model="old-model:latest")
    """
    
    model: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Model name to delete"
    )
    
    @field_validator('model')
    @classmethod
    def model_not_empty(cls, v: str) -> str:
        """Validate model name is not empty."""
        if not v.strip():
            raise ValueError('Model name cannot be empty')
        return v.strip()


class ChunkingParameters(BaseModel):
    """
    Validation model for chunking parameters.
    
    Validates text chunking configuration.
    
    Attributes:
        chunk_size: Size of each chunk in characters
        chunk_overlap: Overlap between chunks
    
    Example:
        >>> params = ChunkingParameters(
        ...     chunk_size=768,
        ...     chunk_overlap=128
        ... )
    """
    
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
    def validate_overlap_less_than_size(self) -> 'ChunkingParameters':
        """Validate overlap is less than chunk size."""
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError('Chunk overlap must be less than chunk size')
        return self


class ErrorResponse(BaseModel):
    """
    Standard error response model.
    
    Provides consistent error response format across the API.
    
    Attributes:
        success: Always False for errors
        error: Error type/name
        message: Human-readable error message
        details: Additional error details
        timestamp: Error timestamp
    
    Example:
        >>> error = ErrorResponse(
        ...     error="ValidationError",
        ...     message="Invalid input",
        ...     details={"field": "message"}
        ... )
    """
    
    success: bool = Field(default=False, description="Success status")
    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Error message")
    details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional error details"
    )
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="Error timestamp"
    )
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": False,
                    "error": "ValidationError",
                    "message": "Message cannot be empty",
                    "details": {"field": "message"},
                    "timestamp": "2024-12-27T10:30:00Z"
                }
            ]
        }
    }


logger.info("Validation models loaded")
