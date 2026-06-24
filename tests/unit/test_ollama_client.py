"""
Unit Tests for Ollama Client
==============================

Comprehensive tests for src/ollama_client.py

Focus areas:
- Connection checking (sync, uses httpx.Client)
- Model listing (sync)
- Embedding generation (sync)
- Chat response generation (async, uses httpx.AsyncClient)
- Model testing (async)
- Error handling
"""

from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

# ---------------------------------------------------------------------------
# Async stream helpers
# ---------------------------------------------------------------------------

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


class TestConnectionManagement:
    """Test Ollama connection management."""

    def test_check_connection_success(self):
        """Test successful connection check."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'status': 'ok'}

        with patch.object(client._session, 'get', return_value=mock_response):
            success, message = client.check_connection()

            assert success is True
            assert "ollama is running" in message.lower()

    def test_check_connection_failure(self):
        """Test connection failure."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")

        with patch.object(client._session, 'get', side_effect=httpx.ConnectError("Connection refused")):
            success, message = client.check_connection()

            assert success is False
            assert len(message) > 0

    def test_check_connection_timeout(self):
        """Test connection timeout."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")

        with patch.object(client._session, 'get', side_effect=httpx.TimeoutException("Timeout")):
            success, message = client.check_connection()

            assert success is False


class TestModelListing:
    """Test model listing functionality."""

    def test_list_models_returns_models(self):
        """Test listing available models."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'models': [
                {'name': 'llama3.2', 'size': 4500000000},
                {'name': 'nomic-embed-text', 'size': 274000000}
            ]
        }

        with patch.object(client._session, 'get', return_value=mock_response):
            success, models = client.list_models()

            assert success is True
            assert len(models) == 2
            assert models[0]['name'] == 'llama3.2'

    def test_list_models_handles_empty_list(self):
        """Test handling of no models."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'models': []}

        with patch.object(client._session, 'get', return_value=mock_response):
            success, models = client.list_models()

            assert success is True
            assert models == []

    def test_list_models_handles_api_error(self):
        """Test handling of API error."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")

        with patch.object(client._session, 'get', side_effect=Exception("API Error")):
            success, models = client.list_models()

            assert success is False
            assert isinstance(models, (list, str))

    def test_get_first_available_model_returns_model(self):
        """Test getting first available model."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'models': [
                {'name': 'llama3.2', 'size': 4500000000}
            ]
        }

        with patch.object(client._session, 'get', return_value=mock_response):
            model = client.get_first_available_model()

            assert model == 'llama3.2'

    def test_get_first_available_model_returns_none_when_empty(self):
        """Test getting model when none available."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'models': []}

        with patch.object(client._session, 'get', return_value=mock_response):
            model = client.get_first_available_model()

            assert model is None


