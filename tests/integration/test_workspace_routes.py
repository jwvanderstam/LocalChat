"""
Integration tests for workspace routes (Feature 4.2).

Covers the full REST surface:
  GET  /api/workspaces
  POST /api/workspaces
  GET  /api/workspaces/<id>
  PUT  /api/workspaces/<id>
  DELETE /api/workspaces/<id>
  GET  /api/workspaces/active
  POST /api/workspaces/switch
"""

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _workspace(id="ws-1", name="Test WS", active=False):
    return {
        "id": id,
        "name": name,
        "description": "",
        "system_prompt": "",
        "model_class": None,
        "created_at": "2026-01-01T00:00:00+00:00",
        "active": active,
        "document_count": 0,
        "conversation_count": 0,
    }


# ---------------------------------------------------------------------------
# GET /api/workspaces
# ---------------------------------------------------------------------------

class TestListWorkspaces:

    def test_returns_200(self, client, app):
        app.db.list_workspaces = MagicMock(return_value=[])
        with patch("src.routes.workspace_routes.config") as mock_cfg:
            mock_cfg.app_state.get_active_workspace_id.return_value = None
            resp = client.get("/api/workspaces")
        assert resp.status_code == 200

    def test_returns_workspaces_list(self, client, app):
        ws = _workspace()
        app.db.list_workspaces = MagicMock(return_value=[ws])
        with patch("src.routes.workspace_routes.config") as mock_cfg:
            mock_cfg.app_state.get_active_workspace_id.return_value = None
            resp = client.get("/api/workspaces")
        data = resp.get_json()
        assert data["success"] is True
        assert len(data["workspaces"]) == 1

    def test_active_flag_set_on_matching_workspace(self, client, app):
        ws = _workspace(id="ws-active")
        app.db.list_workspaces = MagicMock(return_value=[ws])
        with patch("src.routes.workspace_routes.config") as mock_cfg:
            mock_cfg.app_state.get_active_workspace_id.return_value = "ws-active"
            resp = client.get("/api/workspaces")
        data = resp.get_json()
        assert data["workspaces"][0]["active"] is True

    def test_db_error_returns_500(self, client, app):
        app.db.list_workspaces = MagicMock(side_effect=Exception("db down"))
        with patch("src.routes.workspace_routes.config") as mock_cfg:
            mock_cfg.app_state.get_active_workspace_id.return_value = None
            resp = client.get("/api/workspaces")
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# POST /api/workspaces
# ---------------------------------------------------------------------------

class TestCreateWorkspace:

    def test_creates_workspace_returns_201(self, client, app):
        app.db.create_workspace = MagicMock(return_value="ws-new")
        app.db.get_workspace = MagicMock(return_value=_workspace(id="ws-new", name="New"))
        resp = client.post("/api/workspaces", json={"name": "New"})
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["success"] is True
        assert data["workspace"]["id"] == "ws-new"

    def test_missing_name_returns_400(self, client, app):
        resp = client.post("/api/workspaces", json={})
        assert resp.status_code == 400

    def test_empty_name_returns_400(self, client, app):
        resp = client.post("/api/workspaces", json={"name": "   "})
        assert resp.status_code == 400

    def test_passes_optional_fields(self, client, app):
        app.db.create_workspace = MagicMock(return_value="ws-2")
        app.db.get_workspace = MagicMock(return_value=_workspace(id="ws-2"))
        resp = client.post("/api/workspaces", json={
            "name": "Legal",
            "description": "Legal docs",
            "system_prompt": "You are a legal assistant.",
            "model_class": "LARGE",
            "sync_interval": 1800,
        })
        assert resp.status_code == 201
        app.db.create_workspace.assert_called_once_with(
            name="Legal",
            description="Legal docs",
            system_prompt="You are a legal assistant.",
            model_class="LARGE",
        )


# ---------------------------------------------------------------------------
# GET /api/workspaces/<id>
# ---------------------------------------------------------------------------

