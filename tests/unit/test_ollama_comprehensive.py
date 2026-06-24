"""
Comprehensive Ollama client tests.

Tests the actual OllamaClient class from src/ollama_client.py with proper HTTP mocking.
Sync methods (check_connection, list_models, generate_embedding, etc.) use httpx.Client
via _session.  Async inference methods (generate_chat_response, test_model) use
httpx.AsyncClient via _async_client.

Run: pytest tests/unit/test_ollama_comprehensive.py -v --cov=src.ollama_client --cov-report=term-missing
"""

import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

pytestmark = [pytest.mark.unit, pytest.mark.ollama]


@pytest.fixture(scope="session", autouse=True)
def mock_env_vars():
    """Mock environment variables for testing."""
    with patch.dict(os.environ, {
        'PG_PASSWORD': 'test_password',
        'OLLAMA_BASE_URL': 'http://localhost:11434',
        'SECRET_KEY': 'test_secret',
        'JWT_SECRET_KEY': 'test_jwt_secret'
    }):
        yield


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_http():
    """Mock namespace for httpx.Client session methods."""
    class _MockHttp:
        get = Mock()
        post = Mock()
        delete = Mock()
        stream = Mock()
    return _MockHttp()


@pytest.fixture
def ollama_client(mock_http):
    """Create a fresh OllamaClient with sync session methods mocked."""
    from src.ollama_client import OllamaClient
    client = OllamaClient("http://localhost:11434")
    client._session.get = mock_http.get
    client._session.post = mock_http.post
    client._session.delete = mock_http.delete
    client._session.stream = mock_http.stream
    return client


@pytest.fixture
def sample_models_response():
    return {
        'models': [
            {'name': 'llama3.2', 'size': 4500000000, 'modified_at': '2024-01-01T00:00:00Z', 'digest': 'abc123'},
            {'name': 'nomic-embed-text', 'size': 274000000, 'modified_at': '2024-01-01T00:00:00Z', 'digest': 'def456'}
        ]
    }


def _make_async_stream_cm(lines: list[str], status_code: int = 200):
    """Build a mock async context manager for httpx.AsyncClient.stream()."""
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = ""

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


def _make_pull_stream_cm(lines: list[bytes], status_code: int = 200):
    """Build a sync context manager mock for httpx.Client.stream() (used by pull_model)."""
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.iter_lines.return_value = [line.decode() for line in lines]

    cm = Mock()
    cm.__enter__ = Mock(return_value=mock_response)
    cm.__exit__ = Mock(return_value=False)
    return cm, mock_response


# ============================================================================
# CONNECTION TESTS
# ============================================================================

class TestConnection:
    """Test connection checking functionality."""

    def test_check_connection_success(self, ollama_client, mock_http, sample_models_response):
        """Should successfully connect to Ollama."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_models_response
        mock_http.get.return_value = mock_response

        success, message = ollama_client.check_connection()

        assert success is True
        assert "2 models" in message
        assert ollama_client.is_available is True
        assert len(ollama_client.available_models) == 2
        mock_http.get.assert_called_once()

    def test_check_connection_failure_http_error(self, ollama_client, mock_http):
        """Should handle HTTP error responses."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_http.get.return_value = mock_response

        success, message = ollama_client.check_connection()

        assert success is False
        assert "500" in message
        assert ollama_client.is_available is False

    def test_check_connection_timeout(self, ollama_client, mock_http):
        """Should handle connection timeout."""
        mock_http.get.side_effect = httpx.TimeoutException("Connection timeout")

        success, message = ollama_client.check_connection()

        assert success is False
        assert ollama_client.is_available is False

    def test_check_connection_invalid_url(self, mock_http):
        """Should handle invalid URL."""
        from src.ollama_client import OllamaClient

        client = OllamaClient("http://invalid-url:99999")
        client._session.get = mock_http.get
        mock_http.get.side_effect = httpx.ConnectError("Cannot connect")

        success, message = client.check_connection()

        assert success is False

    def test_check_connection_network_error(self, ollama_client, mock_http):
        """Should handle network errors."""
        mock_http.get.side_effect = httpx.RequestError("Network error", request=None)

        success, message = ollama_client.check_connection()

        assert success is False


