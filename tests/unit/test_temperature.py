"""
Temperature Feature Tests
=========================

Unit tests covering the temperature parameter added to:
  - ChatRequest validation (src/models.py)
  - generate_chat_response in OllamaClient (src/ollama_client.py)
  - _parse_chat_request / _stream_chat_response in api_routes (src/routes/api_routes.py)
"""

import os
from unittest.mock import MagicMock, Mock, patch

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

class TestOllamaClientTemperature:
    """generate_chat_response passes temperature into the Ollama payload."""

    def _make_client(self):
        from src.ollama_client import OllamaClient
        return OllamaClient(base_url="http://localhost:11434")

    def _mock_stream_response(self, chunks):
        """Return a mock requests.Response that streams JSON lines."""
        lines = []
        for chunk in chunks:
            import json
            lines.append(json.dumps({"message": {"content": chunk}, "done": False}).encode())
        lines.append(b'{"message": {"content": ""}, "done": true}')

        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.iter_lines.return_value = iter(lines)
        return mock_resp

    def test_default_temperature_sent(self):
        client = self._make_client()
        mock_resp = self._mock_stream_response(["hi"])

        with patch.object(client._session, 'post', return_value=mock_resp) as mock_post:
            list(client.generate_chat_response("llama3.2", [{"role": "user", "content": "hi"}]))
            payload = mock_post.call_args[1]['json']
            assert payload['options']['temperature'] == pytest.approx(0.7)

    def test_custom_temperature_sent(self):
        client = self._make_client()
        mock_resp = self._mock_stream_response(["hi"])

        with patch.object(client._session, 'post', return_value=mock_resp) as mock_post:
            list(client.generate_chat_response(
                "llama3.2",
                [{"role": "user", "content": "hi"}],
                temperature=0.1,
            ))
            payload = mock_post.call_args[1]['json']
            assert payload['options']['temperature'] == pytest.approx(0.1)

    def test_high_temperature_sent(self):
        client = self._make_client()
        mock_resp = self._mock_stream_response(["hi"])

        with patch.object(client._session, 'post', return_value=mock_resp) as mock_post:
            list(client.generate_chat_response(
                "llama3.2",
                [{"role": "user", "content": "hi"}],
                temperature=1.9,
            ))
            payload = mock_post.call_args[1]['json']
            assert payload['options']['temperature'] == pytest.approx(1.9)

    def test_temperature_zero_sent(self):
        client = self._make_client()
        mock_resp = self._mock_stream_response(["hi"])

        with patch.object(client._session, 'post', return_value=mock_resp) as mock_post:
            list(client.generate_chat_response(
                "llama3.2",
                [{"role": "user", "content": "hi"}],
                temperature=0.0,
            ))
            payload = mock_post.call_args[1]['json']
            assert payload['options']['temperature'] == pytest.approx(0.0)

    def test_other_options_still_present(self):
        """Ensure num_gpu and num_ctx are not displaced by temperature."""
        client = self._make_client()
        mock_resp = self._mock_stream_response(["hi"])

        with patch.object(client._session, 'post', return_value=mock_resp) as mock_post:
            list(client.generate_chat_response(
                "llama3.2",
                [{"role": "user", "content": "hi"}],
                temperature=0.5,
            ))
            opts = mock_post.call_args[1]['json']['options']
            assert 'num_gpu' in opts
            assert 'num_ctx' in opts
            assert 'temperature' in opts

    def test_non_streaming_mode_includes_temperature(self):
        """Temperature must appear in the payload even when stream=False."""
        import json
        client = self._make_client()

        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"message": {"content": "hi"}, "done": True}

        with patch.object(client._session, 'post', return_value=mock_resp) as mock_post:
            list(client.generate_chat_response(
                "llama3.2",
                [{"role": "user", "content": "hi"}],
                stream=False,
                temperature=0.4,
            ))
            opts = mock_post.call_args[1]['json']['options']
            assert opts['temperature'] == pytest.approx(0.4)

    def test_temperature_and_max_tokens_coexist(self):
        """Both temperature and num_predict must appear together in options."""
        client = self._make_client()
        mock_resp = self._mock_stream_response(["hi"])

        with patch.object(client._session, 'post', return_value=mock_resp) as mock_post:
            list(client.generate_chat_response(
                "llama3.2",
                [{"role": "user", "content": "hi"}],
                max_tokens=256,
                temperature=1.1,
            ))
            opts = mock_post.call_args[1]['json']['options']
            assert opts['temperature'] == pytest.approx(1.1)
            assert opts['num_predict'] == 256

    def test_temperature_exact_boundary_2_0_sent(self):
        """Boundary value 2.0 must pass through to the payload unchanged."""
        client = self._make_client()
        mock_resp = self._mock_stream_response(["hi"])

        with patch.object(client._session, 'post', return_value=mock_resp) as mock_post:
            list(client.generate_chat_response(
                "llama3.2",
                [{"role": "user", "content": "hi"}],
                temperature=2.0,
            ))
            assert mock_post.call_args[1]['json']['options']['temperature'] == pytest.approx(2.0)


# ============================================================================
# _parse_chat_request – temperature included in returned dict
# ============================================================================

