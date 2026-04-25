"""Tests for ConversationsMixin (db/conversations.py)."""

from unittest.mock import MagicMock, call, patch

import pytest


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


class TestCreateConversationWithMessage:
    def test_raises_when_not_connected(self):
        from src.db.connection import DatabaseUnavailableError
        db = _make_db_with_conversations()
        db.is_connected = False
        with pytest.raises(DatabaseUnavailableError):
            db.create_conversation_with_message("title", "user", "hello")

    def test_returns_conversation_id_and_message_id(self):
        db = _make_db_with_conversations()
        db._cursor.fetchone.return_value = (42,)
        conv_id, msg_id = db.create_conversation_with_message("Test", "user", "Hello")
        assert isinstance(conv_id, str)
        assert len(conv_id) == 36  # UUID
        assert msg_id == 42

    def test_executes_two_inserts(self):
        db = _make_db_with_conversations()
        db._cursor.fetchone.return_value = (1,)
        db.create_conversation_with_message("Chat", "user", "Hi")
        assert db._cursor.execute.call_count == 2

    def test_commits_transaction(self):
        db = _make_db_with_conversations()
        db._cursor.fetchone.return_value = (7,)
        db.create_conversation_with_message("Chat", "user", "Hi")
        db._conn.commit.assert_called_once()

    def test_with_plan_json_passes_jsonb(self):
        db = _make_db_with_conversations()
        db._cursor.fetchone.return_value = (5,)
        plan = {"intent": "search", "steps": ["step1"]}
        conv_id, msg_id = db.create_conversation_with_message(
            "Chat", "user", "Hi", plan_json=plan
        )
        assert isinstance(conv_id, str)
        assert msg_id == 5
        # Second execute call should include a Jsonb-wrapped plan
        second_call_args = db._cursor.execute.call_args_list[1][0][1]
        from psycopg.types.json import Jsonb
        assert isinstance(second_call_args[3], Jsonb)

    def test_without_plan_json_passes_none(self):
        db = _make_db_with_conversations()
        db._cursor.fetchone.return_value = (3,)
        db.create_conversation_with_message("Chat", "user", "Hi")
        second_call_args = db._cursor.execute.call_args_list[1][0][1]
        assert second_call_args[3] is None

    def test_title_truncated_to_255_chars(self):
        db = _make_db_with_conversations()
        db._cursor.fetchone.return_value = (1,)
        long_title = "x" * 300
        db.create_conversation_with_message(long_title, "user", "Hi")
        first_call_args = db._cursor.execute.call_args_list[0][0][1]
        assert len(first_call_args[1]) == 255

    def test_workspace_id_passed_through(self):
        db = _make_db_with_conversations()
        db._cursor.fetchone.return_value = (2,)
        db.create_conversation_with_message("Chat", "user", "Hi", workspace_id="ws-123")
        first_call_args = db._cursor.execute.call_args_list[0][0][1]
        assert first_call_args[2] == "ws-123"
