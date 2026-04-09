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

import json
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helper — build a real Flask test app with the blueprint
# ---------------------------------------------------------------------------

def _make_app(
    active_model="llama3.2",
    db_ok=True,
    memories=None,
    unextracted=None,
    delete_count=3,
):
    from flask import Flask

    from src.routes.longterm_memory_routes import bp

    flask_app = Flask(__name__)
    flask_app.register_blueprint(bp, url_prefix="/api/memory")
    flask_app.config["TESTING"] = True

    mock_db = MagicMock()
    mock_db.get_all_memories.return_value = memories or []
    mock_db.get_unextracted_conversations.return_value = unextracted or []
    mock_db.get_conversation_messages.return_value = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    mock_db.delete_all_memories.return_value = delete_count

    flask_app.db = mock_db
    flask_app.startup_status = {"database": db_ok}
    flask_app.ollama_client = MagicMock()

    with patch("src.routes.longterm_memory_routes.config") as mock_cfg:
        mock_cfg.app_state.get_active_model.return_value = active_model
        flask_app._mock_cfg = mock_cfg

    return flask_app


# ===========================================================================
# GET /api/memory/
# ===========================================================================

class TestListMemories:
    def test_returns_200_with_memories_key(self):
        app = _make_app(memories=[{"id": "m1", "content": "fact"}])
        with app.test_client() as c:
            resp = c.get("/api/memory/")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "memories" in data
        assert data["count"] == 1

    def test_empty_memories_returns_empty_list(self):
        app = _make_app(memories=[])
        with app.test_client() as c:
            resp = c.get("/api/memory/")
        data = resp.get_json()
        assert data["memories"] == []

    def test_pagination_params_forwarded(self):
        app = _make_app()
        with app.test_client() as c:
            c.get("/api/memory/?limit=10&offset=20")
        app.db.get_all_memories.assert_called_once_with(limit=10, offset=20)

    def test_limit_capped_at_500(self):
        app = _make_app()
        with app.test_client() as c:
            c.get("/api/memory/?limit=9999")
        call_args = app.db.get_all_memories.call_args
        assert call_args.kwargs.get("limit", call_args.args[0] if call_args.args else 0) <= 500

    def test_db_exception_returns_500(self):
        app = _make_app()
        app.db.get_all_memories.side_effect = Exception("DB down")
        with app.test_client() as c:
            resp = c.get("/api/memory/")
        assert resp.status_code == 500


# ===========================================================================
# POST /api/memory/extract
# ===========================================================================

class TestExtractMemories:
    def _post_extract(self, app, body=None):
        with app.test_client() as c:
            with patch("src.routes.longterm_memory_routes.config") as cfg:
                cfg.app_state.get_active_model.return_value = app._mock_cfg.app_state.get_active_model.return_value
                resp = c.post(
                    "/api/memory/extract",
                    data=json.dumps(body or {}),
                    content_type="application/json",
                )
        return resp

    def test_db_unavailable_returns_503(self):
        app = _make_app(db_ok=False)
        resp = self._post_extract(app)
        assert resp.status_code == 503

    def test_no_active_model_returns_400(self):
        app = _make_app(active_model=None)
        resp = self._post_extract(app)
        assert resp.status_code == 400

    def test_success_with_no_unextracted_conversations(self):
        app = _make_app(unextracted=[])
        resp = self._post_extract(app)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["conversations_processed"] == 0
        assert data["new_memories"] == 0

    def test_processes_conversations_and_returns_count(self):
        app = _make_app(unextracted=[{"id": "conv-1", "title": "T", "updated_at": None}])

        # Mock MemoryExtractor.extract to return 2 new memories
        with patch("src.memory.extractor.MemoryExtractor") as MockExtractor:
            instance = MockExtractor.return_value
            instance.extract.return_value = 2
            resp = self._post_extract(app)

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["conversations_processed"] == 1
        assert data["new_memories"] == 2

    def test_extraction_failure_per_conv_is_silenced(self):
        app = _make_app(unextracted=[
            {"id": "conv-1", "title": "T1", "updated_at": None},
            {"id": "conv-2", "title": "T2", "updated_at": None},
        ])

        with patch("src.memory.extractor.MemoryExtractor") as MockExtractor:
            instance = MockExtractor.return_value
            # First conv raises, second succeeds
            instance.extract.side_effect = [Exception("NLP error"), 1]
            resp = self._post_extract(app)

        # Should not 500 — the per-conv exception is caught
        assert resp.status_code == 200
        data = resp.get_json()
        # Only the second conversation counted
        assert data["conversations_processed"] == 1

    def test_custom_limit_forwarded(self):
        app = _make_app(unextracted=[])
        self._post_extract(app, body={"limit": 5})
        app.db.get_unextracted_conversations.assert_called_once_with(limit=5)

    def test_limit_capped_at_50(self):
        app = _make_app(unextracted=[])
        self._post_extract(app, body={"limit": 999})
        call_args = app.db.get_unextracted_conversations.call_args
        assert call_args.kwargs.get("limit", call_args.args[0] if call_args.args else 0) <= 50

    def test_normalises_tuple_messages(self):
        """get_conversation_messages returning tuples must be handled."""
        app = _make_app(unextracted=[{"id": "conv-1", "title": "T", "updated_at": None}])
        app.db.get_conversation_messages.return_value = [
            ("user", "hello"), ("assistant", "world")
        ]

        with patch("src.memory.extractor.MemoryExtractor") as MockExtractor:
            instance = MockExtractor.return_value
            instance.extract.return_value = 0
            # Check that extract was called with normalized dicts
            resp = self._post_extract(app)
            call_args = instance.extract.call_args
            msg_list = call_args.kwargs.get("messages") or call_args.args[1]
            assert all(isinstance(m, dict) for m in msg_list)

    def test_outer_exception_returns_500(self):
        app = _make_app(unextracted=[])
        app.db.get_unextracted_conversations.side_effect = Exception("DB crash")
        resp = self._post_extract(app)
        assert resp.status_code == 500


# ===========================================================================
# DELETE /api/memory/<id>
# ===========================================================================

class TestDeleteMemory:
    def test_returns_200_on_success(self):
        app = _make_app()
        with app.test_client() as c:
            resp = c.delete("/api/memory/some-uuid")
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_calls_db_delete_with_id(self):
        app = _make_app()
        with app.test_client() as c:
            c.delete("/api/memory/abc-123")
        app.db.delete_memory.assert_called_once_with("abc-123")

    def test_db_raises_returns_500(self):
        app = _make_app()
        app.db.delete_memory.side_effect = Exception("not found")
        with app.test_client() as c:
            resp = c.delete("/api/memory/bad-id")
        assert resp.status_code == 500


# ===========================================================================
# DELETE /api/memory/
# ===========================================================================

class TestDeleteAllMemories:
    def test_returns_200_with_deleted_count(self):
        app = _make_app(delete_count=5)
        with app.test_client() as c:
            resp = c.delete("/api/memory/")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["deleted"] == 5

    def test_db_raises_returns_500(self):
        app = _make_app()
        app.db.delete_all_memories.side_effect = Exception("crash")
        with app.test_client() as c:
            resp = c.delete("/api/memory/")
        assert resp.status_code == 500
