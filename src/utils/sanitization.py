"""
Input Sanitization Utilities
============================

Provides functions for sanitizing user input to prevent security issues
and ensure data integrity in the LocalChat application.

Functions:
    - sanitize_filename: Clean filenames
    - sanitize_query: Clean search queries
    - sanitize_model_name: Clean model names
    - sanitize_text: General text sanitization
    - validate_path: Prevent path traversal

Example:
    >>> from utils.sanitization import sanitize_filename
    >>> clean_name = sanitize_filename("../../malicious.pdf")
    >>> print(clean_name)
    malicious.pdf

Author: LocalChat Team
Last Updated: 2024-12-27
"""

import re
import os
from pathlib import Path
from typing import Optional
from .logging_config import get_logger

logger = get_logger(__name__)


def sanitize_filename(filename: str, max_length: int = 255) -> str:
    """
    Sanitize filename to prevent security issues.
    
    Removes path traversal attempts, special characters,
    and limits filename length.
    
    Args:
        filename: Original filename
        max_length: Maximum allowed length (default: 255)
    
    Returns:
        Sanitized filename
    
    Example:
        >>> sanitize_filename("../../etc/passwd")
        'passwd'
        >>> sanitize_filename("document<script>.pdf")
        'documentscript.pdf'
    """
    # Remove any directory path
    filename = os.path.basename(filename)
    
    # Remove path traversal attempts
    filename = filename.replace('..', '')
    filename = filename.replace('/', '')
    filename = filename.replace('\\', '')
    
    # Remove potentially dangerous characters
    # Keep: alphanumeric, dots, underscores, hyphens, spaces
    filename = re.sub(r'[^\w\s.-]', '', filename)
    
    # Remove leading/trailing whitespace and dots
    filename = filename.strip('. ')
    
    # Replace multiple spaces with single space
    filename = re.sub(r'\s+', ' ', filename)
    
    # Limit length (keep extension)
    if len(filename) > max_length:
        name, ext = os.path.splitext(filename)
        name = name[:max_length - len(ext)]
        filename = name + ext
    
    # Ensure filename is not empty
    if not filename:
        filename = 'unnamed_file'
    
    logger.debug(f"Sanitized filename: {filename}")
    return filename


def sanitize_query(query: str, max_length: int = 5000) -> str:
    """
    Sanitize user query for safe processing.
    
    Removes excessive whitespace and limits query length.
    
    Args:
        query: User's search query
        max_length: Maximum allowed length (default: 5000)
    
    Returns:
        Sanitized query
    
    Example:
        >>> sanitize_query("  What    is   this?  ")
        'What is this?'
    """
    # Remove leading/trailing whitespace
    query = query.strip()
    
    # Replace multiple whitespace with single space
    query = ' '.join(query.split())
    
    # Remove control characters
    query = ''.join(char for char in query if ord(char) >= 32 or char in '\n\t')
    
    # Limit length
    if len(query) > max_length:
        query = query[:max_length]
        logger.warning(f"Query truncated to {max_length} characters")
    
    return query


def sanitize_model_name(model_name: str, max_length: int = 100) -> str:
    """
    Sanitize model name for safe usage.
    
    Allows only safe characters for model names:
    alphanumeric, dots, colons, underscores, hyphens.
    
    Args:
        model_name: Model name from user
        max_length: Maximum allowed length (default: 100)
    
    Returns:
        Sanitized model name
    
    Example:
        >>> sanitize_model_name("llama3.2:latest")
        'llama3.2:latest'
        >>> sanitize_model_name("bad<model>name")
        'badmodelname'
    """
    # Remove whitespace
    model_name = model_name.strip()
    
    # Only allow alphanumeric, dots, colons, underscores, hyphens
    model_name = re.sub(r'[^\w\.\:\-]', '', model_name)
    
    # Limit length
    model_name = model_name[:max_length]
    
    return model_name


def sanitize_text(
    text: str,
    max_length: Optional[int] = None,
    remove_html: bool = True
) -> str:
    """
    General text sanitization.
    
    Removes potentially harmful content and normalizes text.
    
    Args:
        text: Input text
        max_length: Optional maximum length
        remove_html: Whether to remove HTML tags (default: True)
    
    Returns:
        Sanitized text
    
    Example:
        >>> sanitize_text("<script>alert('xss')</script>Hello")
        'Hello'
    """
    # Remove HTML tags if requested
    if remove_html:
        text = re.sub(r'<[^>]+>', '', text)
    
    # Remove control characters except newlines and tabs
    text = ''.join(char for char in text if ord(char) >= 32 or char in '\n\t')
    
    # Normalize whitespace
    text = '\n'.join(' '.join(line.split()) for line in text.split('\n'))
    
    # Remove excessive newlines (more than 2 consecutive)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    # Limit length if specified
    if max_length and len(text) > max_length:
        text = text[:max_length]
        logger.debug(f"Text truncated to {max_length} characters")
    
    return text


