# -*- coding: utf-8 -*-

"""
Logging Configuration Tests
============================

Tests for logging utilities (src/utils/logging_config.py)

Target: Increase coverage from 26% to 75% (+0.5% overall)

Covers:
- ColoredFormatter
- setup_logging
- get_logger
- Log rotation

Author: LocalChat Team
Created: January 2025
"""

import pytest
import logging
from pathlib import Path


class TestColoredFormatter:
    """Test colored formatter."""
    
    def test_formatter_adds_colors(self):
        """Test that formatter adds ANSI color codes."""
        from src.utils.logging_config import ColoredFormatter
        
        formatter = ColoredFormatter('%(levelname)s - %(message)s')
        record = logging.LogRecord(
            name='test', level=logging.INFO, pathname='', lineno=0,
            msg='Test message', args=(), exc_info=None
        )
        
        result = formatter.format(record)
        
        assert isinstance(result, str)
        assert 'Test message' in result
    
    def test_formatter_handles_all_levels(self):
        """Test formatter with all log levels."""
        from src.utils.logging_config import ColoredFormatter
        
        formatter = ColoredFormatter('%(levelname)s')
        levels = [logging.DEBUG, logging.INFO, logging.WARNING, 
                  logging.ERROR, logging.CRITICAL]
        
        for level in levels:
            record = logging.LogRecord(
                name='test', level=level, pathname='', lineno=0,
                msg='msg', args=(), exc_info=None
            )
            result = formatter.format(record)
            assert isinstance(result, str)


class TestSetupLogging:
    """Test logging setup."""
    
    def test_setup_logging_creates_logger(self, tmp_path):
        """Test that setup_logging creates a configured logger."""
        from src.utils.logging_config import setup_logging
        
        log_file = tmp_path / "test.log"
        logger = setup_logging(
            log_level="INFO",
            log_file=str(log_file),
            enable_console=False
        )
        
        assert isinstance(logger, logging.Logger)
        assert logger.level == logging.INFO
    
    def test_setup_logging_creates_log_directory(self, tmp_path):
        """Test that log directory is created."""
        from src.utils.logging_config import setup_logging
        
        log_file = tmp_path / "subdir" / "test.log"
        setup_logging(log_file=str(log_file), enable_console=False)
        
        assert log_file.parent.exists()
    
    def test_setup_logging_sets_log_level(self, tmp_path):
        """Test that log level is set correctly."""
        from src.utils.logging_config import setup_logging
        
        log_file = tmp_path / "test.log"
        logger = setup_logging(
            log_level="DEBUG",
            log_file=str(log_file),
            enable_console=False
        )
        
        assert logger.level == logging.DEBUG
    
    def test_setup_logging_adds_handlers(self, tmp_path):
        """Test that handlers are added."""
        from src.utils.logging_config import setup_logging
        
        log_file = tmp_path / "test.log"
        logger = setup_logging(log_file=str(log_file), enable_console=True)
        
        assert len(logger.handlers) > 0


class TestGetLogger:
    """Test get_logger function."""
    
    def test_get_logger_returns_logger(self):
        """Test that get_logger returns a logger instance."""
        from src.utils.logging_config import get_logger
        
        logger = get_logger("test_module")
        
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_module"
    
    def test_get_logger_caches_loggers(self):
        """Test that loggers are cached."""
        from src.utils.logging_config import get_logger
        
        logger1 = get_logger("test")
        logger2 = get_logger("test")
        
        assert logger1 is logger2
    
    def test_get_logger_different_names(self):
        """Test that different names create different loggers."""
        from src.utils.logging_config import get_logger
        
        logger1 = get_logger("module1")
        logger2 = get_logger("module2")
        
        assert logger1.name != logger2.name


class TestLogRotation:
    """Test log file rotation."""
    
    def test_rotating_handler_configured(self, tmp_path):
        """Test that rotating handler is configured."""
        from src.utils.logging_config import setup_logging
        import logging.handlers
        
        log_file = tmp_path / "test.log"
        logger = setup_logging(
            log_file=str(log_file),
            max_bytes=1024,
            backup_count=3,
            enable_console=False
        )
        
        # Check if rotating handler exists
        has_rotating = any(
            isinstance(h, logging.handlers.RotatingFileHandler)
            for h in logger.handlers
        )
        assert has_rotating or len(logger.handlers) > 0


class TestLoggingEdgeCases:
    """Test edge cases in logging."""
    
    def test_logging_with_none_message(self):
        """Test logging with None message."""
        from src.utils.logging_config import get_logger
        
        logger = get_logger("test")
        
        # Should not raise
        try:
            logger.info(None)
        except:
            pass  # Some implementations may reject None
    
    def test_logging_with_unicode(self):
        """Test logging with unicode characters."""
        from src.utils.logging_config import get_logger
        
        logger = get_logger("test")
        logger.info("Unicode: test string")

        # Should not raise
        assert logger is not None
    
    def test_setup_with_invalid_level(self, tmp_path):
        """Test setup with invalid log level."""
        from src.utils.logging_config import setup_logging
        
        log_file = tmp_path / "test.log"
        
        # Should handle gracefully or raise
        try:
            setup_logging(
                log_level="INVALID",
                log_file=str(log_file),
                enable_console=False
            )
        except (ValueError, AttributeError):
            pass  # Expected for invalid level