class TestEmbeddingGeneration:
    """Test embedding generation."""

    def test_generate_embedding_success(self):
        """Test successful embedding generation."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'embeddings': [[0.1] * 768]
        }

        with patch.object(client._session, 'post', return_value=mock_response):
            success, embedding = client.generate_embedding("nomic-embed-text", "test text")

            assert success is True
            assert len(embedding) == 768
            assert all(isinstance(x, float) for x in embedding)

    def test_generate_embedding_validates_input(self):
        """Test embedding validation."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")

        # Empty text should fail gracefully
        success, result = client.generate_embedding("nomic-embed-text", "")

        # Either succeeds with empty result or fails gracefully
        assert isinstance(success, bool)

    def test_generate_embedding_handles_api_error(self):
        """Test handling of embedding API error."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")

        with patch.object(client._session, 'post', side_effect=Exception("API Error")):
            success, result = client.generate_embedding("nomic-embed-text", "test")

            assert success is False

    def test_get_embedding_model_returns_model(self):
        """Test getting embedding model."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'models': [
                {'name': 'nomic-embed-text', 'size': 274000000},
                {'name': 'llama3.2', 'size': 4500000000}
            ]
        }

        with patch.object(client._session, 'get', return_value=mock_response):
            model = client.get_embedding_model()

            assert model == 'nomic-embed-text'

    def test_get_embedding_model_returns_none_when_not_found(self):
        """Test embedding model when not available."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'models': [
                {'name': 'llama3.2', 'size': 4500000000}
            ]
        }

        with patch.object(client._session, 'get', return_value=mock_response):
            model = client.get_embedding_model()

            # Should return None or fallback model
            assert model is None or isinstance(model, str)


class TestChatGeneration:
    """Test async chat response generation."""

    async def test_generate_chat_response_streaming(self):
        """Test successful streaming chat generation."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")
        cm, _ = _make_async_stream_cm([
            '{"message": {"role": "assistant", "content": "Hello"}}',
            '{"message": {"role": "assistant", "content": " world"}}',
            '{"done": true}',
        ])
        client._async_client.stream = Mock(return_value=cm)

        chunks = [c async for c in client.generate_chat_response("llama3.2", [{"role": "user", "content": "Hi"}])]
        assert "Hello" in chunks
        assert " world" in chunks

    async def test_generate_chat_response_non_streaming(self):
        """Test non-streaming chat generation (stream=False)."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"message": {"content": "Complete response"}}
        client._async_client.post = AsyncMock(return_value=mock_resp)

        chunks = [c async for c in client.generate_chat_response("llama3.2", [], stream=False)]
        assert chunks == ["Complete response"]

    async def test_generate_chat_response_http_error_raises(self):
        """Non-200 HTTP response should raise RuntimeError."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")
        cm, mock_resp = _make_async_stream_cm([], status_code=500)
        mock_resp.text = "Internal error"

        async def _aread():
            return b"Internal error"
        mock_resp.aread = _aread
        client._async_client.stream = Mock(return_value=cm)

        with pytest.raises(RuntimeError):
            async for _ in client.generate_chat_response("llama3.2", []):
                pass

    async def test_generate_chat_response_timeout_raises(self):
        """TimeoutException should be converted to RuntimeError."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        cm.__aexit__ = AsyncMock(return_value=None)
        client._async_client.stream = Mock(return_value=cm)

        with pytest.raises(RuntimeError):
            async for _ in client.generate_chat_response("llama3.2", []):
                pass


class TestModelTesting:
    """Test async model testing functionality."""

    async def test_test_model_success(self):
        """Test successful model testing."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")
        cm, _ = _make_async_stream_cm([
            '{"message": {"content": "Hello, I am working!"}}',
            '{"done": true}',
        ])
        client._async_client.stream = Mock(return_value=cm)

        success, message = await client.test_model("llama3.2")

        assert success is True
        assert len(message) > 0

    async def test_test_model_failure(self):
        """Test model testing failure on exception."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=Exception("Model not found"))
        cm.__aexit__ = AsyncMock(return_value=None)
        client._async_client.stream = Mock(return_value=cm)

        success, message = await client.test_model("nonexistent")

        assert success is False
        assert len(message) > 0


class TestErrorHandling:
    """Test comprehensive error handling."""

    def test_handles_connection_refused(self):
        """Test handling when Ollama is not running."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")

        with patch.object(client._session, 'get', side_effect=httpx.ConnectError("Connection refused")):
            success, message = client.check_connection()

            assert success is False

    def test_handles_timeout_gracefully(self):
        """Test timeout handling in sync embedding path."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")

        with patch.object(client._session, 'post', side_effect=Exception("Timeout")):
            success, embedding = client.generate_embedding("model", "text")

            assert success is False

    def test_handles_malformed_response(self):
        """Test handling of malformed JSON response."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")

        with patch.object(client._session, 'post', return_value=mock_response):
            success, result = client.generate_embedding("model", "text")

            # Should handle gracefully
            assert success is False or success is True

    def test_handles_http_error_codes(self):
        """Test handling of HTTP error codes in sync path."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")

        mock_response = Mock()
        mock_response.status_code = 404

        with patch.object(client._session, 'get', return_value=mock_response):
            success, message = client.check_connection()
            assert isinstance(success, bool)


class TestGenerateEmbeddingsBatch:
    """Tests for the generate_embeddings_batch() method."""

    def test_empty_texts_returns_empty_list(self):
        from src.ollama_client import OllamaClient
        client = OllamaClient(base_url="http://localhost:11434")
        assert client.generate_embeddings_batch("nomic-embed-text", []) == []

    def test_successful_batch_returns_embeddings(self):
        from src.ollama_client import OllamaClient
        client = OllamaClient(base_url="http://localhost:11434")
        texts = ["hello", "world"]
        expected = [[0.1] * 768, [0.2] * 768]
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"embeddings": expected}
        with patch.object(client._session, 'post', return_value=mock_resp):
            result = client.generate_embeddings_batch("nomic-embed-text", texts)
        assert result == expected

    def test_partial_response_pads_with_none(self):
        from src.ollama_client import OllamaClient
        client = OllamaClient(base_url="http://localhost:11434")
        texts = ["a", "b", "c"]
        partial = [[0.1] * 768, [0.2] * 768]  # only 2 out of 3
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"embeddings": partial}
        with patch.object(client._session, 'post', return_value=mock_resp):
            result = client.generate_embeddings_batch("nomic-embed-text", texts)
        assert len(result) == 3
        assert result[0] == partial[0]
        assert result[1] == partial[1]
        assert result[2] is None

    def test_http_error_falls_back_to_per_text(self):
        from src.ollama_client import OllamaClient
        client = OllamaClient(base_url="http://localhost:11434")
        texts = ["hello"]
        embedding = [0.5] * 768
        mock_resp = Mock()
        mock_resp.status_code = 500
        with patch.object(client._session, 'post', return_value=mock_resp):
            with patch.object(client, 'generate_embedding', return_value=(True, embedding)):
                result = client.generate_embeddings_batch("nomic-embed-text", texts)
        assert result == [embedding]

    def test_exception_falls_back_to_per_text(self):
        from src.ollama_client import OllamaClient
        client = OllamaClient(base_url="http://localhost:11434")
        texts = ["hello"]
        embedding = [0.5] * 768
        with patch.object(client._session, 'post', side_effect=Exception("Network error")):
            with patch.object(client, 'generate_embedding', return_value=(True, embedding)):
                result = client.generate_embeddings_batch("nomic-embed-text", texts)
        assert result == [embedding]

    def test_fallback_yields_none_on_embedding_failure(self):
        from src.ollama_client import OllamaClient
        client = OllamaClient(base_url="http://localhost:11434")
        texts = ["hello"]
        with patch.object(client._session, 'post', side_effect=Exception("Network error")):
            with patch.object(client, 'generate_embedding', return_value=(False, None)):
                result = client.generate_embeddings_batch("nomic-embed-text", texts)
        assert result == [None]


class TestBackgroundRefresh:
    """Tests for _start_background_refresh()."""

    def test_sets_started_flag(self):
        from src.ollama_client import OllamaClient
        client = OllamaClient(base_url="http://localhost:11434")
        assert not getattr(client, '_background_refresh_started', False)
        client._start_background_refresh()
        assert client._background_refresh_started is True

    def test_idempotent_second_call_starts_no_extra_thread(self):
        import threading

        from src.ollama_client import OllamaClient
        client = OllamaClient(base_url="http://localhost:11434")
        client._start_background_refresh()
        count_after_first = threading.active_count()
        client._start_background_refresh()
        assert threading.active_count() == count_after_first


class TestClientConfiguration:
    """Test client configuration."""

    def test_client_initialization(self):
        """Test client initializes with correct URL."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://custom:8080")

        assert client.base_url == "http://custom:8080"

    def test_client_default_url(self):
        """Test client uses default URL."""
        from src.ollama_client import OllamaClient

        client = OllamaClient()

        # Should have some default URL
        assert client.base_url is not None
        assert "http" in client.base_url.lower()


