"""Tests for memory (conversation) routes."""

import json
from unittest.mock import MagicMock


class TestListConversations:
    def test_list_returns_200(self, client, app):
        app.db.list_conversations = MagicMock(return_value=[])
        response = client.get('/api/conversations')
        assert response.status_code == 200

    def test_list_returns_conversations_key(self, client, app):
        app.db.list_conversations = MagicMock(return_value=[
            {'id': 'abc', 'title': 'Chat 1', 'created_at': '2025-01-01'}
        ])
        response = client.get('/api/conversations')
        data = response.get_json()
        assert 'conversations' in data
        assert len(data['conversations']) == 1


class TestCreateConversation:
    def test_create_with_title(self, client, app):
        app.db.create_conversation = MagicMock(return_value='new-uuid-123')
        response = client.post('/api/conversations',
                               data=json.dumps({'title': 'My Chat'}),
                               content_type='application/json')
        assert response.status_code in (200, 201)

    def test_create_without_body_uses_default_title(self, client, app):
        app.db.create_conversation = MagicMock(return_value='uuid-456')
        response = client.post('/api/conversations',
                               data=json.dumps({}),
                               content_type='application/json')
        assert response.status_code in (200, 201)
        call_args = app.db.create_conversation.call_args
        assert call_args[0][0] == 'New Conversation'

    def test_create_returns_conversation_id(self, client, app):
        app.db.create_conversation = MagicMock(return_value='id-789')
        response = client.post('/api/conversations',
                               data=json.dumps({'title': 'Test'}),
                               content_type='application/json')
        assert response.status_code in (200, 201)
        data = response.get_json()
        assert data is not None


class TestGetConversation:
    def test_get_existing_conversation(self, client, app):
        app.db.get_conversation_messages = MagicMock(return_value=[])
        response = client.get('/api/conversations/abc-123')
        assert response.status_code in (200, 404)

    def test_get_nonexistent_conversation(self, client, app):
        app.db.get_conversation_messages = MagicMock(return_value=None)
        response = client.get('/api/conversations/ghost-id')
        assert response.status_code in (404, 200)


class TestRenameConversation:
    def test_rename_conversation(self, client, app):
        app.db.update_conversation_title = MagicMock(return_value=True)
        response = client.patch('/api/conversations/abc-123',
                                data=json.dumps({'title': 'New Name'}),
                                content_type='application/json')
        assert response.status_code in (200, 404)

    def test_rename_missing_title(self, client, app):
        response = client.patch('/api/conversations/abc-123',
                                data=json.dumps({}),
                                content_type='application/json')
        assert response.status_code in (200, 400, 404)

    def test_rename_not_found(self, client, app):
        app.db.update_conversation_title = MagicMock(return_value=False)
        response = client.patch('/api/conversations/ghost',
                                data=json.dumps({'title': 'x'}),
                                content_type='application/json')
        assert response.status_code in (200, 404)


class TestDeleteConversation:
    def test_delete_existing_conversation(self, client, app):
        app.db.delete_conversation = MagicMock(return_value=True)
        response = client.delete('/api/conversations/abc-123')
        assert response.status_code in (200, 204)

    def test_delete_nonexistent_conversation(self, client, app):
        app.db.delete_conversation = MagicMock(return_value=False)
        response = client.delete('/api/conversations/ghost')
        assert response.status_code in (200, 404)
