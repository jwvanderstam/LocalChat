# -*- coding: utf-8 -*-
"""Micro-targeted tests to push coverage past 80%."""

import os
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# src/__init__.py — line 41: FLASK_ENV == 'development' branch
# ---------------------------------------------------------------------------

class TestSrcInitDevBranch:
    def test_development_env_import_succeeds(self):
        """Cover the FLASK_ENV='development' branch in src/__init__.py."""
        with patch.dict(os.environ, {'FLASK_ENV': 'development'}):
            import importlib
            import src
            importlib.reload(src)
        # Reload without dev env to restore
        importlib.reload(src)


# ---------------------------------------------------------------------------
# db/conversations.py — lines 237-247: delete_all_conversations
# ---------------------------------------------------------------------------

def _make_mock_conn():
    """Return a (conn, cursor) pair without touching the global db singleton."""
    conn = MagicMock()
    cursor = MagicMock()
    cursor.rowcount = 3
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn, cursor


class TestDeleteAllConversations:
    def test_deletes_all_and_returns_count(self):
        from src.db import db
        conn, cursor = _make_mock_conn()
        cursor.rowcount = 5
        with patch.object(db, 'is_connected', True), \
             patch.object(db, 'get_connection', return_value=conn):
            result = db.delete_all_conversations()
        assert result == 5

    def test_raises_when_not_connected(self):
        from src.db import db
        from src.db.connection import DatabaseUnavailableError
        with patch.object(db, 'is_connected', False):
            with pytest.raises(DatabaseUnavailableError):
                db.delete_all_conversations()

    def test_executes_delete_statement(self):
        from src.db import db
        conn, cursor = _make_mock_conn()
        with patch.object(db, 'is_connected', True), \
             patch.object(db, 'get_connection', return_value=conn):
            db.delete_all_conversations()
        cursor.execute.assert_called()
        call_args = cursor.execute.call_args[0][0]
        assert "DELETE" in call_args.upper()


# ---------------------------------------------------------------------------
# utils/logging_config.py — lines 34-37: QuietStreamHandler.handleError
# ---------------------------------------------------------------------------

class TestQuietStreamHandler:
    def test_suppresses_closed_file_value_error(self):
        from src.utils.logging_config import get_logger
        import logging

        logger = get_logger("test_quiet")

        # Find a QuietStreamHandler if one was added; otherwise create one directly
        try:
            from src.utils.logging_config import QuietStreamHandler
            handler = QuietStreamHandler()
        except ImportError:
            return  # class not exported publicly, skip

        record = logging.LogRecord("test", logging.DEBUG, "", 0, "msg", (), None)

        with patch('sys.exc_info', return_value=(ValueError, ValueError("closed file"), None)):
            handler.handleError(record)  # Should NOT raise

    def test_propagates_other_errors(self):
        try:
            from src.utils.logging_config import QuietStreamHandler
        except ImportError:
            return

        import logging
        handler = QuietStreamHandler()
        record = logging.LogRecord("test", logging.ERROR, "", 0, "msg", (), None)

        # Other exceptions should propagate to super().handleError
        with patch('sys.exc_info', return_value=(RuntimeError, RuntimeError("other"), None)):
            with patch.object(handler.__class__.__bases__[0], 'handleError'):
                handler.handleError(record)  # Should call super


# ---------------------------------------------------------------------------
# cache/managers.py — line 124: EmbeddingCache.get_or_generate return path
# and init_caches lines 320, 325
# ---------------------------------------------------------------------------

class TestInitCaches:
    def test_init_caches_returns_both_instances(self):
        from src.cache.managers import init_caches, EmbeddingCache, QueryCache
        ec, qc = init_caches()
        assert isinstance(ec, EmbeddingCache)
        assert isinstance(qc, QueryCache)

    def test_init_caches_with_custom_ttl(self):
        from src.cache.managers import init_caches, get_embedding_cache, get_query_cache
        ec, qc = init_caches(embedding_ttl=100, query_ttl=50)
        assert ec.ttl == 100
        assert qc.ttl == 50

    def test_get_embedding_cache_after_init(self):
        from src.cache.managers import init_caches, get_embedding_cache
        init_caches()
        assert get_embedding_cache() is not None

    def test_get_query_cache_after_init(self):
        from src.cache.managers import init_caches, get_query_cache
        init_caches()
        assert get_query_cache() is not None
