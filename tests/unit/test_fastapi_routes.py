"""
Integration smoke-tests for the FastAPI route layer.

Each test uses httpx.TestClient against a minimal FastAPI app that has
only the tested router mounted — no DB, no Ollama. All external services
are mocked through app.state attributes.

Markers: unit (fast, no external services)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_state() -> MagicMock:
    """Minimal app.state mock used by most routes."""
    state = MagicMock()
    state.testing = True
    state.startup_status = {"database": True, "ollama": True, "ready": True}
    state.db.is_connected = True
    return state


def _make_client(router, prefix: str, state: MagicMock | None = None) -> TestClient:
    """Return a TestClient for a single-router FastAPI app."""
    app = FastAPI()
    app.include_router(router, prefix=prefix)
    app.state = state or _base_state()
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAuthRoutes:
    def _client(self, users=None, created_id="u1"):
        from src.routes_fastapi.auth_routes import router

        state = _base_state()
        state.db.list_users.return_value = users or []
        state.db.create_user.return_value = created_id
        state.db.get_user_by_id.return_value = {
            "id": created_id, "username": "alice", "role": "user", "hashed_password": "x"
        }
        return _make_client(router, "/api", state)

    def test_list_users(self):
        client = self._client(users=[{"id": "u1", "username": "alice", "role": "user", "hashed_password": "x"}])
        resp = client.get("/api/users")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["users"]) == 1
        assert "hashed_password" not in data["users"][0]

    def test_create_user_missing_username(self):
        client = self._client()
        resp = client.post("/api/users", json={"password": "secret"})
        assert resp.status_code == 400

    def test_create_user_success(self):
        client = self._client()
        with patch("src.db.users.hash_user_password", return_value="hashed"):
            resp = client.post("/api/users", json={"username": "alice", "password": "secret"})
        assert resp.status_code == 201

    def test_delete_user_not_found(self):
        from src.routes_fastapi.auth_routes import router

        state = _base_state()
        state.db.delete_user.return_value = False
        client = _make_client(router, "/api", state)
        resp = client.delete("/api/users/missing-id")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Feedback routes
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestFeedbackRoutes:
    def _client(self, feedback_id=42):
        from src.routes_fastapi.feedback_routes import router

        state = _base_state()
        state.db.insert_feedback.return_value = feedback_id
        state.db.get_feedback_stats.return_value = {}
        state.db.get_feedback_trend.return_value = []
        state.db.get_stale_chunks.return_value = []
        return _make_client(router, "/api", state)

    def test_submit_feedback_bad_rating(self):
        client = self._client()
        resp = client.post("/api/feedback", json={"rating": 0})
        assert resp.status_code == 400

    def test_submit_feedback_success(self):
        client = self._client()
        resp = client.post("/api/feedback", json={"rating": 1, "message_id": 7})
        assert resp.status_code == 201
        assert resp.json()["ok"] is True

    def test_feedback_stats(self):
        client = self._client()
        resp = client.get("/api/feedback/stats")
        assert resp.status_code == 200
        assert "stats" in resp.json()


# ---------------------------------------------------------------------------
# Annotation routes
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAnnotationRoutes:
    def _client(self, annotation_id=1):
        from src.routes_fastapi.annotation_routes import router

        state = _base_state()
        state.db.add_annotation.return_value = annotation_id
        state.db.get_annotations_for_chunk.return_value = []
        state.db.delete_annotation.return_value = True
        return _make_client(router, "/api", state)

    def test_create_annotation_missing_chunk_id(self):
        client = self._client()
        resp = client.post("/api/annotations", json={"text": "note"})
        assert resp.status_code == 400

    def test_create_annotation_success(self):
        client = self._client()
        resp = client.post("/api/annotations", json={"chunk_id": 5, "text": "important"})
        assert resp.status_code == 201
        assert resp.json()["success"] is True

    def test_list_chunk_annotations(self):
        client = self._client()
        resp = client.get("/api/chunks/5/annotations")
        assert resp.status_code == 200
        assert resp.json()["annotations"] == []

    def test_delete_annotation_not_found(self):
        from src.routes_fastapi.annotation_routes import router

        state = _base_state()
        state.db.delete_annotation.return_value = False
        client = _make_client(router, "/api", state)
        resp = client.delete("/api/annotations/99")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Memory routes
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestMemoryRoutes:
    def _client(self):
        from src.routes_fastapi.memory_routes import router

        state = _base_state()
        state.db.list_conversations.return_value = []
        state.db.create_conversation.return_value = "conv-1"
        state.db.get_conversation_messages.return_value = []
        state.db.delete_conversation.return_value = True
        state.db.delete_all_conversations.return_value = 2
        state.db.get_conversation_document_filter.return_value = []
        state.db.set_conversation_document_filter.return_value = True
        state.db.update_conversation_title.return_value = True
        return _make_client(router, "/api", state)

    def test_list_conversations(self):
        client = self._client()
        resp = client.get("/api/conversations")
        assert resp.status_code == 200
        assert resp.json()["conversations"] == []

    def test_create_conversation(self):
        client = self._client()
        resp = client.post("/api/conversations", json={"title": "My chat"})
        assert resp.status_code == 201
        assert resp.json()["id"] == "conv-1"

    def test_get_conversation_not_found(self):
        from src.routes_fastapi.memory_routes import router

        state = _base_state()
        state.db.get_conversation_messages.return_value = None
        client = _make_client(router, "/api", state)
        resp = client.get("/api/conversations/missing")
        assert resp.status_code == 404

    def test_delete_conversation(self):
        client = self._client()
        resp = client.delete("/api/conversations/conv-1")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_update_conversation_title_empty(self):
        client = self._client()
        resp = client.patch("/api/conversations/conv-1", json={"title": ""})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Model routes
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestModelRoutes:
    def _client(self):
        from src.routes_fastapi.model_routes import router

        state = _base_state()
        state.ollama_client.list_models.return_value = (True, [{"name": "llama3.2"}])
        state.ollama_client.delete_model.return_value = (True, "deleted")
        state.ollama_client.test_model.return_value = (True, "ok")
        return _make_client(router, "/api/models", state)

    def test_list_models(self):
        client = self._client()
        resp = client.get("/api/models")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_get_active_model(self):
        with patch("src.routes_fastapi.model_routes.config") as mock_cfg:
            mock_cfg.app_state.get_active_model.return_value = "llama3.2"
            client = self._client()
            resp = client.get("/api/models/active")
        assert resp.status_code == 200

    def test_delete_model_success(self):
        import json as _json

        client = self._client()
        # ModelDeleteRequest and sanitize_model_name are imported lazily inside the handler
        with patch("src.models.ModelDeleteRequest") as m, \
             patch("src.utils.sanitization.sanitize_model_name", return_value="llama3.2"):
            m.return_value.model = "llama3.2"
            resp = client.request(
                "DELETE", "/api/models/delete",
                content=_json.dumps({"model": "llama3.2"}),
                headers={"Content-Type": "application/json"},
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ---------------------------------------------------------------------------
# Longterm memory routes
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestLongtermMemoryRoutes:
    def _client(self, db_ok=True, active_model="llama3.2", memories=None):
        from src.routes_fastapi.longterm_memory_routes import router

        state = _base_state()
        state.startup_status["database"] = db_ok
        state.db.get_all_memories.return_value = memories or []
        state.db.delete_all_memories.return_value = 5
        return _make_client(router, "/api/memory", state)

    def test_list_memories(self):
        client = self._client(memories=[{"id": "m1", "content": "fact"}])
        resp = client.get("/api/memory/")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    def test_delete_all_memories(self):
        client = self._client()
        resp = client.delete("/api/memory/")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 5

    def test_extract_db_unavailable(self):
        client = self._client(db_ok=False)
        with patch("src.routes_fastapi.longterm_memory_routes.config") as mc:
            mc.app_state.get_active_model.return_value = "llama3.2"
            resp = client.post("/api/memory/extract", json={})
        assert resp.status_code == 503

    def test_delete_memory(self):
        from src.routes_fastapi.longterm_memory_routes import router

        state = _base_state()
        state.db.delete_memory.return_value = None
        client = _make_client(router, "/api/memory", state)
        resp = client.delete("/api/memory/mem-id-1")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# API routes (status endpoint — no Ollama needed)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestApiStatusRoute:
    def test_status_returns_dict(self):
        from src.routes_fastapi.api_routes import router

        state = _base_state()
        state.db.get_document_count.return_value = 3
        state.ollama_client.check_connection.return_value = (True, None)

        with patch("src.routes_fastapi.api_routes.config") as mc:
            mc.app_state.get_active_model.return_value = "llama3.2"
            mc.MODEL_ROUTER_ENABLED = False
            mc.AGGREGATOR_AGENT_ENABLED = False
            mc.MCP_ENABLED = False
            mc.GRAPH_RAG_ENABLED = False
            mc.LONG_TERM_MEMORY_ENABLED = False
            client = _make_client(router, "/api", state)
            resp = client.get("/api/status")

        assert resp.status_code == 200
        body = resp.json()
        assert "ollama" in body
        assert "database" in body
