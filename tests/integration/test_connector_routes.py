"""
Integration tests for connector routes (Feature 4.3).

Covers the full REST surface:
  GET  /api/connectors/types
  GET  /api/connectors
  POST /api/connectors
  GET  /api/connectors/<id>
  PUT  /api/connectors/<id>
  DELETE /api/connectors/<id>
  POST /api/connectors/<id>/sync
  GET  /api/connectors/<id>/history
  POST /api/connectors/<id>/webhook
"""

from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _connector(id="conn-1", connector_type="local_folder", enabled=True):
    return {
        "id": id,
        "workspace_id": None,
        "connector_type": connector_type,
        "display_name": "Local folder: /tmp",
        "config": {"path": "/tmp"},
        "enabled": enabled,
        "sync_interval": 900,
        "last_sync_at": None,
        "last_error": None,
        "created_at": "2026-01-01T00:00:00+00:00",
    }


# ---------------------------------------------------------------------------
# GET /api/connectors/types
# ---------------------------------------------------------------------------

class TestListConnectorTypes:

    def test_returns_200_with_types(self, client):
        resp = client.get("/api/connectors/types")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "local_folder" in data["types"]
        assert "s3" in data["types"]
        assert "webhook" in data["types"]


# ---------------------------------------------------------------------------
# GET /api/connectors
# ---------------------------------------------------------------------------

class TestListConnectors:

    def test_returns_empty_list(self, client, app):
        app.db.list_connectors = MagicMock(return_value=[])
        resp = client.get("/api/connectors")
        assert resp.status_code == 200
        assert resp.get_json()["connectors"] == []

    def test_returns_connectors(self, client, app):
        app.db.list_connectors = MagicMock(return_value=[_connector()])
        resp = client.get("/api/connectors")
        data = resp.get_json()
        assert len(data["connectors"]) == 1

    def test_db_error_returns_500(self, client, app):
        app.db.list_connectors = MagicMock(side_effect=Exception("db error"))
        resp = client.get("/api/connectors")
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# POST /api/connectors
# ---------------------------------------------------------------------------

class TestCreateConnector:

    def test_creates_local_folder_connector(self, client, app, tmp_path):
        app.db.create_connector = MagicMock(return_value="conn-new")
        app.db.get_connector = MagicMock(return_value=_connector(id="conn-new"))
        resp = client.post("/api/connectors", json={
            "connector_type": "local_folder",
            "config": {"path": str(tmp_path)},
        })
        assert resp.status_code == 201
        assert resp.get_json()["success"] is True

    def test_missing_connector_type_returns_400(self, client, app):
        resp = client.post("/api/connectors", json={"config": {}})
        assert resp.status_code == 400

    def test_unknown_connector_type_returns_400(self, client, app):
        resp = client.post("/api/connectors", json={"connector_type": "ftp"})
        assert resp.status_code == 400

    def test_invalid_config_returns_400(self, client, app):
        # local_folder with missing path
        resp = client.post("/api/connectors", json={
            "connector_type": "local_folder",
            "config": {},
        })
        assert resp.status_code == 400

    def test_nonexistent_path_returns_400(self, client, app):
        resp = client.post("/api/connectors", json={
            "connector_type": "local_folder",
            "config": {"path": "/nonexistent/path/xyz"},
        })
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/connectors/<id>
# ---------------------------------------------------------------------------

class TestGetConnector:

    def test_returns_connector(self, client, app):
        app.db.get_connector = MagicMock(return_value=_connector())
        resp = client.get("/api/connectors/conn-1")
        assert resp.status_code == 200
        assert resp.get_json()["connector"]["id"] == "conn-1"

    def test_not_found_returns_404(self, client, app):
        app.db.get_connector = MagicMock(return_value=None)
        resp = client.get("/api/connectors/missing")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /api/connectors/<id>
# ---------------------------------------------------------------------------

class TestUpdateConnector:

    def test_updates_display_name(self, client, app):
        app.db.update_connector = MagicMock(return_value=True)
        app.db.get_connector = MagicMock(
            return_value=_connector(id="conn-1")
        )
        resp = client.put("/api/connectors/conn-1", json={"display_name": "Renamed"})
        assert resp.status_code == 200

    def test_no_valid_fields_returns_400(self, client, app):
        resp = client.put("/api/connectors/conn-1", json={"owner": "bob"})
        assert resp.status_code == 400

    def test_not_found_returns_404(self, client, app):
        app.db.update_connector = MagicMock(return_value=False)
        resp = client.put("/api/connectors/missing", json={"display_name": "X"})
        assert resp.status_code == 404

    def test_disabling_removes_from_registry(self, client, app):
        app.db.update_connector = MagicMock(return_value=True)
        app.db.get_connector = MagicMock(
            return_value=_connector(id="conn-1", enabled=False)
        )
        mock_registry = MagicMock()
        with patch("src.routes.connector_routes.connector_registry", mock_registry):
            resp = client.put("/api/connectors/conn-1", json={"enabled": False})
        assert resp.status_code == 200
        mock_registry.remove.assert_called_once_with("conn-1")


# ---------------------------------------------------------------------------
# DELETE /api/connectors/<id>
# ---------------------------------------------------------------------------