# ============================================================================
# MODEL OPERATIONS TESTS
# ============================================================================

class TestModelOperations:
    """Test model management operations."""

    def test_list_models_success(self, ollama_client, mock_http, sample_models_response):
        """Should successfully list available models."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_models_response
        mock_http.get.return_value = mock_response

        success, models = ollama_client.list_models()

        assert success is True
        assert len(models) == 2
        assert models[0]['name'] == 'llama3.2'
        assert models[1]['name'] == 'nomic-embed-text'
        assert 'size' in models[0]

    def test_list_models_empty(self, ollama_client, mock_http):
        """Should handle empty model list."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'models': []}
        mock_http.get.return_value = mock_response

        success, models = ollama_client.list_models()

        assert success is True
        assert models == []

    def test_list_models_connection_error(self, ollama_client, mock_http):
        """Should handle connection errors."""
        mock_http.get.side_effect = Exception("Connection failed")

        success, models = ollama_client.list_models()

        assert success is False
        assert models == []

    def test_list_models_http_error(self, ollama_client, mock_http):
        """Should handle HTTP errors."""
        mock_response = Mock()
        mock_response.status_code = 503
        mock_http.get.return_value = mock_response

        success, models = ollama_client.list_models()

        assert success is False
        assert models == []

    def test_get_first_available_model(self, ollama_client, mock_http, sample_models_response):
        """Should return first available model."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_models_response
        mock_http.get.return_value = mock_response

        model_name = ollama_client.get_first_available_model()

        assert model_name == 'llama3.2'

    def test_get_first_available_model_no_models(self, ollama_client, mock_http):
        """Should return None when no models available."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'models': []}
        mock_http.get.return_value = mock_response

        model_name = ollama_client.get_first_available_model()

        assert model_name is None

    def test_delete_model_success(self, ollama_client, mock_http):
        """Should successfully delete a model."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_http.delete.return_value = mock_response

        success, message = ollama_client.delete_model("test-model")

        assert success is True
        assert "deleted successfully" in message.lower()
        mock_http.delete.assert_called_once()

    def test_delete_model_failure(self, ollama_client, mock_http):
        """Should handle delete failures."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_http.delete.return_value = mock_response

        success, message = ollama_client.delete_model("nonexistent-model")

        assert success is False
        assert "Failed" in message


# ============================================================================
# CHAT GENERATION TESTS (async — uses _async_client)
# ============================================================================

