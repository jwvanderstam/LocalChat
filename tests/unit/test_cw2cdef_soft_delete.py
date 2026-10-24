"""CW-2c/2d/2e/2f: route-level unit tests for workspace, memory, annotation, and connector soft-delete + purge."""

from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Workspaces (CW-2c)
# ---------------------------------------------------------------------------

class TestDeleteWorkspace:
    def test_soft_delete_returns_200(self, client, app):
        app.state.db.members.role = MagicMock(return_value=None)
        app.state.db.workspaces.retire = MagicMock(return_value=True)
        app.state.db.workspaces.default_id = MagicMock(return_value="fallback-id")
        resp = client.delete("/api/workspaces/some-ws-id")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_delete_missing_workspace_returns_404(self, client, app):
        app.state.db.members.role = MagicMock(return_value=None)
        app.state.db.workspaces.retire = MagicMock(return_value=False)
        resp = client.delete("/api/workspaces/ghost-id")
        assert resp.status_code == 404

    def test_delete_passes_deleted_by(self, client, app):
        app.state.db.members.role = MagicMock(return_value=None)
        app.state.db.workspaces.retire = MagicMock(return_value=True)
        app.state.db.workspaces.default_id = MagicMock(return_value=None)
        client.delete("/api/workspaces/some-ws-id")
        app.state.db.workspaces.retire.assert_called_once()


class TestPurgeWorkspace:
    def test_purge_succeeds_when_empty(self, client, app):
        app.state.db.workspaces.purge = MagicMock(return_value=True)
        resp = client.delete("/api/workspaces/some-ws-id/purge")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_purge_blocked_returns_409(self, client, app):
        app.state.db.workspaces.purge = MagicMock(return_value=False)
        resp = client.delete("/api/workspaces/some-ws-id/purge")
        assert resp.status_code == 409
        assert "purged" in resp.json()["message"].lower()


# ---------------------------------------------------------------------------
# Memories (CW-2d)
# ---------------------------------------------------------------------------

class TestDeleteMemory:
    def test_soft_delete_returns_200(self, client, app):
        app.state.db.memories.retire = MagicMock(return_value=True)
        resp = client.delete("/api/memory/some-memory-id")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_delete_missing_memory_returns_404(self, client, app):
        app.state.db.memories.retire = MagicMock(return_value=False)
        resp = client.delete("/api/memory/ghost-id")
        assert resp.status_code == 404

    def test_delete_all_returns_count(self, client, app):
        app.state.db.memories.retire_all = MagicMock(return_value=7)
        resp = client.delete("/api/memory/")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 7


# ---------------------------------------------------------------------------
# Annotations (CW-2e)
# ---------------------------------------------------------------------------

class TestDeleteAnnotation:
    def test_soft_delete_returns_200(self, client, app):
        app.state.db.annotations.retire = MagicMock(return_value=True)
        resp = client.delete("/api/annotations/some-ann-id")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_delete_missing_annotation_returns_404(self, client, app):
        app.state.db.annotations.retire = MagicMock(return_value=False)
        resp = client.delete("/api/annotations/ghost-id")
        assert resp.status_code == 404

    def test_delete_passes_deleted_by(self, client, app):
        app.state.db.annotations.retire = MagicMock(return_value=True)
        client.delete("/api/annotations/some-ann-id")
        app.state.db.annotations.retire.assert_called_once()


# ---------------------------------------------------------------------------
# Connectors (CW-2f)
# ---------------------------------------------------------------------------

class TestDeleteConnector:
    def test_soft_delete_returns_200(self, client, app):
        app.state.db.connectors.retire = MagicMock(return_value=True)
        app.state.connector_registry = MagicMock()
        resp = client.delete("/api/connectors/some-conn-id")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_delete_missing_connector_returns_404(self, client, app):
        app.state.db.connectors.retire = MagicMock(return_value=False)
        app.state.connector_registry = MagicMock()
        resp = client.delete("/api/connectors/ghost-id")
        assert resp.status_code == 404

    def test_registry_remove_called_on_success(self, client, app):
        app.state.db.connectors.retire = MagicMock(return_value=True)
        registry = MagicMock()
        app.state.connector_registry = registry
        client.delete("/api/connectors/some-conn-id")
        registry.remove.assert_called_once_with("some-conn-id")


class TestPurgeConnector:
    def test_purge_succeeds_when_no_documents(self, client, app):
        app.state.db.connectors.purge = MagicMock(return_value=True)
        resp = client.delete("/api/connectors/some-conn-id/purge")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_purge_blocked_by_documents_returns_409(self, client, app):
        app.state.db.connectors.purge = MagicMock(return_value=False)
        resp = client.delete("/api/connectors/some-conn-id/purge")
        assert resp.status_code == 409
        assert "purged" in resp.json()["message"].lower()
