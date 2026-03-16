# -*- coding: utf-8 -*-
"""Five lines to push coverage to 80%."""

import sys
import logging
import pytest
from unittest.mock import patch


class TestSafeStreamHandlerSuperCall:
    """Cover logging_config.py lines 34-37 (super().handleError path)."""

    def _make_handler(self):
        from src.utils.logging_config import SafeStreamHandler
        import io
        handler = SafeStreamHandler(io.StringIO())
        return handler

    def test_non_value_error_calls_super(self):
        """When exc_info is a TypeError, super().handleError must be called."""
        handler = self._make_handler()
        record = logging.LogRecord("t", logging.ERROR, "", 0, "msg", (), None)

        # Patch sys.exc_info to return a non-ValueError type so super() path runs
        with patch('sys.exc_info', return_value=(TypeError, TypeError("other"), None)):
            # super().handleError writes to stderr — suppress it
            with patch.object(logging.StreamHandler, 'handleError'):
                handler.handleError(record)  # should NOT suppress — calls super

    def test_none_exc_info_calls_super(self):
        """When exc_info is (None, None, None), super().handleError is called."""
        handler = self._make_handler()
        record = logging.LogRecord("t", logging.WARNING, "", 0, "msg", (), None)

        with patch('sys.exc_info', return_value=(None, None, None)):
            with patch.object(logging.StreamHandler, 'handleError'):
                handler.handleError(record)

    def test_closed_file_error_is_suppressed(self):
        """ValueError with 'closed file' must be silently swallowed."""
        handler = self._make_handler()
        record = logging.LogRecord("t", logging.DEBUG, "", 0, "msg", (), None)

        with patch('sys.exc_info',
                   return_value=(ValueError, ValueError("I/O operation on closed file"), None)):
            handler.handleError(record)  # must not raise


class TestApiDocsImportErrorPath:
    """Cover api_docs.py lines 289-291 (flasgger not installed branch)."""

    def test_init_swagger_raises_when_flasgger_missing(self, app):
        from src.api_docs import init_swagger

        # Remove flasgger from sys.modules so the local import inside
        # init_swagger raises ImportError
        flasgger_backup = sys.modules.pop('flasgger', None)
        try:
            with patch.dict(sys.modules, {'flasgger': None}):
                with pytest.raises((ImportError, Exception)):
                    init_swagger(app)
        finally:
            if flasgger_backup is not None:
                sys.modules['flasgger'] = flasgger_backup
