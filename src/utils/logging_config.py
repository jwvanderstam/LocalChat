"""
Logging Utility Module
=====================

Provides structured logging configuration for the LocalChat application.
Implements rotating file handlers and consistent formatting across all modules.

Example:
    >>> from utils.logging_config import get_logger
    >>> logger = get_logger(__name__)
    >>> logger.info("Application started")
"""

import functools
import json
import logging
import logging.handlers
import os
import sys
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional


def sanitize_log_value(value: object) -> str:
    """Strip CR/LF from a user-supplied value before embedding in a log message."""
    return str(value).replace('\r', '').replace('\n', ' ')


class SafeStreamHandler(logging.StreamHandler):
    """
    StreamHandler that silently drops 'I/O operation on closed file' errors.

    During interpreter shutdown (or pytest teardown), the stream held by this
    handler can be closed before all atexit/teardown callbacks have finished.
    The base class would then print a noisy --- Logging error --- traceback to
    stderr via handleError().  We suppress only that specific case.
    """

    def handleError(self, record: logging.LogRecord) -> None:
        t, v, _ = sys.exc_info()
        if t is ValueError and "closed file" in str(v):
            return  # silently ignore — stream was closed during teardown
        super().handleError(record)


class JsonFormatter(logging.Formatter):
    """
    Emit each log record as a single JSON line.

    Fields: timestamp (ISO-8601), level, logger, message, module,
    funcName, lineno, and — when available on the record — request_id.

    Enable by setting ``LOG_FORMAT=json`` in the environment.  Recommended
    for production deployments feeding logs into an aggregator (Loki,
    Elasticsearch, CloudWatch, etc.).
    """

    # Standard LogRecord attributes that should not be re-emitted as extras.
    _STANDARD_ATTRS: frozenset[str] = frozenset({
        "name", "msg", "args", "created", "filename", "funcName", "levelname",
        "levelno", "lineno", "module", "msecs", "message", "pathname",
        "process", "processName", "relativeCreated", "stack_info", "thread",
        "threadName", "exc_info", "exc_text", "request_id", "user_agent",
    })

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "funcName": record.funcName,
            "lineno": record.lineno,
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            payload["request_id"] = request_id
        user_agent = getattr(record, "user_agent", None)
        if user_agent:
            payload["user_agent"] = user_agent
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        # Emit any caller-supplied extra fields (e.g. duration_ms, model, chunks_retrieved)
        for key, value in record.__dict__.items():
            if key not in self._STANDARD_ATTRS and not key.startswith("_") and value is not None:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False)


class RequestIdFilter(logging.Filter):
    """
    Logging filter that copies ``flask.g.request_id`` onto every log record.

    Must be added to each handler (or the root logger) **after** the Flask
    application context is set up.  Falls back to an empty string outside of
    a request context so it is safe to use in background threads and tests.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            from flask import g, request
            record.request_id = getattr(g, "request_id", "")
            record.user_agent = request.user_agent.string
        except RuntimeError:
            # No application/request context — e.g. tests or worker threads.
            record.request_id = ""
            record.user_agent = ""
        return True


class ColoredFormatter(logging.Formatter):
    """Colored console formatter for better readability."""

    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
        'RESET': '\033[0m'        # Reset
    }

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with colors."""
        # Add color to level name
        levelname = record.levelname
        if levelname in self.COLORS:
            record.levelname = f"{self.COLORS[levelname]}{levelname}{self.COLORS['RESET']}"

        # Format message
        formatted = super().format(record)

        # Reset color at end
        return formatted


def setup_logging(
    log_level: str = "INFO",
    log_file: str = "logs/app.log",
    max_bytes: int = 10485760,  # 10 MB
    backup_count: int = 5,
    enable_console: bool = True,
    log_format: str = "text",
) -> logging.Logger:
    """
    Configure application-wide logging.

    Sets up rotating file handler and optional console handler.
    Pass ``log_format='json'`` to emit JSON lines (production default).

    Args:
        log_level: Minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_file: Path to the rotating log file.
        max_bytes: Maximum file size before rotation.
        backup_count: Number of rotated files to retain.
        enable_console: Whether to attach a console (stderr) handler.
        log_format: ``'json'`` for JSON lines, ``'text'`` for human-readable.

    Returns:
        Configured root logger.

    Example:
        >>> logger = setup_logging(log_level="DEBUG", log_format="json")
        >>> logger.info("Application configured")
    """
    log_path = Path(log_file)
    log_path.parent.mkdir(exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    root_logger.handlers.clear()

    request_id_filter = RequestIdFilter()
    use_json = log_format.lower() == "json"

    # --- File handler ---
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    if use_json:
        file_handler.setFormatter(JsonFormatter())
    else:
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d"
            " - [%(request_id)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
    file_handler.addFilter(request_id_filter)
    root_logger.addHandler(file_handler)

    # --- Console handler ---
    if enable_console:
        console_handler = SafeStreamHandler()
        console_handler.setLevel(logging.INFO)
        if use_json:
            console_handler.setFormatter(JsonFormatter())
        else:
            console_handler.setFormatter(
                ColoredFormatter("%(levelname)s - %(name)s - %(message)s")
            )
        console_handler.addFilter(request_id_filter)
        root_logger.addHandler(console_handler)

    root_logger.info("Logging system initialized (format=%s)", log_format)
    root_logger.debug("Log file: %s | level: %s", log_file, log_level)
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a module.

    Args:
        name: Logger name (typically __name__ of the module)

    Returns:
        Logger instance

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Module initialized")
    """
    return logging.getLogger(name)


def log_function_call(func: Callable) -> Callable:
    """
    Decorator to log function calls with arguments and results.

    Args:
        func: Function to decorate

    Returns:
        Wrapped function

    Example:
        >>> @log_function_call
        ... def my_function(x, y):
        ...     return x + y
    """
    logger = get_logger(func.__module__)

    @functools.wraps(func)

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        logger.debug(f"Calling {func.__name__} with args={args}, kwargs={kwargs}")
        try:
            result = func(*args, **kwargs)
            logger.debug(f"{func.__name__} returned {result}")
            return result
        except Exception as e:
            logger.error(f"{func.__name__} raised {type(e).__name__}: {e}", exc_info=True)
            raise

    return wrapper



