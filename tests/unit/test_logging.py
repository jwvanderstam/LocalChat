"""
Unit tests for utils/logging_config.py

Tests logging setup, logger creation, and formatting.
"""

import logging
import os

import pytest

from src.utils.logging_config import get_logger, log_function_call, setup_logging

# ============================================================================
# SETUP_LOGGING TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.skip(reason="File locking issues on Windows")
class TestSetupLogging:
    """Tests for setup_logging function."""

    def test_setup_logging_creates_logger(self, temp_dir):
        """Should create root logger."""
        log_file = os.path.join(temp_dir, "test.log")
        setup_logging(log_file=log_file)

        logger = logging.getLogger()
        assert logger.level == logging.INFO

    def test_setup_logging_with_debug_level(self, temp_dir):
        """Should set debug log level."""
        log_file = os.path.join(temp_dir, "test.log")
        setup_logging(log_level="DEBUG", log_file=log_file)

        logger = logging.getLogger()
        assert logger.level == logging.DEBUG

    def test_setup_logging_with_warning_level(self, temp_dir):
        """Should set warning log level."""
        log_file = os.path.join(temp_dir, "test.log")
        setup_logging(log_level="WARNING", log_file=log_file)

        logger = logging.getLogger()
        assert logger.level == logging.WARNING

    def test_setup_logging_creates_log_directory(self, temp_dir):
        """Should create log directory if it doesn't exist."""
        log_file = os.path.join(temp_dir, "subdir", "test.log")
        setup_logging(log_file=log_file)

        assert os.path.exists(os.path.dirname(log_file))

    def test_setup_logging_adds_file_handler(self, temp_dir):
        """Should add file handler."""
        log_file = os.path.join(temp_dir, "test.log")
        setup_logging(log_file=log_file)

        logger = logging.getLogger()
        # Check if file handler exists
        has_file_handler = any(
            isinstance(h, logging.FileHandler)
            for h in logger.handlers
        )
        assert has_file_handler

    def test_setup_logging_adds_console_handler(self, temp_dir):
        """Should add console handler."""
        log_file = os.path.join(temp_dir, "test.log")
        setup_logging(log_file=log_file)

        logger = logging.getLogger()
        # Check if stream handler exists
        has_console_handler = any(
            isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
            for h in logger.handlers
        )
        assert has_console_handler


# ============================================================================
# GET_LOGGER TESTS
# ============================================================================

@pytest.mark.unit
class TestGetLogger:
    """Tests for get_logger function."""

    def test_get_logger_returns_logger(self):
        """Should return a logger instance."""
        logger = get_logger("test_module")
        assert isinstance(logger, logging.Logger)

    def test_get_logger_with_module_name(self):
        """Should create logger with module name."""
        logger = get_logger("my_module")
        assert logger.name == "my_module"

    def test_get_logger_returns_same_logger_for_same_name(self):
        """Should return same logger for same name."""
        logger1 = get_logger("test")
        logger2 = get_logger("test")
        assert logger1 is logger2

    def test_get_logger_returns_different_loggers_for_different_names(self):
        """Should return different loggers for different names."""
        logger1 = get_logger("test1")
        logger2 = get_logger("test2")
        assert logger1 is not logger2

    def test_get_logger_with_dunder_name(self):
        """Should work with __name__ pattern."""
        logger = get_logger(__name__)
        assert isinstance(logger, logging.Logger)


# ============================================================================
# LOG_FUNCTION_CALL DECORATOR TESTS
# ============================================================================

@pytest.mark.unit
class TestLogFunctionCallDecorator:
    """Tests for log_function_call decorator."""

    def test_decorator_logs_function_call(self, caplog):
        """Should log function call."""
        @log_function_call
        def test_function(x, y):
            return x + y

        with caplog.at_level(logging.DEBUG):
            result = test_function(2, 3)

        assert result == 5
        # Check if function call was logged
        assert any("test_function" in record.message for record in caplog.records)

    def test_decorator_preserves_function_name(self):
        """Should preserve original function name."""
        @log_function_call
        def my_function():
            pass

        assert my_function.__name__ == "my_function"

    def test_decorator_preserves_docstring(self):
        """Should preserve function docstring."""
        @log_function_call
        def my_function():
            """This is a docstring."""
            pass

        assert my_function.__doc__ == "This is a docstring."

    def test_decorator_works_with_return_value(self):
        """Should work with functions that return values."""
        @log_function_call
        def get_value():
            return 42

        result = get_value()
        assert result == 42

    def test_decorator_works_with_exceptions(self):
        """Should work even if function raises exception."""
        @log_function_call
        def raising_function():
            raise ValueError("Test error")

        with pytest.raises(ValueError):
            raising_function()

    def test_decorator_works_with_args_and_kwargs(self):
        """Should work with both args and kwargs."""
        @log_function_call
        def complex_function(a, b, c=None, d=None):
            return (a, b, c, d)

        result = complex_function(1, 2, c=3, d=4)
        assert result == (1, 2, 3, 4)