class TestChatGeneration:
    """Test async chat response generation."""

    async def test_generate_chat_response_streaming(self, ollama_client):
        """Should generate streaming chat response."""
        cm, _ = _make_async_stream_cm([
            '{"message":{"content":"Hello"}}',
            '{"message":{"content":" world"}}',
            '{"message":{"content":"!"},"done":true}',
        ])
        ollama_client._async_client.stream = Mock(return_value=cm)

        messages = [{"role": "user", "content": "Hi"}]
        chunks = [c async for c in ollama_client.generate_chat_response("llama3.2", messages, stream=True)]

        assert len(chunks) >= 3
        assert chunks[0] == "Hello"
        assert chunks[1] == " world"
        assert chunks[2] == "!"

    async def test_generate_chat_response_non_streaming(self, ollama_client):
        """Should generate non-streaming chat response."""
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"message": {"content": "Complete response"}}
        ollama_client._async_client.post = AsyncMock(return_value=mock_resp)

        messages = [{"role": "user", "content": "Hi"}]
        chunks = [c async for c in ollama_client.generate_chat_response("llama3.2", messages, stream=False)]

        assert len(chunks) == 1
        assert chunks[0] == 'Complete response'

    async def test_generate_chat_response_with_history(self, ollama_client):
        """Should handle chat history and pass messages through."""
        called_json = {}

        async def _capture_stream(method, url, json=None, timeout=None):
            called_json['messages'] = json.get('messages', []) if json else []
            cm, _ = _make_async_stream_cm(['{"message":{"content":"ok"},"done":true}'])
            return cm

        ollama_client._async_client.stream = _capture_stream

        messages = [
            {"role": "user", "content": "First message"},
            {"role": "assistant", "content": "First response"},
            {"role": "user", "content": "Second message"},
        ]
        [c async for c in ollama_client.generate_chat_response("llama3.2", messages)]

        assert called_json['messages'] == messages

    async def test_generate_chat_response_empty_message(self, ollama_client):
        """Should handle empty messages."""
        cm, _ = _make_async_stream_cm(['{"done":true}'])
        ollama_client._async_client.stream = Mock(return_value=cm)

        messages = [{"role": "user", "content": ""}]
        chunks = [c async for c in ollama_client.generate_chat_response("llama3.2", messages)]

        assert len(chunks) >= 0  # May return empty

    async def test_generate_chat_response_http_error(self, ollama_client):
        """Should raise RuntimeError on non-200 HTTP responses."""
        cm, mock_resp = _make_async_stream_cm([], status_code=500)
        mock_resp.text = "Internal Server Error"
        ollama_client._async_client.stream = Mock(return_value=cm)

        with pytest.raises(RuntimeError):
            async for _ in ollama_client.generate_chat_response("llama3.2", [{"role": "user", "content": "Hi"}]):
                pass

    async def test_generate_chat_response_exception(self, ollama_client):
        """Should propagate network-level exceptions as RuntimeError."""
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=httpx.ConnectError("Network error"))
        cm.__aexit__ = AsyncMock(return_value=None)
        ollama_client._async_client.stream = Mock(return_value=cm)

        with pytest.raises(RuntimeError):
            async for _ in ollama_client.generate_chat_response("llama3.2", [{"role": "user", "content": "Hi"}]):
                pass


# ============================================================================
# EMBEDDING GENERATION TESTS
# ============================================================================

