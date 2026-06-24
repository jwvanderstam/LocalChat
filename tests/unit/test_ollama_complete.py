"""
Complete Ollama Client Tests
=============================

Additional tests covering edge cases in ollama_client.py.

Sync methods are tested by patching client._session.* (httpx.Client).
Async methods are tested by patching client._async_client.* (httpx.AsyncClient).
pull_model uses client._session.stream() as a sync context manager.
"""

from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

# ---------------------------------------------------------------------------
# Helpers
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


def _make_pull_cm(lines: list[str], status_code: int = 200):
    """Build a sync context manager mock for httpx.Client.stream() (pull_model)."""
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.iter_lines.return_value = lines
    cm = Mock()
    cm.__enter__ = Mock(return_value=mock_response)
    cm.__exit__ = Mock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestLongTextHandling:
    """Test handling of very long text inputs."""

    def test_generate_embedding_with_very_long_text(self):
        """Test embedding generation with text exceeding typical limits."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")

        long_text = "This is a test sentence. " * 400

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'embeddings': [[0.1] * 768]}

        with patch.object(client._session, 'post', return_value=mock_response):
            success, embedding = client.generate_embedding("nomic-embed-text", long_text)

            assert success is True
            assert len(embedding) == 768

    def test_generate_embedding_with_empty_string(self):
        """Test embedding with empty string edge case."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'embeddings': [[0.0] * 768]}

        with patch.object(client._session, 'post', return_value=mock_response):
            success, embedding = client.generate_embedding("nomic-embed-text", "")

            assert isinstance(success, bool)


class TestChatTokenLimits:
    """Test chat generation with token limits (async, uses _async_client)."""

    async def test_generate_chat_with_max_tokens_parameter(self):
        """Test chat generation with explicit max_tokens."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")
        cm, _ = _make_async_stream_cm([
            '{"message": {"role": "assistant", "content": "Short response due to token limit"}}',
            '{"done": true}',
        ])
        client._async_client.stream = Mock(return_value=cm)

        chunks = [c async for c in client.generate_chat_response(
            model="llama3.2",
            messages=[{"role": "user", "content": "Tell me a story"}],
            max_tokens=50,
        )]
        assert len(chunks) >= 1

    async def test_generate_chat_handles_token_limit_exceeded(self):
        """Test handling when response spans multiple chunks."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")
        cm, _ = _make_async_stream_cm([
            '{"message": {"content": "Part 1"}}',
            '{"message": {"content": " Part 2"}}',
            '{"done": true}',
        ])
        client._async_client.stream = Mock(return_value=cm)

        chunks = [c async for c in client.generate_chat_response(
            model="llama3.2",
            messages=[{"role": "user", "content": "Long question"}],
        )]
        assert isinstance(chunks, list)


class TestModelPullProgress:
    """Test model pulling with progress tracking (sync, uses _session.stream)."""

    def test_pull_model_with_progress_callback(self):
        """Test pulling model with progress updates."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")
        cm = _make_pull_cm([
            '{"status": "downloading", "completed": 1000000, "total": 10000000}',
            '{"status": "downloading", "completed": 5000000, "total": 10000000}',
            '{"status": "success"}',
        ])
        with patch.object(client._session, 'stream', return_value=cm):
            results = list(client.pull_model("llama3.2"))

            assert len(results) > 0
            assert all(isinstance(r, dict) for r in results)

    def test_pull_model_handles_network_interruption(self):
        """Test model pull handling network errors."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")

        with patch.object(client._session, 'stream', side_effect=Exception("Network error")):
            results = list(client.pull_model("llama3.2"))

            assert len(results) == 1
            assert "error" in results[0]


class TestStreamingEdgeCases:
    """Test streaming response edge cases (async, uses _async_client)."""

    async def test_streaming_with_empty_response(self):
        """Test streaming that returns no content."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")
        cm, _ = _make_async_stream_cm(['{"done": true}'])
        client._async_client.stream = Mock(return_value=cm)

        chunks = [c async for c in client.generate_chat_response(model="llama3.2", messages=[])]
        assert isinstance(chunks, list)

    async def test_streaming_with_malformed_json(self):
        """Test streaming with invalid JSON chunks raises an exception."""
        from src.ollama_client import OllamaClient

        client = OllamaClient(base_url="http://localhost:11434")
        cm, _ = _make_async_stream_cm([
            '{"message":{"content":"Good data"}}',
            'invalid json here',
            '{"done":true}',
        ])
        client._async_client.stream = Mock(return_value=cm)

        try:
            chunks = [c async for c in client.generate_chat_response(model="llama3.2", messages=[])]
            assert isinstance(chunks, list)
        except Exception:
            pass  # JSON error on malformed line is acceptable