class TestParseChatRequest:
    """_parse_chat_request returns temperature in the field dict."""

    def test_temperature_included_with_default(self):
        from src import config
        from src.routes.api_routes import _parse_chat_request
        fields = _parse_chat_request({'message': 'hi', 'use_rag': False})
        assert 'temperature' in fields
        assert fields['temperature'] == pytest.approx(config.DEFAULT_TEMPERATURE)

    def test_temperature_included_when_provided(self):
        from src.routes.api_routes import _parse_chat_request
        fields = _parse_chat_request({'message': 'hi', 'use_rag': False, 'temperature': 1.2})
        assert fields['temperature'] == pytest.approx(1.2)

    def test_temperature_zero_passes_through(self):
        from src.routes.api_routes import _parse_chat_request
        fields = _parse_chat_request({'message': 'hi', 'temperature': 0.0})
        assert fields['temperature'] == pytest.approx(0.0)

    def test_temperature_boundary_max_passes_through(self):
        from src.routes.api_routes import _parse_chat_request
        fields = _parse_chat_request({'message': 'hi', 'temperature': 2.0})
        assert fields['temperature'] == pytest.approx(2.0)

    def test_temperature_out_of_range_raises(self):
        """Out-of-range temperature must bubble up as a validation error."""
        from pydantic import ValidationError

        from src.routes.api_routes import _parse_chat_request
        with pytest.raises(ValidationError):
            _parse_chat_request({'message': 'hi', 'temperature': 3.0})

    def test_temperature_negative_raises(self):
        from pydantic import ValidationError

        from src.routes.api_routes import _parse_chat_request
        with pytest.raises(ValidationError):
            _parse_chat_request({'message': 'hi', 'temperature': -1.0})


# ============================================================================
# _stream_chat_response – temperature forwarded to ollama_client
# ============================================================================

class TestStreamChatResponseTemperature:
    """_stream_chat_response passes temperature to generate_chat_response."""

    def _make_app(self, chunks=None):
        app = Mock()
        app.ollama_client.generate_chat_response.return_value = iter(chunks or ["hi"])
        app.cloud_client = None  # disable cloud fallback in unit tests
        app.db = Mock()
        app.db.save_message = Mock(return_value=None)
        app.db.create_conversation = Mock(return_value="conv-123")
        app.db.add_message = Mock(return_value=None)
        return app

    def _drain(self, response):
        """Consume the SSE Response generator so the inner callable runs."""
        list(response.response)

    def test_temperature_forwarded(self):
        from src.routes.api_routes import _stream_chat_response

        app = self._make_app(["hello"])
        with patch('src.routes.api_routes._persist_assistant_message'):
            response = _stream_chat_response(app, "llama3.2", [], "conv-1", None, temperature=0.3)
            self._drain(response)
            app.ollama_client.generate_chat_response.assert_called_once()
            _, kwargs = app.ollama_client.generate_chat_response.call_args
            assert kwargs.get('temperature') == pytest.approx(0.3)

    def test_default_temperature_forwarded(self):
        from src.routes.api_routes import _stream_chat_response

        app = self._make_app(["hello"])
        with patch('src.routes.api_routes._persist_assistant_message'):
            response = _stream_chat_response(app, "llama3.2", [], "conv-1", None)
            self._drain(response)
            app.ollama_client.generate_chat_response.assert_called_once()
            _, kwargs = app.ollama_client.generate_chat_response.call_args
            assert kwargs.get('temperature') == pytest.approx(0.7)

    def test_tool_executor_bypasses_ollama_client(self):
        """When a tool_executor is provided it handles generation; ollama_client must not be called."""
        from src.routes.api_routes import _stream_chat_response

        app = self._make_app()
        tool_executor = Mock()
        tool_executor.execute.return_value = iter(["tool response"])

        with patch('src.routes.api_routes._persist_assistant_message'):
            response = _stream_chat_response(app, "llama3.2", [], "conv-1", tool_executor, temperature=0.9)
            self._drain(response)

        app.ollama_client.generate_chat_response.assert_not_called()
        tool_executor.execute.assert_called_once()

    def test_sse_output_contains_content(self):
        """Streamed SSE lines must carry the content chunks."""
        import json

        from src.routes.api_routes import _stream_chat_response

        app = self._make_app(["Hello", " world"])
        with patch('src.routes.api_routes._persist_assistant_message'):
            response = _stream_chat_response(app, "llama3.2", [], "conv-1", None, temperature=0.5)
            chunks = [line for line in response.response if line]

        payloads = [json.loads(c.removeprefix("data: ")) for c in chunks if c.startswith("data: ")]
        content_parts = [p['content'] for p in payloads if 'content' in p]
        assert content_parts == ["Hello", " world"]

    def test_temperature_zero_produces_deterministic_label_in_sse(self):
        """At temperature=0 the stream still completes and emits a done payload."""
        import json

        from src.routes.api_routes import _stream_chat_response

        app = self._make_app(["answer"])
        with patch('src.routes.api_routes._persist_assistant_message'):
            response = _stream_chat_response(app, "llama3.2", [], "conv-1", None, temperature=0.0)
            raw = list(response.response)

        payloads = [json.loads(c.removeprefix("data: ")) for c in raw if c.startswith("data: ")]
        done_payloads = [p for p in payloads if p.get('done')]
        assert len(done_payloads) == 1
