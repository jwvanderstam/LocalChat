"""
Temperature Feature Tests
=========================

Unit tests covering the temperature parameter added to:
  - ChatRequest validation (src/models.py)
  - generate_chat_response in OllamaClient (src/ollama_client.py)
  - _parse_chat_request / _stream_chat_response in api_routes (src/routes/api_routes.py)
"""

import json as _json
import os
from unittest.mock import AsyncMock, Mock, patch

import pytest

pytestmark = [pytest.mark.unit]


@pytest.fixture(scope="session", autouse=True)
def mock_env_vars():
    with patch.dict(os.environ, {
        'PG_PASSWORD': 'test_password',
        'OLLAMA_BASE_URL': 'http://localhost:11434',
        'SECRET_KEY': 'test_secret',
        'JWT_SECRET_KEY': 'test_jwt_secret',
    }):
        yield


# ============================================================================
# ChatRequest – model validation
# ============================================================================

class TestChatRequestTemperature:
    """Temperature field validation on ChatRequest."""

    def test_default_temperature(self):
        from src import config
        from src.models import ChatRequest
        req = ChatRequest(message="hello")
        assert req.temperature == config.DEFAULT_TEMPERATURE

    def test_temperature_zero(self):
        from src.models import ChatRequest
        req = ChatRequest(message="hello", temperature=0.0)
        assert req.temperature == 0.0

    def test_temperature_max(self):
        from src.models import ChatRequest
        req = ChatRequest(message="hello", temperature=2.0)
        assert req.temperature == 2.0

    def test_temperature_midrange(self):
        from src.models import ChatRequest
        req = ChatRequest(message="hello", temperature=1.3)
        assert req.temperature == pytest.approx(1.3)

    def test_temperature_below_zero_rejected(self):
        from pydantic import ValidationError

        from src.models import ChatRequest
        with pytest.raises(ValidationError):
            ChatRequest(message="hello", temperature=-0.1)

    def test_temperature_above_two_rejected(self):
        from pydantic import ValidationError

        from src.models import ChatRequest
        with pytest.raises(ValidationError):
            ChatRequest(message="hello", temperature=2.1)

    def test_temperature_preserved_alongside_other_fields(self):
        from src.models import ChatRequest
        req = ChatRequest(
            message="test",
            use_rag=False,
            enhance=False,
            history=[],
            temperature=1.5,
        )
        assert req.temperature == pytest.approx(1.5)
        assert req.use_rag is False

    def test_integer_coerced_to_float(self):
        """Pydantic should coerce int 1 to float 1.0."""
        from src.models import ChatRequest
        req = ChatRequest(message="hello", temperature=1)
        assert req.temperature == pytest.approx(1.0)
        assert isinstance(req.temperature, float)

    def test_string_coerced_to_float(self):
        """Pydantic v2 coerces numeric strings to float."""
        from src.models import ChatRequest
        req = ChatRequest(message="hello", temperature="0.5")
        assert req.temperature == pytest.approx(0.5)

    def test_very_small_positive_accepted(self):
        """Values very close to zero (but positive) are valid."""
        from src.models import ChatRequest
        req = ChatRequest(message="hello", temperature=0.001)
        assert req.temperature == pytest.approx(0.001)

    def test_negative_zero_accepted(self):
        """-0.0 satisfies ge=0 and is treated as 0.0."""
        from src.models import ChatRequest
        req = ChatRequest(message="hello", temperature=-0.0)
        assert req.temperature == pytest.approx(0.0)

    def test_large_negative_rejected(self):
        from pydantic import ValidationError

        from src.models import ChatRequest
        with pytest.raises(ValidationError):
            ChatRequest(message="hello", temperature=-100.0)

    def test_just_above_max_rejected(self):
        """2.0000001 exceeds the upper bound."""
        from pydantic import ValidationError

        from src.models import ChatRequest
        with pytest.raises(ValidationError):
            ChatRequest(message="hello", temperature=2.0000001)


# ============================================================================
# OllamaClient – temperature forwarded to Ollama options
# ============================================================================

def _make_async_stream_cm(lines: list[str], status_code: int = 200):
    """Build a mock async context manager for httpx.AsyncClient.stream()."""
    mock_response = Mock()
    mock_response.status_code = status_code

    async def _aiter_lines():
        for line in lines:
            yield line

    mock_response.aiter_lines = Mock(return_value=_aiter_lines())

    async def _aread():
        return b""

    mock_response.aread = _aread
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_response)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm, mock_response


