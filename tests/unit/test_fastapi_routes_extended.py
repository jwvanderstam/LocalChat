"""Extended FastAPI route unit tests.

Covers: document, connector, workspace, settings, api (plugins/chat) routes.
Uses the same minimal-app pattern as test_fastapi_routes.py.

Markers: unit (fast, no external services)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers (mirrors test_fastapi_routes.py)
# ---------------------------------------------------------------------------

def _base_state() -> MagicMock:
    state = MagicMock()
    state.testing = True
    state.startup_status = {"database": True, "ollama": True, "ready": True}
    state.db.is_connected = True
    return state


def _make_client(router, prefix: str, state: MagicMock | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix=prefix)
    app.state = state or _base_state()
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Document routes
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestDocumentRoutesExtended:
    def _client(self):
        from src.routes_fastapi.document_routes import router

        state = _base_state()
        state.db.get_all_documents.return_value = [{"id": 1, "filename": "report.pdf"}]
        state.db.get_document_count.return_value = 1
        state.db.get_chunk_count.return_value = 10
        state.db.get_chunk_statistics.return_value = {"avg_length": 400}
        state.db.delete_document.return_value = None
        state.db.delete_all_documents.return_value = None
        state.db.search_chunks_by_text.return_value = []
        state.doc_processor.retrieve_context.return_value = []
        return _make_client(router, "/api/documents", state)

    def test_list_documents(self):
        client = self._client()
        resp = client.get("/api/documents/list")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["documents"]) == 1

    def test_document_stats(self):
        client = self._client()
        resp = client.get("/api/documents/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["document_count"] == 1
        assert data["chunk_count"] == 10

    def test_search_text_missing_field(self):
        client = self._client()
        resp = client.post("/api/documents/search-text", json={})
        assert resp.status_code == 400

    def test_search_text_success(self):
        client = self._client()
        resp = client.post("/api/documents/search-text", json={"search_text": "quarterly report"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["count"] == 0

    def test_test_retrieval_no_query(self):
        client = self._client()
        resp = client.post("/api/documents/test", json={})
        assert resp.status_code == 400

    def test_test_retrieval_success(self):
        client = self._client()
        resp = client.post("/api/documents/test", json={"query": "what is the revenue?"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "results" in data

    def test_chunk_context_not_found(self):
        from src.routes_fastapi.document_routes import router

        state = _base_state()
        state.db.get_chunk_by_id.return_value = None
        client = _make_client(router, "/api/documents", state)
        resp = client.get("/api/documents/chunks/999/context")
        assert resp.status_code == 404

    def test_chunk_context_found(self):
        from src.routes_fastapi.document_routes import router

        state = _base_state()
        state.db.get_chunk_by_id.return_value = {"document_id": 1, "chunk_index": 2}
        state.db.get_adjacent_chunks.return_value = [("chunk text", 2)]
        client = _make_client(router, "/api/documents", state)
        resp = client.get("/api/documents/chunks/1/context")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["chunks"]) == 1

    def test_delete_document(self):
        from src.routes_fastapi.document_routes import router

        state = _base_state()
        state.db.delete_document.return_value = None
        state.db.get_document_count.return_value = 0
        client = _make_client(router, "/api/documents", state)
        with patch("src.routes_fastapi.document_routes.config") as mc:
            mc.app_state = MagicMock()
            mc.UPLOAD_FOLDER = "/tmp"
            mc.SUPPORTED_EXTENSIONS = {".pdf", ".docx"}
            mc.MAX_CONTEXT_LENGTH = 4000
            resp = client.delete("/api/documents/1")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_clear_documents(self):
        from src.routes_fastapi.document_routes import router

        state = _base_state()
        state.db.delete_all_documents.return_value = None
        client = _make_client(router, "/api/documents", state)
        with patch("src.routes_fastapi.document_routes.config") as mc:
            mc.app_state = MagicMock()
            resp = client.delete("/api/documents/clear")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ---------------------------------------------------------------------------
# Connector routes
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestConnectorRoutesExtended:
    def _client(self):
        from src.routes_fastapi.connector_routes import router

        state = _base_state()
        state.db.list_connectors.return_value = []
        return _make_client(router, "/api", state)

    def test_list_available_connectors_no_user(self):
        client = self._client()
        resp = client.get("/api/connectors/available")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert isinstance(data["available"], list)

    def test_list_connector_types(self):
        from src.routes_fastapi.connector_routes import router

        state = _base_state()
        client = _make_client(router, "/api", state)
        with patch("src.routes_fastapi.connector_routes.connector_registry") as mock_reg:
            mock_reg.available_types.return_value = ["local_folder", "s3", "google_drive"]
            resp = client.get("/api/connectors/types")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert "local_folder" in resp.json()["types"]

    def test_list_connectors(self):
        client = self._client()
        resp = client.get("/api/connectors")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["connectors"] == []

    def test_create_connector_missing_type(self):
        client = self._client()
        resp = client.post("/api/connectors", json={"display_name": "My Drive"})
        assert resp.status_code == 400

    def test_create_connector_unknown_type(self):
        from src.routes_fastapi.connector_routes import router

        state = _base_state()
        client = _make_client(router, "/api", state)
        with patch("src.routes_fastapi.connector_routes.connector_registry") as mock_reg:
            mock_reg.available_types.return_value = ["local_folder"]
            resp = client.post("/api/connectors", json={"connector_type": "nonexistent"})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Workspace routes
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestWorkspaceRoutesExtended:
    def _client(self):
        from src.routes_fastapi.workspace_routes import router

        state = _base_state()
        state.db.list_workspaces.return_value = [{"id": "ws-1", "name": "Acme"}]
        state.db.get_workspace.return_value = {"id": "ws-1", "name": "Acme"}
        state.db.create_workspace.return_value = "ws-new"
        state.db.update_workspace.return_value = True
        state.db.delete_workspace.return_value = True
        state.db.get_default_workspace_id.return_value = "ws-default"
        state.db.list_workspace_members.return_value = []
        state.db.get_workspace_member_role.return_value = None
        return _make_client(router, "/api", state)

    def test_list_workspaces(self):
        client = self._client()
        resp = client.get("/api/workspaces")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["workspaces"]) == 1

    def test_create_workspace_missing_name(self):
        client = self._client()
        resp = client.post("/api/workspaces", json={"description": "no name"})
        assert resp.status_code == 400

    def test_create_workspace_success(self):
        client = self._client()
        resp = client.post("/api/workspaces", json={"name": "Engineering"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["success"] is True

    def test_get_active_workspace_none(self):
        from src.routes_fastapi.workspace_routes import router

        state = _base_state()
        client = _make_client(router, "/api", state)
        resp = client.get("/api/workspaces/active")
        assert resp.status_code == 200
        assert resp.json()["workspace"] is None

    def test_get_workspace_found(self):
        client = self._client()
        resp = client.get("/api/workspaces/ws-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["workspace"]["id"] == "ws-1"

    def test_get_workspace_not_found(self):
        from src.routes_fastapi.workspace_routes import router

        state = _base_state()
        state.db.get_workspace.return_value = None
        client = _make_client(router, "/api", state)
        resp = client.get("/api/workspaces/missing")
        assert resp.status_code == 404

    def test_update_workspace_no_fields(self):
        client = self._client()
        resp = client.put("/api/workspaces/ws-1", json={"unknown_field": "x"})
        assert resp.status_code == 400

    def test_update_workspace_success(self):
        client = self._client()
        resp = client.put("/api/workspaces/ws-1", json={"name": "New Name"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_delete_workspace(self):
        client = self._client()
        resp = client.delete("/api/workspaces/ws-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["fallback_workspace_id"] == "ws-default"

    def test_delete_workspace_not_found(self):
        from src.routes_fastapi.workspace_routes import router

        state = _base_state()
        state.db.delete_workspace.return_value = False
        state.db.get_workspace_member_role.return_value = None
        client = _make_client(router, "/api", state)
        resp = client.delete("/api/workspaces/ghost")
        assert resp.status_code == 404

    def test_list_workspace_members(self):
        client = self._client()
        resp = client.get("/api/workspaces/ws-1/members")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["members"] == []

    def test_add_workspace_member_missing_user_id(self):
        client = self._client()
        resp = client.post("/api/workspaces/ws-1/members", json={"role": "viewer"})
        assert resp.status_code == 400

    def test_add_workspace_member_invalid_role(self):
        client = self._client()
        resp = client.post("/api/workspaces/ws-1/members", json={"user_id": "u1", "role": "superadmin"})
        assert resp.status_code == 400

    def test_switch_workspace_missing_id(self):
        client = self._client()
        resp = client.post("/api/workspaces/switch", json={})
        assert resp.status_code == 400

    def test_switch_workspace_success(self):
        client = self._client()
        resp = client.post("/api/workspaces/switch", json={"workspace_id": "ws-1"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ---------------------------------------------------------------------------
# Settings routes
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSettingsRoutesExtended:
    def _client(self):
        from src.routes_fastapi.settings_routes import router

        state = _base_state()
        state.db.get_document_count.return_value = 5
        state.db.get_chunk_count.return_value = 50
        state.ollama_client.get_running_models.return_value = []
        state.ollama_client.get_gpu_info.return_value = []
        state.embedding_cache = None
        state.query_cache = None
        return _make_client(router, "/api", state)

    def test_rag_params_get(self):
        client = self._client()
        with patch("src.routes_fastapi.settings_routes.config") as mc:
            mc.TOP_K_RESULTS = 20
            mc.RERANK_TOP_K = 10
            mc.DIVERSITY_THRESHOLD = 0.70
            mc.SEMANTIC_WEIGHT = 0.70
            resp = client.get("/api/settings/rag")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "TOP_K_RESULTS" in data["params"]

    def test_rag_params_set_unknown_key(self):
        client = self._client()
        resp = client.post("/api/settings/rag", json={"UNKNOWN_PARAM": 99})
        assert resp.status_code == 400

    def test_rag_params_set_out_of_range(self):
        client = self._client()
        with patch("src.routes_fastapi.settings_routes.config") as mc:
            mc.TOP_K_RESULTS = 30
            mc.RERANK_TOP_K = 12
            resp = client.post("/api/settings/rag", json={"TOP_K_RESULTS": 999})
        assert resp.status_code == 400

    def test_settings_stats(self):
        client = self._client()
        with patch("src.routes_fastapi.settings_routes.config") as mc:
            mc.TOP_K_RESULTS = 20
            mc.RERANK_TOP_K = 10
            mc.DIVERSITY_THRESHOLD = 0.70
            mc.SEMANTIC_WEIGHT = 0.70
            mc.CHUNK_SIZE = 1200
            mc.CHUNK_OVERLAP = 200
            mc.APP_VERSION = "1.0.0"
            mc.DEMO_MODE = False
            mc.OLLAMA_BASE_URL = "http://localhost:11434"
            mc.app_state = MagicMock()
            mc.app_state.get_active_model.return_value = "llama3.2"
            with patch("src.monitoring._compute_health_status") as mh:
                mh.return_value = (True, True, {})
                with patch("src.monitoring.get_metrics") as mgm:
                    mgm.return_value = MagicMock()
                    mgm.return_value.get_metrics.return_value = {"uptime_seconds": 0, "counters": {}}
                    resp = client.get("/api/settings/stats")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# API routes — plugins, chat guards
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestApiRoutesExtended:
    def _client(self, state=None):
        from src.routes_fastapi.api_routes import router

        s = state or _base_state()
        return _make_client(router, "/api", s)

    def test_list_plugins(self):
        client = self._client()
        with patch("src.routes_fastapi.api_routes.config") as mc:
            mc.MCP_ENABLED = False
            mc.MODEL_ROUTER_ENABLED = False
            mc.AGGREGATOR_AGENT_ENABLED = False
            mc.GRAPH_RAG_ENABLED = False
            mc.LONG_TERM_MEMORY_ENABLED = False
            mc.WEB_SEARCH_ENABLED = False
            with patch("src.routes_fastapi.api_routes.tool_registry", create=True) as mreg:
                mreg.__len__ = lambda self: 0
                mreg.get_by_source.return_value = []
                with patch("src.routes_fastapi.api_routes.plugin_loader", create=True) as mpl:
                    mpl.list_plugins.return_value = []
                    resp = client.get("/api/plugins")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_chat_empty_body(self):
        client = self._client()
        resp = client.post("/api/chat", content=b"")
        assert resp.status_code == 400

    def test_chat_invalid_json(self):
        client = self._client()
        resp = client.post(
            "/api/chat",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    def test_chat_no_active_model(self):
        client = self._client()
        with patch("src.routes_fastapi.api_routes.config") as mc:
            mc.app_state = MagicMock()
            mc.app_state.get_active_model.return_value = None
            mc.WEB_SEARCH_ENABLED = False
            mc.MCP_ENABLED = False
            mc.AGGREGATOR_AGENT_ENABLED = False
            resp = client.post(
                "/api/chat",
                json={"message": "hello", "use_rag": False, "enhance": False},
            )
        assert resp.status_code == 400
        assert "model" in resp.json()["message"].lower() or "model" in resp.json().get("error", "").lower()

    def test_reload_plugins_disabled(self):
        client = self._client()
        with patch("src.routes_fastapi.api_routes.config") as mc:
            mc.PLUGINS_ENABLED = False
            resp = client.post("/api/plugins/reload")
        assert resp.status_code == 400
