"""
Custom Exception Classes
========================

Defines custom exceptions for the LocalChat RAG application.
Provides specific exception types for different error scenarios.

Exception Hierarchy:
    LocalChatException (base)
    ??? OllamaConnectionError
    ??? DatabaseConnectionError
    ??? DocumentProcessingError
    ??? EmbeddingGenerationError
    ??? InvalidModelError
    ??? ValidationError
    ??? ConfigurationError

Example:
    >>> from exceptions import OllamaConnectionError
    >>> if not ollama_available:
    ...     raise OllamaConnectionError("Ollama service is not running")

Author: LocalChat Team
Last Updated: 2024-12-27
"""

from typing import Optional, Dict, Any
from .utils.logging_config import get_logger

logger = get_logger(__name__)


class LocalChatException(Exception):
    """
    Base exception class for LocalChat application.
    
    All custom exceptions inherit from this class for consistent
    error handling and logging.
    
    Attributes:
        message (str): Error message
        details (Dict[str, Any]): Additional error details
    
    Example:
        >>> raise LocalChatException("Something went wrong")
    """
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        """
        Initialize LocalChat exception.
        
        Args:
            message: Human-readable error message
            details: Optional dictionary with additional error context
        """
        self.message = message
        self.details = details or {}
        super().__init__(self.message)
        logger.error(f"{self.__class__.__name__}: {message}", extra={"exception_details": self.details})
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert exception to dictionary for API responses.
        
        Returns:
            Dictionary with error information
        """
        return {
            'error': self.__class__.__name__,
            'message': self.message,
            'details': self.details
        }


class OllamaConnectionError(LocalChatException):
    """
    Raised when Ollama service is unavailable or unreachable.
    
    This exception indicates that the application cannot connect
    to the Ollama API server.
    
    Example:
        >>> if not ollama_client.is_available:
        ...     raise OllamaConnectionError(
        ...         "Cannot connect to Ollama at http://localhost:11434",
        ...         details={'url': ollama_base_url, 'timeout': 5}
        ...     )
    """
    pass


class DatabaseConnectionError(LocalChatException):
    """
    Raised when database connection fails.
    
    This exception indicates issues with PostgreSQL connection,
    authentication, or database availability.
    
    Example:
        >>> try:
        ...     db.connect()
        ... except psycopg.OperationalError as e:
        ...     raise DatabaseConnectionError(
        ...         "Failed to connect to database",
        ...         details={'host': db_host, 'error': str(e)}
        ...     )
    """
    pass


class DocumentProcessingError(LocalChatException):
    """
    Raised when document ingestion or processing fails.
    
    This exception covers errors during document loading,
    parsing, chunking, or embedding generation.
    
    Example:
        >>> try:
        ...     doc_processor.ingest_document(file_path)
        ... except Exception as e:
        ...     raise DocumentProcessingError(
        ...         f"Failed to process document: {filename}",
        ...         details={'filename': filename, 'error': str(e)}
        ...     )
    """
    pass


class EmbeddingGenerationError(LocalChatException):
    """
    Raised when embedding generation fails.
    
    This exception indicates issues with generating vector embeddings
    for text chunks using the embedding model.
    
    Example:
        >>> success, embedding = generate_embedding(text)
        >>> if not success:
        ...     raise EmbeddingGenerationError(
        ...         "Failed to generate embedding",
        ...         details={'model': model_name, 'text_length': len(text)}
        ...     )
    """
    pass


class InvalidModelError(LocalChatException):
    """
    Raised when specified model is not found or invalid.
    
    This exception indicates that the requested model does not
    exist in Ollama or is not properly configured.
    
    Example:
        >>> if model_name not in available_models:
        ...     raise InvalidModelError(
        ...         f"Model '{model_name}' not found",
        ...         details={'requested': model_name, 'available': available_models}
        ...     )
    """
    pass


class ValidationError(LocalChatException):
    """
    Raised when input validation fails.
    
    This exception indicates that user input does not meet
    validation requirements (format, type, constraints).
    
    Example:
        >>> if len(message) == 0:
        ...     raise ValidationError(
        ...         "Message cannot be empty",
        ...         details={'field': 'message', 'constraint': 'min_length'}
        ...     )
    """
    pass


class ConfigurationError(LocalChatException):
    """
    Raised when configuration is invalid or missing.
    
    This exception indicates issues with application configuration,
    environment variables, or settings files.
    
    Example:
        >>> if not pg_password:
        ...     raise ConfigurationError(
        ...         "Database password not configured",
        ...         details={'env_var': 'PG_PASSWORD'}
        ...     )
    """
    pass


class ChunkingError(LocalChatException):
    """
    Raised when text chunking fails.
    
    This exception indicates issues during the text chunking process,
    such as invalid chunk size or text format errors.
    
    Example:
        >>> if chunk_size <= 0:
        ...     raise ChunkingError(
        ...         "Invalid chunk size",
        ...         details={'chunk_size': chunk_size}
        ...     )
    """
    pass


class SearchError(LocalChatException):
    """
    Raised when vector similarity search fails.
    
    This exception indicates issues with the pgvector similarity
    search operation or query execution.
    
    Example:
        >>> try:
        ...     results = db.search_similar_chunks(embedding)
        ... except Exception as e:
        ...     raise SearchError(
        ...         "Failed to search similar chunks",
        ...         details={'error': str(e)}
        ...     )
    """
    pass


class FileUploadError(LocalChatException):
    """
    Raised when file upload fails.
    
    This exception indicates issues with file upload, such as
    file too large, invalid format, or storage errors.
    
    Example:
        >>> if file_size > MAX_FILE_SIZE:
        ...     raise FileUploadError(
        ...         "File too large",
        ...         details={'size': file_size, 'max': MAX_FILE_SIZE}
        ...     )
    """
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
    """
    Get HTTP status code for exception.
    
    Args:
        exception: Exception instance
    
    Returns:
        HTTP status code (default: 500)
    
    Example:
        >>> exc = ValidationError("Invalid input")
        >>> status = get_status_code(exc)
        >>> print(status)
        400
    """
    return EXCEPTION_STATUS_CODES.get(type(exception), 500)


logger.info("Exception classes loaded")

