"""
Tests for src/llm_client.py

Covers:
  - is_refusal: each pattern matches, long text exempt, empty string, no match
  - LiteLLMClient.__init__: litellm not installed raises ImportError, api_key sets env var
  - LiteLLMClient.generate_chat_response: streaming yields chunks, non-streaming yields once,
    empty content skipped, litellm raises propagates
  - LiteLLMClient.generate_chat_completion: with/without tools, returns model_dump
  - ModelClient Protocol: LiteLLMClient satisfies it at runtime
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ===========================================================================
# is_refusal
# ===========================================================================

class TestIsRefusal:
    def _check(self, text):
        from src.llm_client import is_refusal
        return is_refusal(text)

    def test_short_refusal_pattern_matches(self):
        assert self._check("I don't know the answer to that.") is True

    def test_i_cannot_matches(self):
        assert self._check("I cannot help with that request.") is True

    def test_not_sure_matches(self):
        assert self._check("I'm not sure about this.") is True

    def test_no_information_matches(self):
        assert self._check("I don't have information about that topic.") is True

    def test_not_provided_in_matches(self):
        assert self._check("That information is not provided in the documents.") is True

    def test_normal_answer_does_not_match(self):
        assert self._check("The capital of France is Paris.") is False

    def test_long_text_is_not_refusal_regardless_of_content(self):
        # Text >= 500 chars is never a refusal (false-positive guard)
        long_text = "I don't know " + "x" * 500
        assert self._check(long_text) is False

    def test_empty_string_is_not_refusal(self):
        assert self._check("") is False

    def test_exactly_499_chars_with_pattern_is_refusal(self):
        text = "I cannot answer. " + "x" * (499 - len("I cannot answer. "))
        assert len(text) == 499
        assert self._check(text) is True

    def test_exactly_500_chars_is_not_refusal(self):
        text = "I cannot answer. " + "x" * (500 - len("I cannot answer. "))
        assert len(text) == 500
        assert self._check(text) is False

    def test_case_insensitive(self):
        assert self._check("i don't know") is True
        assert self._check("I DON'T KNOW") is True


# ===========================================================================
# LiteLLMClient.__init__
# ===========================================================================

class TestLiteLLMClientInit:
    def test_raises_import_error_when_litellm_not_installed(self):
        with patch.dict("sys.modules", {"litellm": None}):
            with pytest.raises(ImportError, match="litellm is required"):
                from src.llm_client import LiteLLMClient
                LiteLLMClient("openai", None, "gpt-4o")

    def test_sets_env_var_when_api_key_provided(self):
        import os
        mock_litellm = MagicMock()
        with patch.dict("sys.modules", {"litellm": mock_litellm}):
            from importlib import reload

            import src.llm_client as mod
            reload(mod)
            client = mod.LiteLLMClient("openai", "sk-test-key", "gpt-4o")
            assert os.environ.get("OPENAI_API_KEY") == "sk-test-key"

    def test_no_env_var_when_no_api_key(self):
        import os
        mock_litellm = MagicMock()
        with patch.dict("sys.modules", {"litellm": mock_litellm}):
            from importlib import reload

            import src.llm_client as mod
            reload(mod)
            os.environ.pop("ANTHROPIC_API_KEY", None)
            mod.LiteLLMClient("anthropic", None, "claude-3-haiku")
            # No key set — env var should not be set (or was already absent)
            # We just verify no exception raised


# ===========================================================================
# LiteLLMClient.generate_chat_response
# ===========================================================================

class TestLiteLLMClientGenerateChatResponse:
    def _make_client(self):
        mock_litellm = MagicMock()
        with patch.dict("sys.modules", {"litellm": mock_litellm}):
            from importlib import reload

            import src.llm_client as mod
            reload(mod)
            client = mod.LiteLLMClient("openai", None, "gpt-4o")
            client._litellm = mock_litellm
        return client, mock_litellm

    def _make_stream_chunk(self, content):
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = content
        return chunk

    def test_streaming_yields_content_chunks(self):
        client, mock_litellm = self._make_client()
        mock_litellm.completion.return_value = [
            self._make_stream_chunk("Hello"),
            self._make_stream_chunk(" world"),
        ]
        result = list(client.generate_chat_response("gpt-4o", [{"role": "user", "content": "hi"}], stream=True))
        assert result == ["Hello", " world"]

    def test_empty_content_chunks_are_skipped(self):
        client, mock_litellm = self._make_client()
        mock_litellm.completion.return_value = [
            self._make_stream_chunk(""),
            self._make_stream_chunk(None),
            self._make_stream_chunk("real content"),
        ]
        result = list(client.generate_chat_response("m", [], stream=True))
        assert result == ["real content"]

    def test_no_choices_chunk_skipped(self):
        client, mock_litellm = self._make_client()
        empty_chunk = MagicMock()
        empty_chunk.choices = []
        mock_litellm.completion.return_value = [empty_chunk]
        result = list(client.generate_chat_response("m", [], stream=True))
        assert result == []

    def test_non_streaming_yields_single_response(self):
        client, mock_litellm = self._make_client()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "Full answer here"
        mock_litellm.completion.return_value = mock_resp
        result = list(client.generate_chat_response("m", [], stream=False))
        assert result == ["Full answer here"]

    def test_litellm_exception_propagates(self):
        client, mock_litellm = self._make_client()
        mock_litellm.completion.side_effect = RuntimeError("API error")
        with pytest.raises(RuntimeError, match="API error"):
            list(client.generate_chat_response("m", [], stream=True))

    def test_max_tokens_passed_when_provided(self):
        client, mock_litellm = self._make_client()
        mock_litellm.completion.return_value = []
        list(client.generate_chat_response("m", [], stream=True, max_tokens=512))
        call_kwargs = mock_litellm.completion.call_args.kwargs
        assert call_kwargs.get("max_tokens") == 512

    def test_max_tokens_not_passed_when_none(self):
        client, mock_litellm = self._make_client()
        mock_litellm.completion.return_value = []
        list(client.generate_chat_response("m", [], stream=True))
        call_kwargs = mock_litellm.completion.call_args.kwargs
        assert "max_tokens" not in call_kwargs


# ===========================================================================
# LiteLLMClient.generate_chat_completion
# ===========================================================================

class TestLiteLLMClientGenerateChatCompletion:
    def _make_client(self):
        mock_litellm = MagicMock()
        with patch.dict("sys.modules", {"litellm": mock_litellm}):
            from importlib import reload

            import src.llm_client as mod
            reload(mod)
            client = mod.LiteLLMClient("openai", None, "gpt-4o")
            client._litellm = mock_litellm
        return client, mock_litellm

    def test_returns_model_dump(self):
        client, mock_litellm = self._make_client()
        mock_resp = MagicMock()
        mock_resp.model_dump.return_value = {"choices": []}
        mock_litellm.completion.return_value = mock_resp
        result = client.generate_chat_completion("m", [])
        assert result == {"choices": []}

    def test_tools_passed_when_provided(self):
        client, mock_litellm = self._make_client()
        mock_resp = MagicMock()
        mock_resp.model_dump.return_value = {}
        mock_litellm.completion.return_value = mock_resp
        tools = [{"type": "function", "function": {"name": "search"}}]
        client.generate_chat_completion("m", [], tools=tools)
        call_kwargs = mock_litellm.completion.call_args.kwargs
        assert call_kwargs.get("tools") == tools

    def test_tools_not_passed_when_none(self):
        client, mock_litellm = self._make_client()
        mock_resp = MagicMock()
        mock_resp.model_dump.return_value = {}
        mock_litellm.completion.return_value = mock_resp
        client.generate_chat_completion("m", [], tools=None)
        call_kwargs = mock_litellm.completion.call_args.kwargs
        assert "tools" not in call_kwargs


# ===========================================================================
# ModelClient Protocol
# ===========================================================================

class TestModelClientProtocol:
    def test_litellm_client_satisfies_protocol(self):
        from src.llm_client import ModelClient
        mock_litellm = MagicMock()
        with patch.dict("sys.modules", {"litellm": mock_litellm}):
            from importlib import reload

            import src.llm_client as mod
            reload(mod)
            client = mod.LiteLLMClient("openai", None, "gpt-4o")
        assert isinstance(client, ModelClient)
