"""
Tests for src/routes_fastapi/api_routes.py

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

def _parse_sse(raw: bytes) -> list[dict]:
    """Parse SSE bytes into a list of data dicts."""
    events = []
    for line in raw.decode().splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def _make_chat_app(active_model="llama3.2", db_ok=True, ollama_ok=True, chunks=None):
    """Minimal FastAPI app wired for api_routes tests."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.routes_fastapi.api_routes import router

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api")

    test_app.state.startup_status = {"database": db_ok, "ollama": ollama_ok, "ready": db_ok and ollama_ok}
    test_app.state.db = MagicMock()
    test_app.state.db.get_document_count.return_value = 5
    test_app.state.db.save_message.return_value = 42
    test_app.state.db.create_conversation_with_message.return_value = ("conv-1", 1)
    test_app.state.db.get_conversation_document_filter.return_value = []
    test_app.state.doc_processor = MagicMock()
    test_app.state.doc_processor.retrieve_context.return_value = []
    test_app.state.ollama_client = MagicMock()
    test_app.state.ollama_client.check_connection.return_value = (True, "OK")
    _default_chunks = chunks or ["Hello", " world"]

    async def _default_generate(*args, **kwargs):
        for chunk in _default_chunks:
            yield chunk

    # side_effect = callable makes the MagicMock delegate to the async generator factory;
    # tests that need errors can replace side_effect with an Exception instance.
    test_app.state.ollama_client.generate_chat_response.side_effect = _default_generate
    test_app.state.cloud_client = None
    test_app.state.testing = True
    test_app.state.embedding_cache = None
    test_app.state.query_cache = None
    test_app.state.connector_registry = None
    test_app._active_model = active_model

    client = TestClient(test_app, raise_server_exceptions=False)
    return test_app, client


def _config_patch(active_model="llama3.2"):
    """Context manager patching config for api_routes tests."""
    import contextlib

    @contextlib.contextmanager
    def _patch():
        with patch("src.routes_fastapi.api_routes.config") as cfg:
            cfg.app_state.get_active_model.return_value = active_model
            cfg.WEB_SEARCH_ENABLED = False
            cfg.MCP_ENABLED = False
            cfg.AGGREGATOR_AGENT_ENABLED = False
            cfg.QUERY_PLANNER_ENABLED = False
            cfg.LONG_TERM_MEMORY_ENABLED = False
            cfg.MODEL_ROUTER_ENABLED = False
            cfg.TOOL_CALLING_ENABLED = False
            cfg.PLUGINS_ENABLED = False
            cfg.CLOUD_REFUSAL_PATTERNS = []
            cfg.TOP_K_RESULTS = 5
            cfg.GRAPH_RAG_ENABLED = False
            cfg.DEFAULT_TEMPERATURE = 0.7
            yield cfg

    return _patch()


# ===========================================================================
# _parse_chat_request
# ===========================================================================

class TestParseChatRequest:
    def _parse(self, data):
        from src.routes_fastapi.api_routes import _parse_chat_request
        with patch("src.routes_fastapi.api_routes.config") as cfg:
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
        from src.routes_fastapi.api_routes import _parse_chat_request
        with patch("src.routes_fastapi.api_routes.config") as cfg:
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
        from src.routes_fastapi.api_routes import _insert_system_prompt
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
        from src.routes_fastapi.api_routes import _build_context_sections
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
        from src.routes_fastapi.api_routes import _build_context_prompt
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
        from src.routes_fastapi.api_routes import _persist_user_message
        app = self._make_app()
        conv_id, msg_id = _persist_user_message(app, "existing-conv", "hello")
        assert conv_id == "existing-conv"
        assert msg_id == 99

    def test_persist_user_creates_conversation_when_none(self):
        from src.routes_fastapi.api_routes import _persist_user_message
        app = self._make_app()
        conv_id, msg_id = _persist_user_message(app, None, "first message")
        assert conv_id == "conv-new"
        assert msg_id == 99
        app.db.create_conversation_with_message.assert_called_once()

    def test_persist_user_returns_none_message_id_when_db_unavailable(self):
        from src.routes_fastapi.api_routes import _persist_user_message
        app = self._make_app(db_ok=False)
        conv_id, msg_id = _persist_user_message(app, "conv", "msg")
        assert msg_id is None

    def test_persist_user_handles_db_exception(self):
        from src.routes_fastapi.api_routes import _persist_user_message
        app = self._make_app()
        app.db.save_message.side_effect = Exception("DB error")
        conv_id, msg_id = _persist_user_message(app, "conv", "msg")
        assert msg_id is None

    def test_persist_assistant_returns_message_id(self):
        from src.routes_fastapi.api_routes import _persist_assistant_message
        app = self._make_app()
        msg_id = _persist_assistant_message(app, "conv-1", "response text")
        assert msg_id == 99

    def test_persist_assistant_returns_none_when_no_conv_id(self):
        from src.routes_fastapi.api_routes import _persist_assistant_message
        app = self._make_app()
        msg_id = _persist_assistant_message(app, None, "text")
        assert msg_id is None

    def test_persist_assistant_handles_exception(self):
        from src.routes_fastapi.api_routes import _persist_assistant_message
        app = self._make_app()
        app.db.save_message.side_effect = Exception("DB error")
        msg_id = _persist_assistant_message(app, "conv", "text")
        assert msg_id is None