class TestGetWorkspace:

    def test_returns_workspace(self, client, app):
        app.db.get_workspace = MagicMock(return_value=_workspace())
        with patch("src.routes.workspace_routes.config") as mock_cfg:
            mock_cfg.app_state.get_active_workspace_id.return_value = None
            resp = client.get("/api/workspaces/ws-1")
        assert resp.status_code == 200
        assert resp.get_json()["workspace"]["id"] == "ws-1"

    def test_not_found_returns_404(self, client, app):
        app.db.get_workspace = MagicMock(return_value=None)
        with patch("src.routes.workspace_routes.config") as mock_cfg:
            mock_cfg.app_state.get_active_workspace_id.return_value = None
            resp = client.get("/api/workspaces/missing")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /api/workspaces/<id>
# ---------------------------------------------------------------------------

class TestUpdateWorkspace:

    def test_updates_and_returns_workspace(self, client, app):
        app.db.update_workspace = MagicMock(return_value=True)
        app.db.get_workspace = MagicMock(return_value=_workspace(name="Renamed"))
        resp = client.put("/api/workspaces/ws-1", json={"name": "Renamed"})
        assert resp.status_code == 200
        assert resp.get_json()["workspace"]["name"] == "Renamed"

    def test_no_valid_fields_returns_400(self, client, app):
        resp = client.put("/api/workspaces/ws-1", json={"owner": "bob"})
        assert resp.status_code == 400

    def test_not_found_returns_404(self, client, app):
        app.db.update_workspace = MagicMock(return_value=False)
        resp = client.put("/api/workspaces/ws-x", json={"name": "X"})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/workspaces/<id>
# ---------------------------------------------------------------------------

class TestDeleteWorkspace:

    def test_deletes_workspace(self, client, app):
        app.db.delete_workspace = MagicMock(return_value=True)
        with patch("src.routes.workspace_routes.config") as mock_cfg:
            mock_cfg.app_state.get_active_workspace_id.return_value = None
            resp = client.delete("/api/workspaces/ws-1")
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_not_found_returns_404(self, client, app):
        app.db.delete_workspace = MagicMock(return_value=False)
        with patch("src.routes.workspace_routes.config") as mock_cfg:
            mock_cfg.app_state.get_active_workspace_id.return_value = None
            resp = client.delete("/api/workspaces/missing")
        assert resp.status_code == 404

    def test_clears_active_if_deleted_was_active(self, client, app):
        app.db.delete_workspace = MagicMock(return_value=True)
        app.db.get_default_workspace_id = MagicMock(return_value="ws-default")
        with patch("src.routes.workspace_routes.config") as mock_cfg:
            mock_cfg.app_state.get_active_workspace_id.return_value = "ws-1"
            resp = client.delete("/api/workspaces/ws-1")
        assert resp.status_code == 200
        mock_cfg.app_state.set_active_workspace_id.assert_called_once_with("ws-default")


# ---------------------------------------------------------------------------
# GET /api/workspaces/active
# ---------------------------------------------------------------------------

class TestGetActiveWorkspace:

    def test_returns_none_when_no_active(self, client, app):
        with patch("src.routes.workspace_routes.config") as mock_cfg:
            mock_cfg.app_state.get_active_workspace_id.return_value = None
            resp = client.get("/api/workspaces/active")
        data = resp.get_json()
        assert data["success"] is True
        assert data["workspace"] is None

    def test_returns_active_workspace(self, client, app):
        app.db.get_workspace = MagicMock(return_value=_workspace(id="ws-1"))
        with patch("src.routes.workspace_routes.config") as mock_cfg:
            mock_cfg.app_state.get_active_workspace_id.return_value = "ws-1"
            resp = client.get("/api/workspaces/active")
        data = resp.get_json()
        assert data["workspace"]["id"] == "ws-1"


# ---------------------------------------------------------------------------
# POST /api/workspaces/switch
# ---------------------------------------------------------------------------

class TestSwitchWorkspace:

    def test_switches_successfully(self, client, app):
        app.db.get_workspace = MagicMock(return_value=_workspace(id="ws-2", name="Proj"))
        with patch("src.routes.workspace_routes.config") as mock_cfg:
            resp = client.post("/api/workspaces/switch", json={"workspace_id": "ws-2"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["workspace"]["name"] == "Proj"

    def test_missing_workspace_id_returns_400(self, client, app):
        resp = client.post("/api/workspaces/switch", json={})
        assert resp.status_code == 400

    def test_not_found_returns_404(self, client, app):
        app.db.get_workspace = MagicMock(return_value=None)
        resp = client.post("/api/workspaces/switch", json={"workspace_id": "ws-ghost"})
        assert resp.status_code == 404
