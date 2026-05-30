"""
Tests for src/routes/longterm_memory_routes.py

Covers:
  - GET  /api/memory/          list_memories: success, pagination, DB error
  - POST /api/memory/extract   extract_memories: DB unavailable, no active model,
                               success (conversations processed), extraction failure
                               per-conversation is silenced, empty conversation list
  - DELETE /api/memory/<id>    delete_memory: success, DB raises
  - DELETE /api/memory/        delete_all_memories: success with count, DB raises
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helper — build a minimal FastAPI test app with the router
# ---------------------------------------------------------------------------

def _make_app(
    active_model="llama3.2",
    db_ok=True,
    memories=None,
    unextracted=None,
    delete_count=3,
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.routes_fastapi.longterm_memory_routes import router

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api/memory")

    mock_db = MagicMock()
    mock_db.get_all_memories.return_value = memories or []
    mock_db.get_unextracted_conversations.return_value = unextracted or []
    mock_db.get_conversation_messages.return_value = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    mock_db.delete_all_memories.return_value = delete_count

    test_app.state.db = mock_db
    test_app.state.startup_status = {"database": db_ok}
    test_app.state.ollama_client = MagicMock()
    test_app._active_model = active_model

    client = TestClient(test_app, raise_server_exceptions=False)
    return test_app, client


# ===========================================================================
# GET /api/memory/
# ===========================================================================

class TestListMemories:
    def test_returns_200_with_memories_key(self):
        app, client = _make_app(memories=[{"id": "m1", "content": "fact"}])
        resp = client.get("/api/memory/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "memories" in data
        assert data["count"] == 1

    def test_empty_memories_returns_empty_list(self):
        _, client = _make_app(memories=[])
        resp = client.get("/api/memory/")
        data = resp.json()
        assert data["memories"] == []

    def test_pagination_params_forwarded(self):
        app, client = _make_app()
        client.get("/api/memory/?limit=10&offset=20")
        app.state.db.get_all_memories.assert_called_once_with(limit=10, offset=20)

    def test_limit_capped_at_500(self):
        app, client = _make_app()
        client.get("/api/memory/?limit=9999")
        call_args = app.state.db.get_all_memories.call_args
        assert call_args.kwargs.get("limit", call_args.args[0] if call_args.args else 0) <= 500

    def test_db_exception_returns_500(self):
        app, client = _make_app()
        app.state.db.get_all_memories.side_effect = Exception("DB down")
        resp = client.get("/api/memory/")
        assert resp.status_code == 500


# ===========================================================================
# POST /api/memory/extract
# ===========================================================================

class TestExtractMemories:
    def _post_extract(self, client, active_model="llama3.2", body=None):
        with patch("src.routes_fastapi.longterm_memory_routes.config") as cfg:
            cfg.app_state.get_active_model.return_value = active_model
            resp = client.post("/api/memory/extract", json=body or {})
        return resp

    def test_db_unavailable_returns_503(self):
        _, client = _make_app(db_ok=False)
        resp = self._post_extract(client)
        assert resp.status_code == 503

    def test_no_active_model_returns_400(self):
        _, client = _make_app(active_model=None)
        resp = self._post_extract(client, active_model=None)
        assert resp.status_code == 400

    def test_success_with_no_unextracted_conversations(self):
        _, client = _make_app(unextracted=[])
        resp = self._post_extract(client)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["conversations_processed"] == 0
        assert data["new_memories"] == 0

    def test_processes_conversations_and_returns_count(self):
        _, client = _make_app(unextracted=[{"id": "conv-1", "title": "T", "updated_at": None}])

        with patch("src.memory.extractor.MemoryExtractor") as MockExtractor:
            instance = MockExtractor.return_value
            instance.extract.return_value = 2
            resp = self._post_extract(client)

        assert resp.status_code == 200
        data = resp.json()
        assert data["conversations_processed"] == 1
        assert data["new_memories"] == 2

    def test_extraction_failure_per_conv_is_silenced(self):
        _, client = _make_app(unextracted=[
            {"id": "conv-1", "title": "T1", "updated_at": None},
            {"id": "conv-2", "title": "T2", "updated_at": None},
        ])

        with patch("src.memory.extractor.MemoryExtractor") as MockExtractor:
            instance = MockExtractor.return_value
            instance.extract.side_effect = [Exception("NLP error"), 1]
            resp = self._post_extract(client)

        assert resp.status_code == 200
        data = resp.json()
        assert data["conversations_processed"] == 1

    def test_custom_limit_forwarded(self):
        app, client = _make_app(unextracted=[])
        self._post_extract(client, body={"limit": 5})
        app.state.db.get_unextracted_conversations.assert_called_once_with(limit=5)

    def test_limit_capped_at_50(self):
        app, client = _make_app(unextracted=[])
        self._post_extract(client, body={"limit": 999})
        call_args = app.state.db.get_unextracted_conversations.call_args
        assert call_args.kwargs.get("limit", call_args.args[0] if call_args.args else 0) <= 50

    def test_normalises_tuple_messages(self):
        """get_conversation_messages returning tuples must be handled."""
        app, client = _make_app(unextracted=[{"id": "conv-1", "title": "T", "updated_at": None}])
        app.state.db.get_conversation_messages.return_value = [
            ("user", "hello"), ("assistant", "world")
        ]

        with patch("src.memory.extractor.MemoryExtractor") as MockExtractor:
            instance = MockExtractor.return_value
            instance.extract.return_value = 0
            self._post_extract(client)
            call_args = instance.extract.call_args
            msg_list = call_args.kwargs.get("messages") or call_args.args[1]
            assert all(isinstance(m, dict) for m in msg_list)

    def test_outer_exception_returns_500(self):
        app, client = _make_app(unextracted=[])
        app.state.db.get_unextracted_conversations.side_effect = Exception("DB crash")
        resp = self._post_extract(client)
        assert resp.status_code == 500


# ===========================================================================
# DELETE /api/memory/<id>
# ===========================================================================

class TestDeleteMemory:
    def test_returns_200_on_success(self):
        _, client = _make_app()
        resp = client.delete("/api/memory/some-uuid")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_calls_db_delete_with_id(self):
        app, client = _make_app()
        client.delete("/api/memory/abc-123")
        app.state.db.delete_memory.assert_called_once_with("abc-123")

    def test_db_raises_returns_500(self):
        app, client = _make_app()
        app.state.db.delete_memory.side_effect = Exception("not found")
        resp = client.delete("/api/memory/bad-id")
        assert resp.status_code == 500


# ===========================================================================
# DELETE /api/memory/
# ===========================================================================

class TestDeleteAllMemories:
    def test_returns_200_with_deleted_count(self):
        _, client = _make_app(delete_count=5)
        resp = client.delete("/api/memory/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["deleted"] == 5

    def test_db_raises_returns_500(self):
        app, client = _make_app()
        app.state.db.delete_all_memories.side_effect = Exception("crash")
        resp = client.delete("/api/memory/")
        assert resp.status_code == 500