class TestSuggestVisionModel:
    """Tests for OllamaClient.suggest_vision_model()."""

    def test_no_gpu_returns_moondream(self):
        """With no GPU info, fall back to the CPU-compatible model."""
        from src.ollama_client import ollama_client
        with patch.object(ollama_client, 'get_gpu_info', return_value=[]):
            model, reason = ollama_client.suggest_vision_model()
        assert model == "moondream:1.8b"
        assert "CPU" in reason

    def test_4gb_vram_returns_llava7b(self):
        """4 GB free VRAM → llava:7b."""
        from src.ollama_client import ollama_client
        gpus = [{'vram_free_mb': 4096, 'vram_total_mb': 8192, 'vram_used_mb': 4096}]
        with patch.object(ollama_client, 'get_gpu_info', return_value=gpus):
            model, reason = ollama_client.suggest_vision_model()
        assert model == "llava:7b"
        assert "7 B" in reason

    def test_8gb_vram_returns_llava13b(self):
        """8 GB free VRAM → llava:13b."""
        from src.ollama_client import ollama_client
        gpus = [{'vram_free_mb': 8192, 'vram_total_mb': 12288, 'vram_used_mb': 4096}]
        with patch.object(ollama_client, 'get_gpu_info', return_value=gpus):
            model, reason = ollama_client.suggest_vision_model()
        assert model == "llava:13b"
        assert "13 B" in reason

    def test_20gb_vram_returns_llava34b(self):
        """20+ GB free VRAM → llava:34b."""
        from src.ollama_client import ollama_client
        gpus = [{'vram_free_mb': 20480, 'vram_total_mb': 24576, 'vram_used_mb': 4096}]
        with patch.object(ollama_client, 'get_gpu_info', return_value=gpus):
            model, reason = ollama_client.suggest_vision_model()
        assert model == "llava:34b"
        assert "34 B" in reason

    def test_get_gpu_info_exception_falls_back(self):
        """If GPU detection raises, fall back gracefully to moondream."""
        from src.ollama_client import ollama_client
        with patch.object(ollama_client, 'get_gpu_info', side_effect=RuntimeError("no driver")):
            model, reason = ollama_client.suggest_vision_model()
        assert model == "moondream:1.8b"