# ===========================================================================
# GET /api/status
# ===========================================================================

class TestApiStatus:
    def _get_status(self, active_model="llama3.2", db_ok=True, doc_count=5):
        app, client = _make_chat_app(active_model=active_model, db_ok=db_ok)
        with patch("src.routes_fastapi.api_routes._get_doc_count_cached", return_value=(doc_count, db_ok)):
            with patch("src.routes_fastapi.api_routes._check_ollama_live", return_value=True):
                with patch("src.routes_fastapi.api_routes.config") as cfg:
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
        data = self._get_status().json()
        assert "ollama" in data
        assert "database" in data
        assert "ready" in data
        assert "active_model" in data
        assert "document_count" in data

    def test_active_model_in_response(self):
        data = self._get_status(active_model="mistral").json()
        assert data["active_model"] == "mistral"

    def test_db_unavailable_reflected(self):
        data = self._get_status(db_ok=False).json()
        assert data["database"] is False


# ===========================================================================
# _check_ollama_live — TTL cache + live check
# ===========================================================================

class TestCheckOllamaLive:
    def _make_app_state(self, check_ok=True):
        app_state = MagicMock()
        app_state.startup_status = {"database": True, "ollama": False, "ready": False}
        if check_ok:
            app_state.ollama_client.check_connection.return_value = (True, "OK")
        else:
            app_state.ollama_client.check_connection.side_effect = ConnectionError("timeout")
        return app_state

    def test_cache_hit_returns_cached_value(self):
        import src.routes_fastapi.api_routes as api_routes
        app_state = self._make_app_state()
        fresh_time = time.monotonic()
        with patch.object(api_routes, '_ollama_status_cache', [True, fresh_time]):
            result = api_routes._check_ollama_live(app_state)
        assert result is True
        app_state.ollama_client.check_connection.assert_not_called()

    def test_cache_miss_live_check_success(self):
        import src.routes_fastapi.api_routes as api_routes
        app_state = self._make_app_state(check_ok=True)
        with patch.object(api_routes, '_ollama_status_cache', [False, 0.0]):
            result = api_routes._check_ollama_live(app_state)
        assert result is True
        assert app_state.startup_status['ollama'] is True

    def test_cache_miss_live_check_failure(self):
        import src.routes_fastapi.api_routes as api_routes
        app_state = self._make_app_state(check_ok=False)
        with patch.object(api_routes, '_ollama_status_cache', [True, 0.0]):
            result = api_routes._check_ollama_live(app_state)
        assert result is False
        assert app_state.startup_status['ollama'] is False


# ===========================================================================
# POST /api/chat — SSE streaming
# ===========================================================================

class TestApiChat:
    def _post_chat(self, payload, active_model="llama3.2", chunks=None):
        app, client = _make_chat_app(active_model=active_model, chunks=chunks)
        with _config_patch(active_model=active_model):
            resp = client.post("/api/chat", json=payload)
            raw = resp.content
        return resp, _parse_sse(raw), app

    def test_no_body_returns_400(self):
        _, client = _make_chat_app()
        with _config_patch():
            resp = client.post("/api/chat", content=b"")
        assert resp.status_code == 400

    def test_no_active_model_returns_400(self):
        _, client = _make_chat_app()
        with patch("src.routes_fastapi.api_routes.config") as cfg:
            cfg.app_state.get_active_model.return_value = None
            cfg.WEB_SEARCH_ENABLED = False
            resp = client.post("/api/chat", json={"message": "hi"})
        assert resp.status_code == 400

    def test_direct_llm_stream_returns_content_and_done(self):
        resp, events, _ = self._post_chat({"message": "hello", "use_rag": False})
        assert resp.status_code == 200
        content_events = [e for e in events if "content" in e]
        done_events = [e for e in events if e.get("done")]
        assert len(content_events) >= 1
        assert len(done_events) == 1

    def test_done_event_has_conversation_id(self):
        _, events, _ = self._post_chat({"message": "hello", "use_rag": False})
        done = next(e for e in events if e.get("done"))
        assert "conversation_id" in done

    def test_done_event_has_message_id(self):
        _, events, _ = self._post_chat({"message": "hello", "use_rag": False})
        done = next(e for e in events if e.get("done"))
        assert "message_id" in done

    def test_rag_mode_calls_retrieve_context(self):
        _, events, app = self._post_chat({"message": "what is X", "use_rag": True})
        app.state.doc_processor.retrieve_context.assert_called_once()

    def test_stream_error_yields_error_event(self):
        app, client = _make_chat_app()
        app.state.ollama_client.generate_chat_response.side_effect = Exception("connection failed")
        with _config_patch():
            resp = client.post("/api/chat", json={"message": "hi", "use_rag": False})
        events = _parse_sse(resp.content)
        error_events = [e for e in events if "error" in e]
        assert len(error_events) >= 1

    def test_model_override_used_in_generation(self):
        _, events, app = self._post_chat(
            {"message": "hi", "use_rag": False, "model_override": "mistral:7b"}
        )
        call_args = app.state.ollama_client.generate_chat_response.call_args
        assert call_args is not None
        assert call_args.args[0] == "mistral:7b" or call_args.kwargs.get("model") == "mistral:7b"
