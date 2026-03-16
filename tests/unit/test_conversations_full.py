# -*- coding: utf-8 -*-
"""Tests for ConversationsMixin (db/conversations.py)."""

import pytest
from unittest.mock import MagicMock, patch, call


def _make_db_with_conversations():
    """Build a minimal object that exercises ConversationsMixin."""
    from src.db.conversations import ConversationsMixin

    class FakeDB(ConversationsMixin):
        def __init__(self, connected=True):
            self.is_connected = connected
            self._conn = MagicMock()
            self._cursor = MagicMock()

        def get_connection(self):
            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=self._conn)
            ctx.__exit__ = MagicMock(return_value=False)
            self._conn.cursor.return_value.__enter__ = MagicMock(return_value=self._cursor)
            self._conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            return ctx

    return FakeDB()


class TestCreateConversation:
    def test_create_returns_uuid_string(self):
        db = _make_db_with_conversations()
        result = db.create_conversation("Test")
        assert isinstance(result, str)
        assert len(result) == 36  # UUID format

    def test_create_inserts_record(self):
        db = _make_db_with_conversations()
        db.create_conversation("My chat")
        db._cursor.execute.assert_called()

    def test_create_truncates_long_title(self):
        db = _make_db_with_conversations()
        long_title = "x" * 300
        result = db.create_conversation(long_title)
        # Should succeed without error
        assert isinstance(result, str)

    def test_create_raises_when_not_connected(self):
        from src.db.connection import DatabaseUnavailableError
        db = _make_db_with_conversations()
        db.is_connected = False
        with pytest.raises(DatabaseUnavailableError):
            db.create_conversation("test")


class TestListConversations:
    def test_list_returns_empty_when_none(self):
        db = _make_db_with_conversations()
        db._cursor.fetchall.return_value = []
        result = db.list_conversations()
        assert result == []

    def test_list_returns_rows_as_dicts(self):
        db = _make_db_with_conversations()
        from datetime import datetime
        db._cursor.fetchall.return_value = [
            ('uuid-1', 'Chat One', datetime(2025,1,1), datetime(2025,1,2), 3),
        ]
        result = db.list_conversations()
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]['id'] == 'uuid-1'

    def test_list_raises_when_not_connected(self):
        from src.db.connection import DatabaseUnavailableError
        db = _make_db_with_conversations()
        db.is_connected = False
        with pytest.raises(DatabaseUnavailableError):
            db.list_conversations()


class TestGetConversationMessages:
    def test_get_existing_returns_list(self):
        db = _make_db_with_conversations()
        from datetime import datetime
        db._cursor.fetchall.return_value = [
            ('user', 'Hello', datetime(2025,1,1)),
        ]
        result = db.get_conversation_messages('uuid-1')
        assert isinstance(result, list)
        assert result[0]['role'] == 'user'

    def test_get_nonexistent_returns_none(self):
        db = _make_db_with_conversations()
        db._cursor.fetchall.return_value = []
        db._cursor.fetchone.return_value = None  # conversation not found
        result = db.get_conversation_messages('ghost-id')
        assert result is None

    def test_get_raises_when_not_connected(self):
        from src.db.connection import DatabaseUnavailableError
        db = _make_db_with_conversations()
        db.is_connected = False
        with pytest.raises(DatabaseUnavailableError):
            db.get_conversation_messages('any-id')


class TestSaveMessage:
    def test_save_user_message(self):
        db = _make_db_with_conversations()
        db.save_message('conv-id', 'user', 'Hello!')
        db._cursor.execute.assert_called()

    def test_save_assistant_message(self):
        db = _make_db_with_conversations()
        db.save_message('conv-id', 'assistant', 'Hi there!')
        db._cursor.execute.assert_called()

    def test_save_raises_when_not_connected(self):
        from src.db.connection import DatabaseUnavailableError
        db = _make_db_with_conversations()
        db.is_connected = False
        with pytest.raises(DatabaseUnavailableError):
            db.save_message('id', 'user', 'text')


class TestUpdateConversationTitle:
    def test_update_returns_true_when_found(self):
        db = _make_db_with_conversations()
        db._cursor.rowcount = 1
        result = db.update_conversation_title('conv-id', 'New Title')
        assert result is True

    def test_update_returns_false_when_not_found(self):
        db = _make_db_with_conversations()
        db._cursor.rowcount = 0
        result = db.update_conversation_title('ghost-id', 'Title')
        assert result is False

    def test_update_raises_when_not_connected(self):
        from src.db.connection import DatabaseUnavailableError
        db = _make_db_with_conversations()
        db.is_connected = False
        with pytest.raises(DatabaseUnavailableError):
            db.update_conversation_title('id', 'title')


class TestDeleteConversation:
    def test_delete_returns_true_when_found(self):
        db = _make_db_with_conversations()
        db._cursor.rowcount = 1
        result = db.delete_conversation('conv-id')
        assert result is True

    def test_delete_returns_false_when_not_found(self):
        db = _make_db_with_conversations()
        db._cursor.rowcount = 0
        result = db.delete_conversation('ghost-id')
        assert result is False

    def test_delete_raises_when_not_connected(self):
        from src.db.connection import DatabaseUnavailableError
        db = _make_db_with_conversations()
        db.is_connected = False
        with pytest.raises(DatabaseUnavailableError):
            db.delete_conversation('id')