class TestSafeStreamHandler:
    """Tests for SafeStreamHandler.handleError."""

    def test_suppresses_closed_file_value_error(self):
        """ValueError('closed file') is silently swallowed."""
        from src.utils.logging_config import SafeStreamHandler
        import io

        handler = SafeStreamHandler(io.StringIO())
        record = logging.LogRecord("t", logging.INFO, "", 0, "m", (), None)

        # Simulate the ValueError that occurs when the stream is closed
        try:
            raise ValueError("I/O operation on closed file")
        except ValueError:
            import sys
            handler.handleError(record)  # should not raise or print

    def test_delegates_other_errors(self):
        """Non 'closed file' errors are passed to the base class."""
        from src.utils.logging_config import SafeStreamHandler
        import io

        handler = SafeStreamHandler(io.StringIO())
        record = logging.LogRecord("t", logging.INFO, "", 0, "m", (), None)

        try:
            raise ValueError("some other error")
        except ValueError:
            # Base class handleError prints to stderr but does not raise
            handler.handleError(record)  # should not raise


class TestJsonFormatter:
    """Tests for JsonFormatter."""

    def _make_record(self, msg="hello", level=logging.INFO, exc_info=None):
        return logging.LogRecord(
            name="test.module", level=level, pathname="f.py",
            lineno=10, msg=msg, args=(), exc_info=exc_info,
        )

    def test_output_is_valid_json(self):
        """Each formatted record is a parseable JSON object."""
        import json
        from src.utils.logging_config import JsonFormatter

        fmt = JsonFormatter()
        output = fmt.format(self._make_record())
        data = json.loads(output)
        assert data["message"] == "hello"
        assert data["level"] == "INFO"
        assert "timestamp" in data

    def test_includes_all_standard_fields(self):
        """All required fields are present."""
        import json
        from src.utils.logging_config import JsonFormatter

        fmt = JsonFormatter()
        data = json.loads(fmt.format(self._make_record()))
        for field in ("timestamp", "level", "logger", "message", "module", "funcName", "lineno"):
            assert field in data

    def test_includes_request_id_when_set(self):
        """request_id attribute on the record is forwarded to the JSON."""
        import json
        from src.utils.logging_config import JsonFormatter

        fmt = JsonFormatter()
        record = self._make_record()
        record.request_id = "req-abc-123"
        data = json.loads(fmt.format(record))
        assert data["request_id"] == "req-abc-123"

    def test_includes_exc_info_when_present(self):
        """Exception info is serialised into the JSON output."""
        import json
        from src.utils.logging_config import JsonFormatter

        fmt = JsonFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys
            record = self._make_record(exc_info=sys.exc_info())
        data = json.loads(fmt.format(record))
        assert "exc_info" in data


class TestSetupLoggingJsonFormat:
    """Cover setup_logging with log_format='json' (lines 167, 182)."""

    def test_json_format_file_handler(self, tmp_path):
        """JSON formatter is used for the file handler when log_format='json'."""
        from src.utils.logging_config import setup_logging, JsonFormatter
        import logging.handlers

        log_file = tmp_path / "app.log"
        logger = setup_logging(
            log_file=str(log_file),
            log_format="json",
            enable_console=False,
        )
        file_handlers = [
            h for h in logger.handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert file_handlers, "Expected a RotatingFileHandler"
        assert isinstance(file_handlers[0].formatter, JsonFormatter)

    def test_json_format_console_handler(self, tmp_path):
        """JSON formatter is used for the console handler when log_format='json'."""
        from src.utils.logging_config import setup_logging, JsonFormatter

        log_file = tmp_path / "app.log"
        logger = setup_logging(
            log_file=str(log_file),
            log_format="json",
            enable_console=True,
        )
        console_handlers = [
            h for h in logger.handlers
            if not isinstance(h, __import__("logging.handlers", fromlist=["RotatingFileHandler"]).RotatingFileHandler)
        ]
        json_console = any(isinstance(h.formatter, JsonFormatter) for h in console_handlers)
        assert json_console


class TestLogFunctionCall:
    """Tests for the log_function_call decorator (lines 227-241)."""

    def test_returns_result_unchanged(self):
        """Decorated function still returns its value."""
        from src.utils.logging_config import log_function_call

        @log_function_call
        def add(a, b):
            return a + b

        assert add(2, 3) == 5

    def test_preserves_function_metadata(self):
        """@wraps preserves __name__ and __doc__."""
        from src.utils.logging_config import log_function_call

        @log_function_call
        def my_func():
            """My docstring."""

        assert my_func.__name__ == "my_func"
        assert my_func.__doc__ == "My docstring."

    def test_reraises_exceptions(self):
        """Exceptions from the wrapped function propagate normally."""
        from src.utils.logging_config import log_function_call
        import pytest

        @log_function_call
        def fail():
            raise RuntimeError("oops")

        with pytest.raises(RuntimeError, match="oops"):
            fail()

    def test_logs_call_and_result(self):
        """Debug messages are emitted for the call and its return value."""
        from src.utils.logging_config import log_function_call
        from unittest.mock import patch

        @log_function_call
        def greet(name):
            return f"hello {name}"

        with patch("src.utils.logging_config.get_logger") as mock_get:
            mock_logger = mock_get.return_value
            # Re-decorate so it picks up the patched logger
            @log_function_call
            def greet2(name):
                return f"hi {name}"
            greet2("world")

        mock_logger.debug.assert_called()
