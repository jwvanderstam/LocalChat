"""
Exception hierarchy: LocalChatException → OllamaConnectionError, DatabaseConnectionError,
DocumentProcessingError, EmbeddingGenerationError, InvalidModelError, ValidationError,
ConfigurationError, ChunkingError, SearchError, FileUploadError.
"""

from typing import Any

from .utils.logging_config import get_logger

logger = get_logger(__name__)


class LocalChatException(Exception):
    """Base class; logs a warning on construction and exposes to_dict() for API responses."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        self.message = message
        self.details = details or {}
        super().__init__(self.message)
        logger.warning(f"{self.__class__.__name__}: {message}", extra={"exception_details": self.details})

    def to_dict(self) -> dict[str, Any]:
        return {
            'error': self.__class__.__name__,
            'message': self.message,
            'details': self.details
        }


class OllamaConnectionError(LocalChatException):
    """Ollama service is unavailable or unreachable."""
    pass


class DatabaseConnectionError(LocalChatException):
    """PostgreSQL connection, authentication, or availability failure."""
    pass


class DocumentProcessingError(LocalChatException):
    """Document loading, parsing, chunking, or embedding failure."""
    pass


class EmbeddingGenerationError(LocalChatException):
    """Vector embedding generation failed."""
    pass


class InvalidModelError(LocalChatException):
    """Requested model not found in Ollama or not properly configured."""
    pass


class ValidationError(LocalChatException):
    """User input fails format, type, or constraint requirements."""
    pass


class ConfigurationError(LocalChatException):
    """Application configuration, environment variable, or settings file error."""
    pass


class ChunkingError(LocalChatException):
    """Text chunking failed (invalid chunk size or text format)."""
    pass


class SearchError(LocalChatException):
    """pgvector similarity search or query execution failed."""
    pass


class FileUploadError(LocalChatException):
    """File upload failed (too large, invalid format, or storage error)."""
    pass


# Exception mapping for HTTP status codes
EXCEPTION_STATUS_CODES = {
    ValidationError: 400,
    InvalidModelError: 404,
    OllamaConnectionError: 503,
    DatabaseConnectionError: 500,
    DocumentProcessingError: 500,
    EmbeddingGenerationError: 500,
    ConfigurationError: 500,
    ChunkingError: 500,
    SearchError: 500,
    FileUploadError: 400,
    LocalChatException: 500
}


def get_status_code(exception: Exception) -> int:
    return EXCEPTION_STATUS_CODES.get(type(exception), 500)


logger.info("Exception classes loaded")

