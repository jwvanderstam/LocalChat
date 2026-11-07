"""
Tests for src/llm_client.py

Covers:
  - is_refusal: each pattern matches, long text exempt, empty string, no match
  - OpenAICompatibleClient, against httpx.MockTransport: the request it sends (URL, bearer
    token, OpenAI body), a server-sent stream parsed to its content, a non-streamed answer,
    an error status raised, and the tool-call completion returned as the endpoint sent it
  - ModelClient Protocol: OpenAICompatibleClient satisfies it at runtime
"""

from __future__ import annotations

import json

import httpx
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
# OpenAICompatibleClient
# ===========================================================================

BASE = "https://cloud.example/v1"
MESSAGES = [{"role": "user", "content": "hi"}]


def _delta(content):
    return {"choices": [{"index": 0, "delta": {"content": content}}]}


def _sse(*events):
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"


def _stream(*events):
    return lambda request: httpx.Response(200, text=_sse(*events))


def _client(handler, api_key=None):
    from src.llm_client import OpenAICompatibleClient

    seen = []

    def record(request):
        seen.append(request)
        return handler(request)

    client = OpenAICompatibleClient(BASE, api_key, "m", timeout=5, transport=httpx.MockTransport(record))
    return client, seen


class TestTheRequest:
    def test_it_posts_to_chat_completions_under_the_base_url(self):
        client, seen = _client(_stream())
        list(client.generate_chat_response("m", MESSAGES))
        assert (seen[0].method, str(seen[0].url)) == ("POST", "https://cloud.example/v1/chat/completions")

    def test_the_api_key_is_sent_as_a_bearer_token(self):
        client, seen = _client(_stream(), api_key="sk-test")
        list(client.generate_chat_response("m", MESSAGES))
        assert seen[0].headers["authorization"] == "Bearer sk-test"

    def test_without_an_api_key_no_authorization_header_is_sent(self):
        client, seen = _client(_stream())
        list(client.generate_chat_response("m", MESSAGES))
        assert "authorization" not in seen[0].headers

    def test_a_stream_sends_the_openai_body_and_asks_for_usage(self):
        client, seen = _client(_stream())
        list(client.generate_chat_response("m", MESSAGES, temperature=0.2, max_tokens=512))
        assert json.loads(seen[0].content) == {
            "model": "m", "messages": MESSAGES, "stream": True, "temperature": 0.2,
            "max_tokens": 512, "stream_options": {"include_usage": True},
        }

    def test_max_tokens_is_left_out_when_none(self):
        client, seen = _client(_stream())
        list(client.generate_chat_response("m", MESSAGES))
        assert "max_tokens" not in json.loads(seen[0].content)


class TestStreaming:
    def test_content_chunks_are_yielded_in_order(self):
        client, _ = _client(_stream(_delta("Hello"), _delta(" world")))
        assert list(client.generate_chat_response("m", MESSAGES)) == ["Hello", " world"]

    def test_empty_missing_and_choiceless_chunks_are_skipped(self):
        client, _ = _client(_stream(_delta(""), _delta(None), {"choices": []}, _delta("real content")))
        assert list(client.generate_chat_response("m", MESSAGES)) == ["real content"]

    def test_nothing_after_done_is_read(self):
        text = _sse(_delta("Hello")) + f"data: {json.dumps(_delta('late'))}\n\n"
        client, _ = _client(lambda request: httpx.Response(200, text=text))
        assert list(client.generate_chat_response("m", MESSAGES)) == ["Hello"]

    def test_an_error_status_raises(self):
        client, _ = _client(lambda request: httpx.Response(500, text="upstream down"))
        with pytest.raises(httpx.HTTPStatusError):
            list(client.generate_chat_response("m", MESSAGES))


class TestNonStreaming:
    def test_it_yields_the_message_content_once_and_asks_for_no_stream(self):
        client, seen = _client(lambda request: httpx.Response(
            200, json={"choices": [{"message": {"content": "Full answer here"}}]}))
        assert list(client.generate_chat_response("m", MESSAGES, stream=False)) == ["Full answer here"]
        body = json.loads(seen[0].content)
        assert (body["stream"], "stream_options" in body) == (False, False)

    def test_no_choices_yields_an_empty_string(self):
        client, _ = _client(lambda request: httpx.Response(200, json={"choices": []}))
        assert list(client.generate_chat_response("m", MESSAGES, stream=False)) == [""]


class TestChatCompletion:
    def test_it_returns_the_response_as_the_endpoint_sent_it(self):
        data = {"choices": [{"message": {"tool_calls": [{"id": "c1", "function": {"name": "search"}}]}}]}
        client, _ = _client(lambda request: httpx.Response(200, json=data))
        assert client.generate_chat_completion("m", MESSAGES) == data

    def test_tools_are_sent_when_given(self):
        tools = [{"type": "function", "function": {"name": "search"}}]
        client, seen = _client(lambda request: httpx.Response(200, json={}))
        client.generate_chat_completion("m", MESSAGES, tools=tools)
        assert json.loads(seen[0].content)["tools"] == tools

    def test_tools_are_left_out_when_none(self):
        client, seen = _client(lambda request: httpx.Response(200, json={}))
        client.generate_chat_completion("m", MESSAGES, tools=None)
        assert "tools" not in json.loads(seen[0].content)


# ===========================================================================
# ModelClient Protocol
# ===========================================================================

class TestModelClientProtocol:
    def test_the_client_satisfies_the_protocol(self):
        from src.llm_client import ModelClient
        client, _ = _client(_stream())
        assert isinstance(client, ModelClient)
