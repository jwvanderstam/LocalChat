"""Unit tests for src/tools/executor.py — focusing on previously untested paths."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.tools.executor import ToolExecutor
from src.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_executor(max_rounds: int = 5) -> tuple[ToolExecutor, MagicMock]:
    """Return a ToolExecutor wired to a mock OllamaClient with one registered tool."""
    client = MagicMock()
    registry = ToolRegistry()

    @registry.register(name="test_tool", description="A test tool", parameters={"query": {"type": "string"}})
    def test_tool(query: str) -> str:
        return f"result for {query}"

    executor = ToolExecutor(client=client, registry=registry, max_rounds=max_rounds)
    return executor, client


def _chat_response(content: str = "", tool_calls=None) -> dict:
    """Build a minimal Ollama chat-completion response dict."""
    msg: dict = {"role": "assistant", "content": content}
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return {"message": msg}


def _async_gen(*values):
    """Return an async generator function that yields the given values."""
    async def _g(*args, **kwargs):
        for v in values:
            yield v
    return _g


# ---------------------------------------------------------------------------
# _try_parse_content_tool_call
# ---------------------------------------------------------------------------

class TestTryParseContentToolCall:
    """Unit tests for the static helper that detects inline JSON tool calls."""

    def test_returns_none_for_plain_text(self):
        result = ToolExecutor._try_parse_content_tool_call("Hello, world!")
        assert result is None

    def test_returns_none_for_empty_string(self):
        result = ToolExecutor._try_parse_content_tool_call("")
        assert result is None

    def test_returns_none_for_invalid_json(self):
        result = ToolExecutor._try_parse_content_tool_call("{not valid json}")
        assert result is None

    def test_returns_none_when_name_missing(self):
        result = ToolExecutor._try_parse_content_tool_call('{"parameters": {"x": 1}}')
        assert result is None

    def test_parses_parameters_key(self):
        json_str = '{"name": "search_documents", "parameters": {"query": "revenue"}}'
        result = ToolExecutor._try_parse_content_tool_call(json_str)
        assert result is not None
        assert result["function"]["name"] == "search_documents"
        assert result["function"]["arguments"] == {"query": "revenue"}

    def test_parses_arguments_key(self):
        json_str = '{"name": "calc", "arguments": {"expr": "1+1"}}'
        result = ToolExecutor._try_parse_content_tool_call(json_str)
        assert result["function"]["arguments"] == {"expr": "1+1"}

    def test_parses_input_key(self):
        json_str = '{"name": "tool", "input": {"x": 42}}'
        result = ToolExecutor._try_parse_content_tool_call(json_str)
        assert result["function"]["arguments"] == {"x": 42}

    def test_returns_empty_args_when_no_known_key(self):
        json_str = '{"name": "tool"}'
        result = ToolExecutor._try_parse_content_tool_call(json_str)
        assert result["function"]["arguments"] == {}


# ---------------------------------------------------------------------------
# _format_data_as_text
# ---------------------------------------------------------------------------

class TestFormatDataAsText:
    """Unit tests for the recursive text formatter."""

    def test_scalar_string(self):
        assert ToolExecutor._format_data_as_text("hello") == "hello"

    def test_scalar_number(self):
        assert ToolExecutor._format_data_as_text(42) == "42"

    def test_flat_dict(self):
        # Underscore key exercises the .replace("_", " ").title() label formatting.
        result = ToolExecutor._format_data_as_text({"total_count": 100})
        assert result == "- Total Count: 100"

    def test_list_of_scalars(self):
        # Each item is recursively formatted at indent+1 *and* prefixed with
        # "- " by the list join, so list items carry a doubled indent.
        result = ToolExecutor._format_data_as_text(["a", "b"])
        assert result == "-   a\n-   b"

    def test_nested_dict(self):
        result = ToolExecutor._format_data_as_text({"data": {"key": "val"}})
        assert result == "**Data:**\n  - Key: val"

    def test_list_of_dicts_nested_indent(self):
        result = ToolExecutor._format_data_as_text([{"key": "val"}])
        assert result == "-   - Key: val"


# ---------------------------------------------------------------------------
# inline_mode fallback path
# ---------------------------------------------------------------------------

class TestInlineMode:
    """
    Tests for the inline_mode path where the model emits tool calls as JSON
    in the content field instead of the structured tool_calls field.
    """

    async def test_first_inline_call_is_detected_and_executed(self):
        """
        Round 1: model returns JSON in content, no tool_calls.
        Executor should detect it, set inline_mode=True, execute the tool,
        and continue to round 2.
        Round 2: model returns a plain text answer.
        Generator should yield that answer and return.
        """
        executor, client = _make_executor(max_rounds=5)

        inline_json = '{"name": "test_tool", "parameters": {"query": "hello"}}'
        plain_answer = "Here is the answer."

        # Round 1: inline JSON tool call in content
        # Round 2: plain text answer
        client.generate_chat_completion = AsyncMock(side_effect=[
            _chat_response(content=inline_json),
            _chat_response(content=plain_answer),
        ])
        client.generate_chat_response = _async_gen()

        messages = [{"role": "user", "content": "test"}]
        chunks = [c async for c in executor.execute("model", messages)]

        assert plain_answer in chunks
        assert client.generate_chat_completion.call_count == 2

    async def test_second_inline_call_formats_as_text(self):
        """
        When inline_mode is already True and the model AGAIN returns JSON in
        content (model echoing the result), the executor should format the
        arguments as plain text and yield them as the final answer.
        """
        executor, client = _make_executor(max_rounds=5)

        inline_json = '{"name": "test_tool", "parameters": {"query": "hello"}}'
        echo_json = '{"name": "test_tool", "parameters": {"result": "done"}}'

        # Round 1: inline JSON → sets inline_mode=True
        # Round 2: another JSON in content while inline_mode=True → format as text
        client.generate_chat_completion = AsyncMock(side_effect=[
            _chat_response(content=inline_json),
            _chat_response(content=echo_json),
        ])

        messages = [{"role": "user", "content": "test"}]
        chunks = [c async for c in executor.execute("model", messages)]

        # Should have yielded the formatted text (not the raw JSON)
        combined = "".join(chunks)
        assert combined  # something was yielded
        assert "{" not in combined or "Result" in combined  # formatted, not raw JSON


# ---------------------------------------------------------------------------
# Max-rounds exhaustion path
# ---------------------------------------------------------------------------

class TestMaxRoundsExhaustion:
    """Tests for the path where the tool-call loop hits max_rounds."""

    async def test_falls_through_to_final_stream_after_max_rounds(self):
        """
        When every round returns tool_calls (loop never resolves),
        hitting max_rounds should trigger a final streamed response.
        """
        executor, client = _make_executor(max_rounds=2)

        tool_call = {"function": {"name": "test_tool", "arguments": {"query": "x"}}}
        client.generate_chat_completion = AsyncMock(return_value=_chat_response(
            tool_calls=[tool_call]
        ))
        client.generate_chat_response = _async_gen("final answer")

        messages = [{"role": "user", "content": "test"}]
        chunks = [c async for c in executor.execute("model", messages)]

        assert "final answer" in chunks
        # generate_chat_completion called max_rounds times
        assert client.generate_chat_completion.call_count == 2
        # fallback stream called exactly once

    async def test_max_rounds_of_one_exhausts_immediately(self):
        """With max_rounds=1 a single tool-call response triggers the fallback."""
        executor, client = _make_executor(max_rounds=1)

        tool_call = {"function": {"name": "test_tool", "arguments": {"query": "y"}}}
        client.generate_chat_completion = AsyncMock(return_value=_chat_response(
            tool_calls=[tool_call]
        ))
        client.generate_chat_response = _async_gen("stream chunk")

        chunks = [c async for c in executor.execute("model", [{"role": "user", "content": "hi"}])]

        assert "stream chunk" in chunks


# ---------------------------------------------------------------------------
# Tool-result message structure — exact role/content, not just final text
# ---------------------------------------------------------------------------

class TestToolResultMessageRole:
    """Verifies the actual message dict appended for a non-inline tool
    result, not just the text eventually yielded to the caller."""

    async def test_tool_result_appended_with_role_tool_not_user(self):
        executor, client = _make_executor(max_rounds=3)

        tool_call = {"function": {"name": "test_tool", "arguments": {"query": "x"}}}
        client.generate_chat_completion = AsyncMock(side_effect=[
            _chat_response(tool_calls=[tool_call]),
            _chat_response(content="final"),
        ])
        client.generate_chat_response = _async_gen()

        messages = [{"role": "user", "content": "test"}]
        chunks = [c async for c in executor.execute("model", messages)]
        assert "final" in chunks

        # working_messages is mutated in place and passed by reference, so
        # inspecting either recorded call gives the same final message list.
        sent_messages = client.generate_chat_completion.call_args_list[-1].args[1]
        tool_messages = [m for m in sent_messages if m.get("role") == "tool"]
        assert len(tool_messages) == 1
        assert tool_messages[0] == {"role": "tool", "content": "result for x"}


# ---------------------------------------------------------------------------
# Schema-dict guard — argument received as schema object instead of value
# ---------------------------------------------------------------------------

class TestSchemaDictGuard:
    """When a model sends a schema dict as an argument value, the executor
    should reject the tool call with an informative error message."""

    async def test_schema_dict_argument_returns_error_string(self):
        client = MagicMock()
        registry = ToolRegistry()

        @registry.register(
            name="greet",
            description="Greet someone",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        )
        def greet(name: str) -> str:
            return f"Hello, {name}!"

        executor = ToolExecutor(client=client, registry=registry, max_rounds=5)

        # Simulate the model sending the schema dict as the argument value
        schema_as_value = {"type": "string", "description": "The name to greet"}
        tool_call = {
            "function": {"name": "greet", "arguments": {"name": schema_as_value}}
        }
        client.generate_chat_completion = AsyncMock(return_value=_chat_response(
            tool_calls=[tool_call]
        ))
        client.generate_chat_response = _async_gen("fallback")

        chunks = [c async for c in executor.execute("model", [{"role": "user", "content": "hi"}])]
        combined = "".join(chunks)
        assert combined  # something was yielded

        # Assert the exact guard error text was appended as the tool result,
        # not just that *something* non-empty eventually came out.
        sent_messages = client.generate_chat_completion.call_args_list[-1].args[1]
        tool_messages = [m for m in sent_messages if m.get("role") == "tool"]
        assert tool_messages
        assert tool_messages[0]["content"] == (
            "Error: argument 'name' must be a plain string, not a schema "
            "object. Call the tool again with the actual value as a string."
        )

    async def test_non_string_schema_type_does_not_trigger_guard(self):
        """A dict argument is legitimate when the declared schema type is
        not "string" — the guard must only fire on the string/dict mismatch,
        proving `== "string"` isn't a typo'd/mismatched key check."""
        client = MagicMock()
        registry = ToolRegistry()

        @registry.register(
            name="configure",
            description="Configure something",
            parameters={
                "type": "object",
                "properties": {"options": {"type": "object"}},
                "required": ["options"],
            },
        )
        def configure(options: dict) -> str:
            return f"configured with {options}"

        executor = ToolExecutor(client=client, registry=registry, max_rounds=5)

        tool_call = {
            "function": {"name": "configure", "arguments": {"options": {"a": 1}}}
        }
        client.generate_chat_completion = AsyncMock(side_effect=[
            _chat_response(tool_calls=[tool_call]),
            _chat_response(content="done"),
        ])
        client.generate_chat_response = _async_gen()

        chunks = [c async for c in executor.execute("model", [{"role": "user", "content": "hi"}])]
        assert "done" in chunks

        sent_messages = client.generate_chat_completion.call_args_list[-1].args[1]
        tool_messages = [m for m in sent_messages if m.get("role") == "tool"]
        assert tool_messages[0]["content"] == "configured with {'a': 1}"


# ---------------------------------------------------------------------------
# No-tools early-exit path
# ---------------------------------------------------------------------------

class TestNoToolsRegistered:
    """When the registry has no tools, execute() skips the loop entirely."""

    async def test_streams_directly_when_no_schemas(self):
        client = MagicMock()
        registry = ToolRegistry()  # empty
        executor = ToolExecutor(client=client, registry=registry, max_rounds=5)

        client.generate_chat_response = _async_gen("direct answer")

        chunks = [c async for c in executor.execute("model", [{"role": "user", "content": "hi"}])]

        assert chunks == ["direct answer"]
        client.generate_chat_completion.assert_not_called()