class TestOllamaClientTemperature:
    """generate_chat_response passes temperature into the Ollama payload."""

    def _make_client(self):
        from src.ollama_client import OllamaClient
        return OllamaClient(base_url="http://localhost:11434")

    def _stream_lines(self, chunks: list[str]) -> list[str]:
        lines = [_json.dumps({"message": {"content": c}, "done": False}) for c in chunks]
        lines.append('{"message": {"content": ""}, "done": true}')
        return lines

    async def test_default_temperature_sent(self):
        client = self._make_client()
        cm, _ = _make_async_stream_cm(self._stream_lines(["hi"]))
        client._async_client.stream = Mock(return_value=cm)

        _ = [c async for c in client.generate_chat_response("llama3.2", [{"role": "user", "content": "hi"}])]
        payload = client._async_client.stream.call_args.kwargs['json']
        assert payload['options']['temperature'] == pytest.approx(0.7)

    async def test_custom_temperature_sent(self):
        client = self._make_client()
        cm, _ = _make_async_stream_cm(self._stream_lines(["hi"]))
        client._async_client.stream = Mock(return_value=cm)

        _ = [c async for c in client.generate_chat_response(
            "llama3.2", [{"role": "user", "content": "hi"}], temperature=0.1,
        )]
        payload = client._async_client.stream.call_args.kwargs['json']
        assert payload['options']['temperature'] == pytest.approx(0.1)

    async def test_high_temperature_sent(self):
        client = self._make_client()
        cm, _ = _make_async_stream_cm(self._stream_lines(["hi"]))
        client._async_client.stream = Mock(return_value=cm)

        _ = [c async for c in client.generate_chat_response(
            "llama3.2", [{"role": "user", "content": "hi"}], temperature=1.9,
        )]
        payload = client._async_client.stream.call_args.kwargs['json']
        assert payload['options']['temperature'] == pytest.approx(1.9)

    async def test_temperature_zero_sent(self):
        client = self._make_client()
        cm, _ = _make_async_stream_cm(self._stream_lines(["hi"]))
        client._async_client.stream = Mock(return_value=cm)

        _ = [c async for c in client.generate_chat_response(
            "llama3.2", [{"role": "user", "content": "hi"}], temperature=0.0,
        )]
        payload = client._async_client.stream.call_args.kwargs['json']
        assert payload['options']['temperature'] == pytest.approx(0.0)

    async def test_other_options_still_present(self):
        """Ensure num_gpu and num_ctx are not displaced by temperature."""
        client = self._make_client()
        cm, _ = _make_async_stream_cm(self._stream_lines(["hi"]))
        client._async_client.stream = Mock(return_value=cm)

        _ = [c async for c in client.generate_chat_response(
            "llama3.2", [{"role": "user", "content": "hi"}], temperature=0.5,
        )]
        opts = client._async_client.stream.call_args.kwargs['json']['options']
        assert 'num_gpu' in opts
        assert 'num_ctx' in opts
        assert 'temperature' in opts

    async def test_non_streaming_mode_includes_temperature(self):
        """Temperature must appear in the payload even when stream=False."""
        client = self._make_client()
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"message": {"content": "hi"}, "done": True}
        client._async_client.post = AsyncMock(return_value=mock_resp)

        _ = [c async for c in client.generate_chat_response(
            "llama3.2", [{"role": "user", "content": "hi"}],
            stream=False, temperature=0.4,
        )]
        opts = client._async_client.post.call_args.kwargs['json']['options']
        assert opts['temperature'] == pytest.approx(0.4)

    async def test_temperature_and_max_tokens_coexist(self):
        """Both temperature and num_predict must appear together in options."""
        client = self._make_client()
        cm, _ = _make_async_stream_cm(self._stream_lines(["hi"]))
        client._async_client.stream = Mock(return_value=cm)

        _ = [c async for c in client.generate_chat_response(
            "llama3.2", [{"role": "user", "content": "hi"}],
            max_tokens=256, temperature=1.1,
        )]
        opts = client._async_client.stream.call_args.kwargs['json']['options']
        assert opts['temperature'] == pytest.approx(1.1)
        assert opts['num_predict'] == 256

    async def test_temperature_exact_boundary_2_0_sent(self):
        """Boundary value 2.0 must pass through to the payload unchanged."""
        client = self._make_client()
        cm, _ = _make_async_stream_cm(self._stream_lines(["hi"]))
        client._async_client.stream = Mock(return_value=cm)

        _ = [c async for c in client.generate_chat_response(
            "llama3.2", [{"role": "user", "content": "hi"}], temperature=2.0,
        )]
        assert client._async_client.stream.call_args.kwargs['json']['options']['temperature'] == pytest.approx(2.0)


# ============================================================================
# _parse_chat_request – temperature included in returned dict
# ============================================================================