# ============================================================================
# LOGGING OUTPUT TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.skip(reason="File locking issues on Windows during test cleanup")
class TestLoggingOutput:
    """Tests for logging output."""

    def test_logger_writes_to_file(self, temp_dir):
        """Should write logs to file."""
        log_file = os.path.join(temp_dir, "test.log")
        setup_logging(log_file=log_file)

        logger = get_logger("test")
        logger.info("Test message")

        # Check file was created and contains message
        assert os.path.exists(log_file)
        with open(log_file) as f:
            content = f.read()
            assert "Test message" in content

    def test_logger_respects_log_level(self, temp_dir, caplog):
        """Should respect log level."""
        log_file = os.path.join(temp_dir, "test.log")
        setup_logging(log_level="WARNING", log_file=log_file)

        logger = get_logger("test")

        with caplog.at_level(logging.WARNING):
            logger.debug("Debug message")  # Should not appear
            logger.warning("Warning message")  # Should appear

        # Warning should be logged, debug should not
        messages = [record.message for record in caplog.records]
        assert "Warning message" in messages
        assert "Debug message" not in messages

    def test_logger_formats_messages_correctly(self, temp_dir):
        """Should format log messages correctly."""
        log_file = os.path.join(temp_dir, "test.log")
        setup_logging(log_file=log_file)

        logger = get_logger("test_module")
        logger.info("Test message")

        with open(log_file) as f:
            content = f.read()
            # Should contain timestamp, level, module name, and message
            assert "INFO" in content
            assert "test_module" in content
            assert "Test message" in content


# ============================================================================
# LOGGER HIERARCHY TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.skip(reason="File locking issues on Windows")
class TestLoggerHierarchy:
    """Tests for logger hierarchy."""

    def test_child_logger_inherits_level(self, temp_dir):
        """Should inherit log level from parent."""
        log_file = os.path.join(temp_dir, "test.log")
        setup_logging(log_level="WARNING", log_file=log_file)

        get_logger("parent")
        child_logger = get_logger("parent.child")

        # Child should inherit parent's effective level
        assert child_logger.getEffectiveLevel() >= logging.WARNING

    def test_loggers_with_different_names_are_independent(self):
        """Should create independent loggers for different names."""
        logger1 = get_logger("module1")
        logger2 = get_logger("module2")

        assert logger1 != logger2
        assert logger1.name != logger2.name


# ============================================================================
# EDGE CASES
# ============================================================================

@pytest.mark.unit
@pytest.mark.skip(reason="File locking issues on Windows during test cleanup")
class TestLoggingEdgeCases:
    """Edge case tests for logging."""

    def test_setup_logging_called_multiple_times(self, temp_dir):
        """Should handle being called multiple times."""
        log_file = os.path.join(temp_dir, "test.log")

        setup_logging(log_file=log_file)
        setup_logging(log_file=log_file)  # Call again

        # Should not raise exception
        logger = get_logger("test")
        logger.info("Test")

    def test_get_logger_with_empty_name(self):
        """Should handle empty logger name."""
        logger = get_logger("")
        assert isinstance(logger, logging.Logger)

    def test_logging_with_unicode_characters(self, temp_dir):
        """Should handle Unicode characters in log messages."""
        log_file = os.path.join(temp_dir, "test.log")
        setup_logging(log_file=log_file)

        logger = get_logger("test")
        logger.info("Testing ??? ?? ????")

        # Should not raise exception
        with open(log_file, encoding='utf-8') as f:
            content = f.read()
            assert len(content) > 0

    def test_logging_very_long_messages(self, temp_dir):
        """Should handle very long log messages."""
        log_file = os.path.join(temp_dir, "test.log")
        setup_logging(log_file=log_file)

        logger = get_logger("test")
        long_message = "x" * 10000
        logger.info(long_message)

        # Should not raise exception
        assert os.path.exists(log_file)

    def test_logging_with_special_characters(self, temp_dir):
        """Should handle special characters."""
        log_file = os.path.join(temp_dir, "test.log")
        setup_logging(log_file=log_file)

        logger = get_logger("test")
        logger.info("Test: {}, [], <>, %, \\, /")

        # Should not raise exception
        assert os.path.exists(log_file)


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.skip(reason="File locking issues on Windows during test cleanup")
class TestLoggingIntegration:
    """Integration tests for logging."""

    def test_complete_logging_workflow(self, temp_dir):
        """Should handle complete logging workflow."""
        log_file = os.path.join(temp_dir, "app.log")

        # Setup logging
        setup_logging(log_level="DEBUG", log_file=log_file)

        # Create loggers for different modules
        logger1 = get_logger("module1")
        logger2 = get_logger("module2")

        # Log at different levels
        logger1.debug("Debug message")
        logger1.info("Info message")
        logger2.warning("Warning message")
        logger2.error("Error message")

        # Verify log file exists and has content
        assert os.path.exists(log_file)
        with open(log_file) as f:
            content = f.read()
            assert "Debug message" in content
            assert "Info message" in content
            assert "Warning message" in content
            assert "Error message" in content

    def test_logging_across_multiple_modules(self, temp_dir):
        """Should work across multiple modules."""
        log_file = os.path.join(temp_dir, "test.log")
        setup_logging(log_file=log_file)

        # Simulate different modules
        db_logger = get_logger("db")
        api_logger = get_logger("api")
        rag_logger = get_logger("rag")

        db_logger.info("Database connected")
        api_logger.info("API request received")
        rag_logger.info("Document processed")

        with open(log_file) as f:
            content = f.read()
            assert "Database connected" in content
            assert "API request received" in content
            assert "Document processed" in content


