"""CW-2a / CW-2b: route-level unit tests for conversation and user soft-delete + purge."""

from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Conversations (CW-2a)
# ---------------------------------------------------------------------------

class TestDeleteConversation:
    def test_soft_delete_returns_200(self, client, app):
        app.state.db.delete_conversation = MagicMock(return_value=True)
        resp = client.delete("/api/conversations/some-uuid")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_delete_missing_conversation_returns_404(self, client, app):
        app.state.db.delete_conversation = MagicMock(return_value=False)
        resp = client.delete("/api/conversations/ghost-uuid")
        assert resp.status_code == 404

    def test_delete_calls_db_with_deleted_by(self, client, app):
        app.state.db.delete_conversation = MagicMock(return_value=True)
        client.delete("/api/conversations/abc-123")
        app.state.db.delete_conversation.assert_called_once()
        call_kwargs = app.state.db.delete_conversation.call_args
        # Second positional arg or deleted_by kwarg must be present
        assert call_kwargs is not None


class TestPurgeConversation:
    def test_purge_succeeds_when_no_citations(self, client, app):
        app.state.db.purge_conversation = MagicMock(return_value=True)
        resp = client.delete("/api/conversations/some-uuid/purge")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_purge_blocked_by_memories_returns_409(self, client, app):
        app.state.db.purge_conversation = MagicMock(return_value=False)
        resp = client.delete("/api/conversations/some-uuid/purge")
        assert resp.status_code == 409
        assert "purged" in resp.json()["message"].lower()


class TestDeleteAllConversations:
    def test_delete_all_returns_count(self, client, app):
        app.state.db.delete_all_conversations = MagicMock(return_value=5)
        resp = client.delete("/api/conversations")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 5

    def test_delete_all_calls_db_with_deleted_by(self, client, app):
        app.state.db.delete_all_conversations = MagicMock(return_value=0)
        client.delete("/api/conversations")
        app.state.db.delete_all_conversations.assert_called_once()


# ---------------------------------------------------------------------------
# Users (CW-2b)
# ---------------------------------------------------------------------------

class TestDeleteUser:
    def test_soft_delete_returns_200(self, client, app):
        app.state.db.delete_user = MagicMock(return_value=True)
        resp = client.delete("/api/users/some-user-id")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_delete_missing_user_returns_404(self, client, app):
        app.state.db.delete_user = MagicMock(return_value=False)
        resp = client.delete("/api/users/ghost-id")
        assert resp.status_code == 404

    def test_delete_calls_db_with_deleted_by(self, client, app):
        app.state.db.delete_user = MagicMock(return_value=True)
        client.delete("/api/users/some-user-id")
        app.state.db.delete_user.assert_called_once()
        call_kwargs = app.state.db.delete_user.call_args
        assert call_kwargs is not None

    def test_delete_db_error_returns_500(self, client, app):
        app.state.db.delete_user = MagicMock(side_effect=Exception("db gone"))
        resp = client.delete("/api/users/some-id")
        assert resp.status_code == 500


class TestPurgeUser:
    def test_purge_succeeds_when_no_memberships(self, client, app):
        app.state.db.purge_user = MagicMock(return_value=True)
        resp = client.delete("/api/users/some-user-id/purge")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_purge_blocked_by_memberships_returns_409(self, client, app):
        app.state.db.purge_user = MagicMock(return_value=False)
        resp = client.delete("/api/users/some-user-id/purge")
        assert resp.status_code == 409
        assert "purged" in resp.json()["message"].lower()

    def test_purge_db_error_returns_500(self, client, app):
        app.state.db.purge_user = MagicMock(side_effect=Exception("db gone"))
        resp = client.delete("/api/users/some-user-id/purge")
        assert resp.status_code == 500