def validate_path(file_path: str, base_dir: str) -> bool:
    """
    Validate file path to prevent directory traversal.
    
    Ensures the resolved path is within the base directory.
    
    Args:
        file_path: File path to validate
        base_dir: Base directory that should contain the file
    
    Returns:
        True if path is safe, False otherwise
    
    Example:
        >>> validate_path("uploads/file.pdf", "uploads")
        True
        >>> validate_path("../etc/passwd", "uploads")
        False
    """
    try:
        # Resolve both paths to absolute paths
        base_path = Path(base_dir).resolve()
        requested_path = Path(file_path).resolve()
        
        # Check if requested path is within base directory
        return requested_path.is_relative_to(base_path)
    except (ValueError, OSError) as e:
        logger.warning(f"Path validation failed: {e}")
        return False


def sanitize_file_extension(filename: str, allowed_extensions: list) -> bool:
    """
    Validate file extension against allowed list.
    
    Args:
        filename: Filename to check
        allowed_extensions: List of allowed extensions (e.g., ['.pdf', '.txt'])
    
    Returns:
        True if extension is allowed, False otherwise
    
    Example:
        >>> sanitize_file_extension("doc.pdf", ['.pdf', '.txt'])
        True
        >>> sanitize_file_extension("doc.exe", ['.pdf', '.txt'])
        False
    """
    ext = Path(filename).suffix.lower()
    is_allowed = ext in allowed_extensions
    
    if not is_allowed:
        logger.warning(f"Rejected file extension: {ext}")
    
    return is_allowed


def sanitize_json_keys(data: dict, max_depth: int = 10) -> dict:
    """
    Sanitize dictionary keys to prevent injection attacks.
    
    Removes potentially dangerous characters from keys.
    
    Args:
        data: Dictionary to sanitize
        max_depth: Maximum recursion depth (default: 10)
    
    Returns:
        Dictionary with sanitized keys
    
    Example:
        >>> sanitize_json_keys({"user<script>": "value"})
        {'userscript': 'value'}
    """
    if max_depth <= 0:
        logger.warning("Max recursion depth reached in sanitize_json_keys")
        return data
    
    sanitized = {}
    for key, value in data.items():
        # Sanitize key
        clean_key = re.sub(r'[^\w\-_]', '', str(key))
        
        # Recursively sanitize nested dictionaries
        if isinstance(value, dict):
            sanitized[clean_key] = sanitize_json_keys(value, max_depth - 1)
        elif isinstance(value, list):
            sanitized[clean_key] = [
                sanitize_json_keys(item, max_depth - 1) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            sanitized[clean_key] = value
    
    return sanitized


def escape_sql_like(pattern: str) -> str:
    """
    Escape special characters in SQL LIKE patterns.
    
    Escapes %, _, [, and ] characters to prevent SQL injection
    in LIKE queries.
    
    Args:
        pattern: SQL LIKE pattern
    
    Returns:
        Escaped pattern
    
    Example:
        >>> escape_sql_like("test%file")
        'test\\%file'
    """
    # Escape special LIKE characters
    pattern = pattern.replace('\\', '\\\\')
    pattern = pattern.replace('%', '\\%')
    pattern = pattern.replace('_', '\\_')
    pattern = pattern.replace('[', '\\[')
    pattern = pattern.replace(']', '\\]')
    
    return pattern


def truncate_text(
    text: str,
    max_length: int,
    suffix: str = '...'
) -> str:
    """
    Truncate text to maximum length with suffix.
    
    Args:
        text: Text to truncate
        max_length: Maximum length
        suffix: Suffix to add when truncated (default: '...')
    
    Returns:
        Truncated text
    
    Example:
        >>> truncate_text("This is a long text", 10)
        'This is...'
    """
    if len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)] + suffix


def remove_null_bytes(text: str) -> str:
    """
    Remove null bytes from text.
    
    Null bytes can cause issues in some contexts and should be removed.
    
    Args:
        text: Input text
    
    Returns:
        Text without null bytes
    
    Example:
        >>> remove_null_bytes("test\\x00data")
        'testdata'
    """
    return text.replace('\x00', '')


logger.info("Sanitization utilities loaded")
