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

import logging
import functools
import logging.handlers
import os
from pathlib import Path
from typing import Optional


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
    max_bytes: int = 10485760,  # 10MB
    backup_count: int = 5,
    enable_console: bool = True
) -> logging.Logger:
    """
    Configure application-wide logging.
    
    Sets up both file and console logging with rotating file handlers.
    File logs are more detailed than console logs.
    
    Args:
        log_level: Minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Path to log file
        max_bytes: Maximum size of log file before rotation
        backup_count: Number of backup files to keep
        enable_console: Whether to enable console logging
    
    Returns:
        Configured root logger
    
    Example:
        >>> logger = setup_logging(log_level="DEBUG")
        >>> logger.info("Application configured")
    """
    # Create logs directory if it doesn't exist
    log_path = Path(log_file)
    log_path.parent.mkdir(exist_ok=True)
    
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # File handler with detailed formatting
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)
    
    # Console handler with colored output
    if enable_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = ColoredFormatter(
            '%(levelname)s - %(name)s - %(message)s'
        )
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)
    
    # Log initial message
    root_logger.info("Logging system initialized")
    root_logger.debug(f"Log file: {log_file}")
    root_logger.debug(f"Log level: {log_level}")
    
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


def log_function_call(func):
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
    
    def wrapper(*args, **kwargs):
        logger.debug(f"Calling {func.__name__} with args={args}, kwargs={kwargs}")
        try:
            result = func(*args, **kwargs)
            logger.debug(f"{func.__name__} returned {result}")
            return result
        except Exception as e:
            logger.error(f"{func.__name__} raised {type(e).__name__}: {e}", exc_info=True)
            raise
    
    return wrapper



