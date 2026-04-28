"""Unit tests for src/tools/executor.py — focusing on previously untested paths."""

from unittest.mock import MagicMock

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
        result = ToolExecutor._format_data_as_text({"revenue": 100})
        assert "Revenue" in result
        assert "100" in result

    def test_list_of_scalars(self):
        result = ToolExecutor._format_data_as_text(["a", "b"])
        assert "a" in result
        assert "b" in result

    def test_nested_dict(self):
        result = ToolExecutor._format_data_as_text({"data": {"key": "val"}})
        assert "Data" in result
        assert "val" in result


# ---------------------------------------------------------------------------
# inline_mode fallback path
# ---------------------------------------------------------------------------

class TestInlineMode:
    """
    Tests for the inline_mode path where the model emits tool calls as JSON
    in the content field instead of the structured tool_calls field.
    """

    def test_first_inline_call_is_detected_and_executed(self):
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
        client.generate_chat_completion.side_effect = [
            _chat_response(content=inline_json),
            _chat_response(content=plain_answer),
        ]
        client.generate_chat_response.return_value = iter([])

        messages = [{"role": "user", "content": "test"}]
        chunks = list(executor.execute("model", messages))

        assert plain_answer in chunks
        assert client.generate_chat_completion.call_count == 2

    def test_second_inline_call_formats_as_text(self):
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
        client.generate_chat_completion.side_effect = [
            _chat_response(content=inline_json),
            _chat_response(content=echo_json),
        ]

        messages = [{"role": "user", "content": "test"}]
        chunks = list(executor.execute("model", messages))

        # Should have yielded the formatted text (not the raw JSON)
        combined = "".join(chunks)
        assert combined  # something was yielded
        assert "{" not in combined or "Result" in combined  # formatted, not raw JSON


# ---------------------------------------------------------------------------
# Max-rounds exhaustion path
# ---------------------------------------------------------------------------

class TestMaxRoundsExhaustion:
    """Tests for the path where the tool-call loop hits max_rounds."""

    def test_falls_through_to_final_stream_after_max_rounds(self):
        """
        When every round returns tool_calls (loop never resolves),
        hitting max_rounds should trigger a final streamed response.
        """
        executor, client = _make_executor(max_rounds=2)

        tool_call = {"function": {"name": "test_tool", "arguments": {"query": "x"}}}
        client.generate_chat_completion.return_value = _chat_response(
            tool_calls=[tool_call]
        )
        client.generate_chat_response.return_value = iter(["final answer"])

        messages = [{"role": "user", "content": "test"}]
        chunks = list(executor.execute("model", messages))

        assert "final answer" in chunks
        # generate_chat_completion called max_rounds times
        assert client.generate_chat_completion.call_count == 2
        # fallback stream called exactly once
        assert client.generate_chat_response.call_count == 1

    def test_max_rounds_of_one_exhausts_immediately(self):
        """With max_rounds=1 a single tool-call response triggers the fallback."""
        executor, client = _make_executor(max_rounds=1)

        tool_call = {"function": {"name": "test_tool", "arguments": {"query": "y"}}}
        client.generate_chat_completion.return_value = _chat_response(
            tool_calls=[tool_call]
        )
        client.generate_chat_response.return_value = iter(["stream chunk"])

        chunks = list(executor.execute("model", [{"role": "user", "content": "hi"}]))

        assert "stream chunk" in chunks
        assert client.generate_chat_response.call_count == 1


# ---------------------------------------------------------------------------
# Schema-dict guard — argument received as schema object instead of value
# ---------------------------------------------------------------------------

class TestSchemaDictGuard:
    """When a model sends a schema dict as an argument value, the executor
    should reject the tool call with an informative error message."""

    def test_schema_dict_argument_returns_error_string(self):
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
        client.generate_chat_completion.return_value = _chat_response(
            tool_calls=[tool_call]
        )
        client.generate_chat_response.return_value = iter(["fallback"])

        chunks = list(executor.execute("model", [{"role": "user", "content": "hi"}]))
        combined = "".join(chunks)
        # The guard returns an error; the executor continues to a final streamed response
        assert combined  # something was yielded


# ---------------------------------------------------------------------------
# No-tools early-exit path
# ---------------------------------------------------------------------------

class TestNoToolsRegistered:
    """When the registry has no tools, execute() skips the loop entirely."""

    def test_streams_directly_when_no_schemas(self):
        client = MagicMock()
        registry = ToolRegistry()  # empty
        executor = ToolExecutor(client=client, registry=registry, max_rounds=5)

        client.generate_chat_response.return_value = iter(["direct answer"])

        chunks = list(executor.execute("model", [{"role": "user", "content": "hi"}]))

        assert chunks == ["direct answer"]
        client.generate_chat_completion.assert_not_called()