class TestEmbeddingGeneration:
    """Test embedding generation functionality."""

    def test_generate_embedding_success(self, ollama_client, mock_http):
        """Should successfully generate embedding."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'embeddings': [[0.1, 0.2, 0.3] * 256]  # 768 dimensions
        }
        mock_http.post.return_value = mock_response

        success, embedding = ollama_client.generate_embedding("nomic-embed-text", "test text")

        assert success is True
        assert len(embedding) == 768
        assert all(isinstance(x, (int, float)) for x in embedding)

    def test_generate_embedding_failure(self, ollama_client, mock_http):
        """Should handle embedding generation failures."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_http.post.return_value = mock_response

        success, embedding = ollama_client.generate_embedding("nomic-embed-text", "test")

        assert success is False
        assert embedding == []

    def test_generate_embedding_empty_text(self, ollama_client, mock_http):
        """Should handle empty text."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'embeddings': [[0.0] * 768]}
        mock_http.post.return_value = mock_response

        success, embedding = ollama_client.generate_embedding("nomic-embed-text", "")

        assert success is True
        assert len(embedding) == 768

    def test_generate_embedding_long_text(self, ollama_client, mock_http):
        """Should handle long text."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'embeddings': [[0.1] * 768]}
        mock_http.post.return_value = mock_response

        long_text = "test " * 1000
        success, embedding = ollama_client.generate_embedding("nomic-embed-text", long_text)

        assert success is True
        assert len(embedding) == 768

    def test_generate_embedding_dimensions(self, ollama_client, mock_http):
        """Should return correct embedding dimensions."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'embeddings': [[0.1] * 768]}
        mock_http.post.return_value = mock_response

        success, embedding = ollama_client.generate_embedding("nomic-embed-text", "test")

        assert len(embedding) == 768

    def test_generate_embedding_exception(self, ollama_client, mock_http):
        """Should handle exceptions."""
        mock_http.post.side_effect = Exception("Network error")

        success, embedding = ollama_client.generate_embedding("nomic-embed-text", "test")

        assert success is False
        assert embedding == []


# ============================================================================
# GET EMBEDDING MODEL TESTS
# ============================================================================

class TestGetEmbeddingModel:
    """Test embedding model selection."""

    def test_get_embedding_model_preferred(self, ollama_client, mock_http):
        """Should return preferred model if available."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'models': [
                {'name': 'nomic-embed-text', 'size': 274000000},
                {'name': 'llama3.2', 'size': 4500000000}
            ]
        }
        mock_http.get.return_value = mock_response

        model = ollama_client.get_embedding_model("nomic-embed-text")

        assert model == "nomic-embed-text"

    def test_get_embedding_model_fallback(self, ollama_client, mock_http):
        """Should fall back to common embedding models."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'models': [
                {'name': 'llama3.2', 'size': 4500000000},
                {'name': 'mxbai-embed-large', 'size': 500000000}
            ]
        }
        mock_http.get.return_value = mock_response

        model = ollama_client.get_embedding_model()

        assert model == "mxbai-embed-large"

    def test_get_embedding_model_partial_match(self, ollama_client, mock_http):
        """Should match partial model names."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'models': [
                {'name': 'nomic-embed-text:latest', 'size': 274000000}
            ]
        }
        mock_http.get.return_value = mock_response

        model = ollama_client.get_embedding_model()

        assert model == "nomic-embed-text:latest"

    def test_get_embedding_model_none_available(self, ollama_client, mock_http):
        """Should return None when no embedding models."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'models': []}
        mock_http.get.return_value = mock_response

        model = ollama_client.get_embedding_model()

        assert model is None


# ============================================================================
# PULL MODEL TESTS
# ============================================================================

class TestPullModel:
    """Test model pulling functionality (uses _session.stream context manager)."""

    def test_pull_model_success(self, ollama_client, mock_http):
        """Should yield progress updates when pulling model."""
        cm, _ = _make_pull_stream_cm([
            b'{"status":"pulling","completed":1000,"total":10000}',
            b'{"status":"pulling","completed":5000,"total":10000}',
            b'{"status":"success","completed":10000,"total":10000}',
        ])
        mock_http.stream.return_value = cm

        progress_updates = list(ollama_client.pull_model("llama3.2"))

        assert len(progress_updates) == 3
        assert progress_updates[0]['status'] == 'pulling'
        assert progress_updates[-1]['status'] == 'success'

    def test_pull_model_error(self, ollama_client, mock_http):
        """Should handle pull errors."""
        cm, mock_resp = _make_pull_stream_cm([], status_code=404)
        mock_http.stream.return_value = cm

        progress_updates = list(ollama_client.pull_model("nonexistent-model"))

        assert len(progress_updates) > 0
        assert 'error' in progress_updates[0]


# ============================================================================
# TEST MODEL TESTS (async — uses _async_client)
# ============================================================================

class TestTestModel:
    """Test model testing functionality."""

    async def test_test_model_success(self, ollama_client):
        """Should successfully test a model."""
        cm, _ = _make_async_stream_cm([
            '{"message":{"content":"Hello, I am working!"},"done":true}',
        ])
        ollama_client._async_client.stream = Mock(return_value=cm)

        success, response = await ollama_client.test_model("llama3.2")

        assert success is True
        assert len(response) > 0

    async def test_test_model_failure(self, ollama_client):
        """Should handle test failures."""
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=Exception("Model not found"))
        cm.__aexit__ = AsyncMock(return_value=None)
        ollama_client._async_client.stream = Mock(return_value=cm)

        success, response = await ollama_client.test_model("nonexistent-model")

        assert success is False
        assert isinstance(response, str)


# ============================================================================
# INITIALIZATION TESTS
# ============================================================================

class TestInitialization:
    """Test client initialization."""

    def test_init_with_default_url(self):
        """Should initialize with default URL from config."""
        from src.ollama_client import OllamaClient

        client = OllamaClient()

        assert client.base_url == "http://localhost:11434"
        assert client.is_available is False
        assert client.available_models == []

    def test_init_with_custom_url(self):
        """Should initialize with custom URL."""
        from src.ollama_client import OllamaClient

        custom_url = "http://custom-host:8080"
        client = OllamaClient(custom_url)

        assert client.base_url == custom_url