class TestDeleteConnector:

    def test_deletes_connector(self, client, app):
        app.db.delete_connector = MagicMock(return_value=True)
        mock_registry = MagicMock()
        with patch("src.routes.connector_routes.connector_registry", mock_registry):
            resp = client.delete("/api/connectors/conn-1")
        assert resp.status_code == 200
        mock_registry.remove.assert_called_once_with("conn-1")

    def test_not_found_returns_404(self, client, app):
        app.db.delete_connector = MagicMock(return_value=False)
        resp = client.delete("/api/connectors/missing")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/connectors/<id>/sync
# ---------------------------------------------------------------------------

class TestTriggerSync:

    def test_triggers_sync(self, client, app):
        mock_instance = MagicMock()
        mock_worker = MagicMock()
        app.sync_worker = mock_worker
        with patch("src.routes.connector_routes.connector_registry") as mock_reg:
            mock_reg.get.return_value = mock_instance
            resp = client.post("/api/connectors/conn-1/sync")
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_connector_not_loaded_returns_404(self, client, app):
        with patch("src.routes.connector_routes.connector_registry") as mock_reg:
            mock_reg.get.return_value = None
            resp = client.post("/api/connectors/conn-1/sync")
        assert resp.status_code == 404

    def test_no_worker_returns_503(self, client, app):
        app.sync_worker = None
        with patch("src.routes.connector_routes.connector_registry") as mock_reg:
            mock_reg.get.return_value = MagicMock()
            resp = client.post("/api/connectors/conn-1/sync")
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# GET /api/connectors/<id>/history
# ---------------------------------------------------------------------------

class TestSyncHistory:

    def test_returns_history(self, client, app):
        history = [
            {"id": 1, "started_at": "2026-01-01T00:00:00+00:00",
             "finished_at": "2026-01-01T00:00:01+00:00",
             "files_added": 3, "files_updated": 0, "files_deleted": 0, "error": None}
        ]
        app.db.get_connector_sync_history = MagicMock(return_value=history)
        resp = client.get("/api/connectors/conn-1/history")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["history"]) == 1
        assert data["history"][0]["files_added"] == 3

    def test_limit_capped_at_100(self, client, app):
        app.db.get_connector_sync_history = MagicMock(return_value=[])
        resp = client.get("/api/connectors/conn-1/history?limit=999")
        assert resp.status_code == 200
        app.db.get_connector_sync_history.assert_called_once_with("conn-1", limit=100)


# ---------------------------------------------------------------------------
# POST /api/connectors/<id>/webhook
# ---------------------------------------------------------------------------

class TestWebhookReceiver:

    def test_accepts_valid_added_event(self, client, app):
        app.db.get_connector = MagicMock(return_value=_connector(connector_type="webhook"))
        mock_instance = MagicMock()
        mock_instance.push_event.return_value = []
        with patch("src.routes.connector_routes.connector_registry") as mock_reg:
            mock_reg.get.return_value = mock_instance
            resp = client.post("/api/connectors/conn-1/webhook", json={
                "event_type": "added",
                "source_id": "doc-1",
                "filename": "report.pdf",
                "fetch_url": "http://example.com/report.pdf",
            })
        assert resp.status_code == 200

    def test_wrong_connector_type_returns_400(self, client, app):
        app.db.get_connector = MagicMock(return_value=_connector(connector_type="local_folder"))
        resp = client.post("/api/connectors/conn-1/webhook", json={})
        assert resp.status_code == 400

    def test_connector_not_found_returns_404(self, client, app):
        app.db.get_connector = MagicMock(return_value=None)
        resp = client.post("/api/connectors/missing/webhook", json={})
        assert resp.status_code == 404

    def test_invalid_payload_returns_400(self, client, app):
        app.db.get_connector = MagicMock(return_value=_connector(connector_type="webhook"))
        mock_instance = MagicMock()
        mock_instance.push_event.return_value = ["'source_id' is required"]
        with patch("src.routes.connector_routes.connector_registry") as mock_reg:
            mock_reg.get.return_value = mock_instance
            resp = client.post("/api/connectors/conn-1/webhook", json={})
        assert resp.status_code == 400

    def test_bad_secret_returns_403(self, client, app):
        connector = _connector(connector_type="webhook")
        connector["config"] = {"secret": "correct-secret"}
        app.db.get_connector = MagicMock(return_value=connector)
        with patch("src.routes.connector_routes.connector_registry") as mock_reg:
            mock_reg.get.return_value = MagicMock()
            resp = client.post(
                "/api/connectors/conn-1/webhook",
                json={"event_type": "added", "source_id": "x", "fetch_url": "http://x"},
                headers={"X-LocalChat-Secret": "wrong-secret"},
            )
        assert resp.status_code == 403

    def test_correct_secret_accepted(self, client, app):
        connector = _connector(connector_type="webhook")
        connector["config"] = {"secret": "correct-secret"}
        app.db.get_connector = MagicMock(return_value=connector)
        mock_instance = MagicMock()
        mock_instance.push_event.return_value = []
        with patch("src.routes.connector_routes.connector_registry") as mock_reg:
            mock_reg.get.return_value = mock_instance
            resp = client.post(
                "/api/connectors/conn-1/webhook",
                json={"event_type": "deleted", "source_id": "doc-1"},
                headers={"X-LocalChat-Secret": "correct-secret"},
            )
        assert resp.status_code == 200

    def test_instance_not_active_returns_503(self, client, app):
        app.db.get_connector = MagicMock(return_value=_connector(connector_type="webhook"))
        with patch("src.routes.connector_routes.connector_registry") as mock_reg:
            mock_reg.get.return_value = None
            resp = client.post("/api/connectors/conn-1/webhook", json={})
        assert resp.status_code == 503
