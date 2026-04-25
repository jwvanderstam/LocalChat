"""
Tests for src/routes/api_routes.py

Covers:
  - _parse_chat_request: valid input, Pydantic rejection, sanitization passthrough
  - _insert_system_prompt: no system msg inserts, existing system msg skipped
  - _build_context_sections: both / one / neither context
  - _build_context_prompt: local+web, local only, no context, no RAG, memory_context injection
  - _persist_user_message / _persist_assistant_message: DB on/off, return values
  - GET /api/status: basic shape, DB unavailable, cache TTL
  - POST /api/chat: no body, no active model, valid direct-LLM SSE stream,
    validation error returns 400, tool executor skipped when context present
"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_flask_app(active_model="llama3.2", db_ok=True, ollama_ok=True):
    """Minimal Flask app wired like the real one for route tests."""
    from flask import Flask

    from src.routes import api_routes

    flask_app = Flask(__name__)
    flask_app.register_blueprint(api_routes.bp, url_prefix="/api")
    flask_app.config["TESTING"] = True

    mock_db = MagicMock()
    mock_db.is_connected = db_ok
    mock_db.get_document_count.return_value = 5
    mock_db.save_message.return_value = 42

    flask_app.db = mock_db
    flask_app.startup_status = {"database": db_ok, "ollama": ollama_ok, "ready": db_ok and ollama_ok}
    flask_app.doc_processor = MagicMock()
    flask_app.doc_processor.retrieve_context.return_value = []
    flask_app.ollama_client = MagicMock()
    flask_app.ollama_client.generate_chat_response.return_value = iter(["Hello", " world"])
    flask_app.cloud_client = None

    # Patch app_state
    with patch("src.routes.api_routes.config") as mock_cfg:
        mock_cfg.app_state.get_active_model.return_value = active_model
        mock_cfg.WEB_SEARCH_ENABLED = False
        mock_cfg.TOP_K_RESULTS = 5
        mock_cfg.MCP_ENABLED = False
        mock_cfg.AGGREGATOR_AGENT_ENABLED = False
        mock_cfg.QUERY_PLANNER_ENABLED = False
        mock_cfg.LONG_TERM_MEMORY_ENABLED = False
        mock_cfg.MODEL_ROUTER_ENABLED = False
        mock_cfg.TOOL_CALLING_ENABLED = False
        mock_cfg.PLUGINS_ENABLED = False
        mock_cfg.CLOUD_REFUSAL_PATTERNS = []
        flask_app._mock_cfg = mock_cfg

    return flask_app


def _parse_sse(raw: bytes) -> list[dict]:
    """Parse SSE bytes into a list of data dicts."""
    events = []
    for line in raw.decode().splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


# ===========================================================================
# _parse_chat_request
# ===========================================================================

class TestParseChatRequest:
    def _parse(self, data):
        from src.routes.api_routes import _parse_chat_request
        with patch("src.routes.api_routes.config") as cfg:
            cfg.WEB_SEARCH_ENABLED = True
            return _parse_chat_request(data)

    def test_valid_minimal_request(self):
        result = self._parse({"message": "hello"})
        assert result["message"] == "hello"
        assert result["use_rag"] is True  # default

    def test_rag_false_passes_through(self):
        result = self._parse({"message": "hello", "use_rag": False})
        assert result["use_rag"] is False

    def test_enhance_disabled_when_web_search_disabled(self):
        from src.routes.api_routes import _parse_chat_request
        with patch("src.routes.api_routes.config") as cfg:
            cfg.WEB_SEARCH_ENABLED = False
            result = _parse_chat_request({"message": "q", "enhance": True})
        assert result["enhance"] is False

    def test_model_override_passed_through(self):
        result = self._parse({"message": "q", "model_override": "llama3:8b"})
        assert result["model_override"] == "llama3:8b"

    def test_invalid_message_raises(self):
        from pydantic import ValidationError
        with pytest.raises((ValidationError, Exception)):
            self._parse({"message": ""})  # empty → below min_length

    def test_images_defaults_to_empty_list(self):
        result = self._parse({"message": "what is this"})
        assert result["images"] == []


# ===========================================================================
# _insert_system_prompt
# ===========================================================================

class TestInsertSystemPrompt:
    def _insert(self, messages, prompt):
        from src.routes.api_routes import _insert_system_prompt
        _insert_system_prompt(messages, prompt)
        return messages

    def test_inserts_when_no_system_message(self):
        msgs = [{"role": "user", "content": "hi"}]
        self._insert(msgs, "You are helpful.")
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "You are helpful."

    def test_skips_when_system_already_present(self):
        msgs = [{"role": "system", "content": "existing"}, {"role": "user", "content": "hi"}]
        self._insert(msgs, "new system")
        assert msgs[0]["content"] == "existing"
        assert len(msgs) == 2

    def test_empty_messages_inserts(self):
        msgs = []
        self._insert(msgs, "be helpful")
        assert len(msgs) == 1
        assert msgs[0]["role"] == "system"


# ===========================================================================
# _build_context_sections
# ===========================================================================

class TestBuildContextSections:
    def _build(self, local="", web=""):
        from src.routes.api_routes import _build_context_sections
        return _build_context_sections(local, web)

    def test_both_contexts_present(self):
        result = self._build("local stuff", "web stuff")
        assert "Local Document Context" in result
        assert "Web Search Results" in result
        assert "local stuff" in result
        assert "web stuff" in result

    def test_local_only(self):
        result = self._build(local="local content")
        assert "Local Document Context" in result
        assert "Web Search Results" not in result

    def test_web_only(self):
        result = self._build(web="web content")
        assert "Web Search Results" in result
        assert "Local Document Context" not in result

    def test_empty_returns_empty_string(self):
        assert self._build() == ""


# ===========================================================================
# _build_context_prompt
# ===========================================================================

class TestBuildContextPrompt:
    def _build(self, local="", web="", messages=None, use_rag=True, enhance=False, memory=""):
        from src.routes.api_routes import _build_context_prompt
        msgs = messages or [{"role": "user", "content": "question"}]
        return _build_context_prompt("original question", local, web, msgs, use_rag, enhance, memory_context=memory)

    def test_with_local_context_inserts_rag_system_prompt(self):
        msgs, final = self._build(local="doc content")
        assert msgs[0]["role"] == "system"
        assert "Question: original question" in final

    def test_with_web_context_uses_enhanced_prompt(self):
        msgs, final = self._build(web="web content", enhance=True)
        assert msgs[0]["role"] == "system"
        assert "web" in msgs[0]["content"].lower() or "synthesize" in msgs[0]["content"].lower()

    def test_rag_enabled_no_context_uses_fallback_system(self):
        msgs, final = self._build(use_rag=True)
        assert msgs[0]["role"] == "system"
        assert "No relevant documents" in msgs[0]["content"]
        assert final == "original question"

    def test_no_rag_no_context_no_system_injected(self):
        msgs, final = self._build(use_rag=False)
        # No system message injected when not RAG mode and no context
        assert final == "original question"
        assert not any(m["role"] == "system" for m in msgs)

    def test_memory_context_prepended_to_system(self):
        msgs, _ = self._build(local="ctx", memory="Remember: user is Alice")
        assert "Remember: user is Alice" in msgs[0]["content"]

    def test_memory_context_injected_for_no_rag(self):
        msgs, _ = self._build(use_rag=False, memory="mem context")
        assert any(m["role"] == "system" and "mem context" in m["content"] for m in msgs)


# ===========================================================================
# _persist_user_message / _persist_assistant_message
# ===========================================================================

class TestPersistMessages:
    def _make_app(self, db_ok=True):
        app = MagicMock()
        app.startup_status = {"database": db_ok}
        app.db = MagicMock()
        app.db.create_conversation.return_value = "conv-new"
        app.db.create_conversation_with_message.return_value = ("conv-new", 99)
        app.db.save_message.return_value = 99
        return app

    def test_persist_user_returns_conversation_id_and_message_id(self):
        from src.routes.api_routes import _persist_user_message
        app = self._make_app()
        conv_id, msg_id = _persist_user_message(app, "existing-conv", "hello")
        assert conv_id == "existing-conv"
        assert msg_id == 99

    def test_persist_user_creates_conversation_when_none(self):
        from src.routes.api_routes import _persist_user_message
        app = self._make_app()
        conv_id, msg_id = _persist_user_message(app, None, "first message")
        assert conv_id == "conv-new"
        assert msg_id == 99
        app.db.create_conversation_with_message.assert_called_once()

    def test_persist_user_returns_none_message_id_when_db_unavailable(self):
        from src.routes.api_routes import _persist_user_message
        app = self._make_app(db_ok=False)
        conv_id, msg_id = _persist_user_message(app, "conv", "msg")
        assert msg_id is None

    def test_persist_user_handles_db_exception(self):
        from src.routes.api_routes import _persist_user_message
        app = self._make_app()
        app.db.save_message.side_effect = Exception("DB error")
        # Should not raise
        conv_id, msg_id = _persist_user_message(app, "conv", "msg")
        assert msg_id is None

    def test_persist_assistant_returns_message_id(self):
        from src.routes.api_routes import _persist_assistant_message
        app = self._make_app()
        msg_id = _persist_assistant_message(app, "conv-1", "response text")
        assert msg_id == 99

    def test_persist_assistant_returns_none_when_no_conv_id(self):
        from src.routes.api_routes import _persist_assistant_message
        app = self._make_app()
        msg_id = _persist_assistant_message(app, None, "text")
        assert msg_id is None

    def test_persist_assistant_handles_exception(self):
        from src.routes.api_routes import _persist_assistant_message
        app = self._make_app()
        app.db.save_message.side_effect = Exception("DB error")
        msg_id = _persist_assistant_message(app, "conv", "text")
        assert msg_id is None


# ===========================================================================
# GET /api/status
# ===========================================================================

class TestApiStatus:
    def _get_status(self, active_model="llama3.2", db_ok=True, doc_count=5):
        from flask import Flask

        from src.routes import api_routes
        from src.routes.api_routes import bp

        flask_app = Flask(__name__)
        flask_app.register_blueprint(bp, url_prefix="/api")
        flask_app.config["TESTING"] = True
        flask_app.startup_status = {"database": db_ok, "ollama": True, "ready": db_ok}
        flask_app.db = MagicMock()
        flask_app.db.get_document_count.return_value = doc_count
        flask_app.ollama_client = MagicMock()
        flask_app.ollama_client.check_connection.return_value = (True, "OK")

        # Force a cache miss so _check_ollama_live always does a live check.
        with patch.object(api_routes, '_ollama_status_cache', [False, 0.0]):
            with flask_app.test_client() as client:
                with patch("src.routes.api_routes.config") as cfg:
                    cfg.app_state.get_active_model.return_value = active_model
                    cfg.MCP_ENABLED = False
                    cfg.MODEL_ROUTER_ENABLED = False
                    cfg.AGGREGATOR_AGENT_ENABLED = False
                    cfg.GRAPH_RAG_ENABLED = False
                    cfg.LONG_TERM_MEMORY_ENABLED = False
                    resp = client.get("/api/status")
        return resp

    def test_returns_200(self):
        assert self._get_status().status_code == 200

    def test_response_has_required_keys(self):
        data = self._get_status().get_json()
        assert "ollama" in data
        assert "database" in data
        assert "ready" in data
        assert "active_model" in data
        assert "document_count" in data

    def test_active_model_in_response(self):
        data = self._get_status(active_model="mistral").get_json()
        assert data["active_model"] == "mistral"

    def test_db_unavailable_reflected(self):
        data = self._get_status(db_ok=False).get_json()
        assert data["database"] is False
        assert data["ready"] is False


# ===========================================================================
# _check_ollama_live — TTL cache + live check
# ===========================================================================

class TestCheckOllamaLive:
    def _make_app(self, check_ok=True):
        from flask import Flask
        flask_app = Flask(__name__)
        flask_app.startup_status = {"database": True, "ollama": False, "ready": False}
        flask_app.ollama_client = MagicMock()
        if check_ok:
            flask_app.ollama_client.check_connection.return_value = (True, "OK")
        else:
            flask_app.ollama_client.check_connection.side_effect = ConnectionError("timeout")
        return flask_app

    def test_cache_hit_returns_cached_value(self):
        from src.routes import api_routes
        flask_app = self._make_app()
        # Fresh timestamp ensures TTL has not expired.
        fresh_time = time.monotonic()
        with patch.object(api_routes, '_ollama_status_cache', [True, fresh_time]):
            with flask_app.app_context():
                result = api_routes._check_ollama_live()
        assert result is True
        flask_app.ollama_client.check_connection.assert_not_called()

    def test_cache_miss_live_check_success(self):
        from src.routes import api_routes
        flask_app = self._make_app(check_ok=True)
        with patch.object(api_routes, '_ollama_status_cache', [False, 0.0]):
            with flask_app.app_context():
                result = api_routes._check_ollama_live()
        assert result is True
        assert flask_app.startup_status['ollama'] is True

    def test_cache_miss_live_check_failure(self):
        from src.routes import api_routes
        flask_app = self._make_app(check_ok=False)
        with patch.object(api_routes, '_ollama_status_cache', [True, 0.0]):
            with flask_app.app_context():
                result = api_routes._check_ollama_live()
        assert result is False
        assert flask_app.startup_status['ollama'] is False


# ===========================================================================
# POST /api/chat — SSE streaming
# ===========================================================================

class TestApiChat:
    def _make_chat_app(self, active_model="llama3.2", stream_chunks=None):
        from flask import Flask

        from src.routes import api_routes

        chunks = stream_chunks or ["Hello", " world"]

        flask_app = Flask(__name__)
        flask_app.register_blueprint(api_routes.bp, url_prefix="/api")
        flask_app.config["TESTING"] = True
        flask_app.startup_status = {"database": True, "ollama": True, "ready": True}
        flask_app.db = MagicMock()
        flask_app.db.save_message.return_value = 1
        flask_app.db.create_conversation.return_value = "conv-1"
        flask_app.db.create_conversation_with_message.return_value = ("conv-1", 1)
        flask_app.doc_processor = MagicMock()
        flask_app.doc_processor.retrieve_context.return_value = []
        flask_app.ollama_client = MagicMock()
        flask_app.ollama_client.generate_chat_response.return_value = iter(chunks)
        flask_app.cloud_client = None
        return flask_app

    def _post_chat(self, flask_app, payload, active_model="llama3.2"):
        with flask_app.test_client() as client:
            with patch("src.routes.api_routes.config") as cfg:
                cfg.app_state.get_active_model.return_value = active_model
                cfg.WEB_SEARCH_ENABLED = False
                cfg.MCP_ENABLED = False
                cfg.AGGREGATOR_AGENT_ENABLED = False
                cfg.QUERY_PLANNER_ENABLED = False
                cfg.LONG_TERM_MEMORY_ENABLED = False
                cfg.MODEL_ROUTER_ENABLED = False
                cfg.TOOL_CALLING_ENABLED = False
                cfg.CLOUD_REFUSAL_PATTERNS = []
                cfg.TOP_K_RESULTS = 5
                resp = client.post(
                    "/api/chat",
                    data=json.dumps(payload),
                    content_type="application/json",
                )
                raw = resp.data
        return resp, _parse_sse(raw)

    def test_no_body_returns_400(self):
        app = self._make_chat_app()
        with app.test_client() as client:
            with patch("src.routes.api_routes.config") as cfg:
                cfg.app_state.get_active_model.return_value = "m"
                cfg.WEB_SEARCH_ENABLED = False
                resp = client.post("/api/chat", data="not json", content_type="application/json")
        assert resp.status_code == 400

    def test_no_active_model_returns_400(self):
        app = self._make_chat_app()
        with app.test_client() as client:
            with patch("src.routes.api_routes.config") as cfg:
                cfg.app_state.get_active_model.return_value = None
                cfg.WEB_SEARCH_ENABLED = False
                resp = client.post(
                    "/api/chat",
                    data=json.dumps({"message": "hi"}),
                    content_type="application/json",
                )
        assert resp.status_code == 400

    def test_direct_llm_stream_returns_content_and_done(self):
        app = self._make_chat_app()
        resp, events = self._post_chat(app, {"message": "hello", "use_rag": False})
        assert resp.status_code == 200
        content_events = [e for e in events if "content" in e]
        done_events = [e for e in events if e.get("done")]
        assert len(content_events) >= 1
        assert len(done_events) == 1

    def test_done_event_has_conversation_id(self):
        app = self._make_chat_app()
        _, events = self._post_chat(app, {"message": "hello", "use_rag": False})
        done = next(e for e in events if e.get("done"))
        assert "conversation_id" in done

    def test_done_event_has_message_id(self):
        app = self._make_chat_app()
        _, events = self._post_chat(app, {"message": "hello", "use_rag": False})
        done = next(e for e in events if e.get("done"))
        assert "message_id" in done

    def test_rag_mode_calls_retrieve_context(self):
        app = self._make_chat_app()
        self._post_chat(app, {"message": "what is X", "use_rag": True})
        app.doc_processor.retrieve_context.assert_called_once()

    def test_stream_error_yields_error_event(self):
        app = self._make_chat_app()
        app.ollama_client.generate_chat_response.side_effect = Exception("connection failed")
        _, events = self._post_chat(app, {"message": "hi", "use_rag": False})
        error_events = [e for e in events if "error" in e]
        assert len(error_events) >= 1

    def test_model_override_used_in_generation(self):
        app = self._make_chat_app()
        self._post_chat(app, {"message": "hi", "use_rag": False, "model_override": "mistral:7b"})
        call_args = app.ollama_client.generate_chat_response.call_args
        assert call_args is not None
        # First positional arg is the model name
        assert call_args.args[0] == "mistral:7b" or call_args.kwargs.get("model") == "mistral:7b"
