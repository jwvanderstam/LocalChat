import os
import re
from pathlib import Path
from typing import Any

from .logging_config import get_logger

logger = get_logger(__name__)


def sanitize_filename(filename: str, max_length: int = 255) -> str:
    filename = os.path.basename(filename)
    filename = filename.replace('..', '').replace('/', '').replace('\\', '')
    # Keep: alphanumeric, dots, underscores, hyphens, spaces
    filename = re.sub(r'[^\w\s.-]', '', filename)
    filename = filename.strip('. ')
    filename = re.sub(r'\s+', ' ', filename)
    if len(filename) > max_length:
        name, ext = os.path.splitext(filename)
        filename = name[:max_length - len(ext)] + ext
    if not filename:
        filename = 'unnamed_file'
    logger.debug(f"Sanitized filename: {filename}")
    return filename


def sanitize_query(query: str, max_length: int = 5000) -> str:
    query = query.strip()
    query = ' '.join(query.split())
    query = ''.join(char for char in query if ord(char) >= 32 or char in '\n\t')
    if len(query) > max_length:
        query = query[:max_length]
        logger.warning(f"Query truncated to {max_length} characters")
    return query


def sanitize_model_name(model_name: str, max_length: int = 100) -> str:
    """Allowlist: alphanumeric, dots, colons, underscores, hyphens."""
    model_name = model_name.strip()
    model_name = re.sub(r'[^\w\.\:\-]', '', model_name)
    return model_name[:max_length]


def sanitize_text(
    text: str,
    max_length: int | None = None,
    remove_html: bool = True
) -> str:
    if remove_html:
        text = re.sub(r'<[^>]+>', '', text)
    text = ''.join(char for char in text if ord(char) >= 32 or char in '\n\t')
    text = '\n'.join(' '.join(line.split()) for line in text.split('\n'))
    text = re.sub(r'\n{3,}', '\n\n', text)
    if max_length and len(text) > max_length:
        text = text[:max_length]
        logger.debug(f"Text truncated to {max_length} characters")
    return text


def validate_path(file_path: str, base_dir: str) -> bool:
    try:
        base_path = Path(base_dir).resolve()
        requested_path = Path(file_path).resolve()
        return requested_path.is_relative_to(base_path)
    except (ValueError, OSError) as e:
        logger.warning(f"Path validation failed: {e}")
        return False


def sanitize_file_extension(filename: str, allowed_extensions: list) -> bool:
    ext = Path(filename).suffix.lower()
    is_allowed = ext in allowed_extensions
    if not is_allowed:
        logger.warning(f"Rejected file extension: {ext}")
    return is_allowed


def sanitize_json_keys(data: dict, max_depth: int = 10) -> dict:
    if max_depth <= 0:
        logger.warning("Max recursion depth reached in sanitize_json_keys")
        return data
    sanitized: dict[str, Any] = {}
    for key, value in data.items():
        clean_key = re.sub(r'[^\w\-]', '', str(key))
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
    """Escapes LIKE metacharacters (%, _, [, ]) so the pattern is treated literally."""
    pattern = pattern.replace('\\', '\\\\')
    pattern = pattern.replace('%', '\\%')
    pattern = pattern.replace('_', '\\_')
    pattern = pattern.replace('[', '\\[')
    pattern = pattern.replace(']', '\\]')
    return pattern


def truncate_text(text: str, max_length: int, suffix: str = '...') -> str:
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def remove_null_bytes(text: str) -> str:
    return text.replace('\x00', '')


logger.info("Sanitization utilities loaded")