class TestParseChatRequest:
    """_parse_chat_request returns temperature in the field dict."""

    def test_temperature_included_with_default(self):
        from src import config
        from src.routes_fastapi.api_routes import _parse_chat_request
        fields = _parse_chat_request({'message': 'hi', 'use_rag': False})
        assert 'temperature' in fields
        assert fields['temperature'] == pytest.approx(config.DEFAULT_TEMPERATURE)

    def test_temperature_included_when_provided(self):
        from src.routes_fastapi.api_routes import _parse_chat_request
        fields = _parse_chat_request({'message': 'hi', 'use_rag': False, 'temperature': 1.2})
        assert fields['temperature'] == pytest.approx(1.2)

    def test_temperature_zero_passes_through(self):
        from src.routes_fastapi.api_routes import _parse_chat_request
        fields = _parse_chat_request({'message': 'hi', 'temperature': 0.0})
        assert fields['temperature'] == pytest.approx(0.0)

    def test_temperature_boundary_max_passes_through(self):
        from src.routes_fastapi.api_routes import _parse_chat_request
        fields = _parse_chat_request({'message': 'hi', 'temperature': 2.0})
        assert fields['temperature'] == pytest.approx(2.0)

    def test_temperature_out_of_range_raises(self):
        """Out-of-range temperature must bubble up as a validation error."""
        from pydantic import ValidationError

        from src.routes_fastapi.api_routes import _parse_chat_request
        with pytest.raises(ValidationError):
            _parse_chat_request({'message': 'hi', 'temperature': 3.0})

    def test_temperature_negative_raises(self):
        from pydantic import ValidationError

        from src.routes_fastapi.api_routes import _parse_chat_request
        with pytest.raises(ValidationError):
            _parse_chat_request({'message': 'hi', 'temperature': -1.0})


# ============================================================================
# api_chat endpoint – temperature forwarded to ollama_client
# ============================================================================

class TestStreamChatResponseTemperature:
    """api_chat passes temperature to generate_chat_response."""

    def _make_fastapi_app(self, chunks=None):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from src.routes_fastapi.api_routes import router

        test_app = FastAPI()
        test_app.include_router(router, prefix="/api")

        test_app.state.startup_status = {"database": True, "ollama": True, "ready": True}
        test_app.state.db = Mock()
        test_app.state.db.save_message = Mock(return_value=1)
        test_app.state.db.create_conversation_with_message = Mock(return_value=("conv-123", 1))
        test_app.state.db.get_conversation_document_filter = Mock(return_value=[])
        test_app.state.doc_processor = Mock()
        test_app.state.doc_processor.retrieve_context = Mock(return_value=[])
        test_app.state.ollama_client = Mock()
        _chunks = chunks or ["hi"]

        async def _default_gen(*args, **kwargs):
            for chunk in _chunks:
                yield chunk

        test_app.state.ollama_client.generate_chat_response.side_effect = _default_gen
        test_app.state.cloud_client = None
        test_app.state.testing = True
        test_app.state.embedding_cache = None
        test_app.state.query_cache = None
        test_app.state.connector_registry = None

        return test_app, TestClient(test_app, raise_server_exceptions=False)

    def _config_ctx(self, active_model="llama3.2"):
        import contextlib

        @contextlib.contextmanager
        def _ctx():
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

        return _ctx()

    def _post_and_parse(self, app, client, payload):
        import json as _json
        with self._config_ctx():
            resp = client.post("/api/chat", json=payload)
        events = []
        for line in resp.content.decode().splitlines():
            if line.startswith("data: "):
                events.append(_json.loads(line[6:]))
        return resp, events

    def test_temperature_forwarded(self):
        app, client = self._make_fastapi_app(["hello"])
        self._post_and_parse(app, client, {"message": "hi", "use_rag": False, "temperature": 0.3})
        app.state.ollama_client.generate_chat_response.assert_called_once()
        _, kwargs = app.state.ollama_client.generate_chat_response.call_args
        assert kwargs.get('temperature') == pytest.approx(0.3)

    def test_default_temperature_forwarded(self):
        from src import config as src_config
        app, client = self._make_fastapi_app(["hello"])
        self._post_and_parse(app, client, {"message": "hi", "use_rag": False})
        app.state.ollama_client.generate_chat_response.assert_called_once()
        _, kwargs = app.state.ollama_client.generate_chat_response.call_args
        assert kwargs.get('temperature') == pytest.approx(src_config.DEFAULT_TEMPERATURE)

    def test_tool_executor_bypasses_ollama_client(self):
        """When a tool_executor is injected it handles generation; ollama_client must not be called."""
        app, client = self._make_fastapi_app()
        mock_executor = Mock()
        mock_executor.execute.return_value = iter(["tool response"])

        with patch("src.routes_fastapi.api_routes._get_tool_executor", return_value=mock_executor):
            self._post_and_parse(app, client, {"message": "hi", "use_rag": False})

        app.state.ollama_client.generate_chat_response.assert_not_called()
        mock_executor.execute.assert_called_once()

    def test_sse_output_contains_content(self):
        """Streamed SSE lines must carry the content chunks."""
        app, client = self._make_fastapi_app(["Hello", " world"])
        _, events = self._post_and_parse(app, client, {"message": "hi", "use_rag": False, "temperature": 0.5})
        content_parts = [e['content'] for e in events if 'content' in e]
        assert content_parts == ["Hello", " world"]

    def test_temperature_zero_produces_deterministic_label_in_sse(self):
        """At temperature=0 the stream still completes and emits a done payload."""
        app, client = self._make_fastapi_app(["answer"])
        _, events = self._post_and_parse(app, client, {"message": "hi", "use_rag": False, "temperature": 0.0})
        done_payloads = [e for e in events if e.get('done')]
        assert len(done_payloads) == 1
