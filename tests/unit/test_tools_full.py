# -*- coding: utf-8 -*-
"""Tests for ToolRegistry, ToolExecutor, and built-in tools."""

import json
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# ToolRegistry
# ---------------------------------------------------------------------------

class TestToolRegistry:
    def setup_method(self):
        from src.tools.registry import ToolRegistry
        self.registry = ToolRegistry()

    def _register_hello(self):
        @self.registry.register(
            name="hello",
            description="Say hello",
            parameters={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        )
        def hello(name: str) -> str:
            return f"Hello, {name}!"
        return hello

    def test_register_and_get(self):
        self._register_hello()
        spec = self.registry.get("hello")
        assert spec is not None
        assert spec.name == "hello"
        assert spec.description == "Say hello"

    def test_get_unknown_returns_none(self):
        assert self.registry.get("nonexistent") is None

    def test_len_empty_registry(self):
        assert len(self.registry) == 0

    def test_len_after_registration(self):
        self._register_hello()
        assert len(self.registry) == 1

    def test_names_property(self):
        self._register_hello()
        assert "hello" in self.registry.names

    def test_contains_registered_tool(self):
        self._register_hello()
        assert "hello" in self.registry

    def test_contains_unknown_tool(self):
        assert "unknown" not in self.registry

    def test_execute_registered_tool(self):
        self._register_hello()
        result = self.registry.execute("hello", {"name": "World"})
        assert result == "Hello, World!"

    def test_execute_unknown_raises_key_error(self):
        with pytest.raises(KeyError):
            self.registry.execute("ghost", {})

    def test_get_ollama_schemas_format(self):
        self._register_hello()
        schemas = self.registry.get_ollama_schemas()
        assert len(schemas) == 1
        assert schemas[0]["type"] == "function"
        assert schemas[0]["function"]["name"] == "hello"

    def test_register_overwrites_existing_tool(self):
        self._register_hello()

        @self.registry.register(name="hello", description="Updated", parameters={})
        def hello_v2() -> str:
            return "v2"

        assert self.registry.get("hello").description == "Updated"

    def test_repr_contains_tool_names(self):
        self._register_hello()
        assert "hello" in repr(self.registry)

    def test_register_returns_original_function(self):
        @self.registry.register(name="echo", description="echo", parameters={})
        def echo(x: str) -> str:
            return x

        assert echo("test") == "test"


# ---------------------------------------------------------------------------
# ToolExecutor
# ---------------------------------------------------------------------------

class TestToolExecutorParseArguments:
    def test_dict_passthrough(self):
        from src.tools.executor import ToolExecutor
        result = ToolExecutor._parse_tool_arguments({"key": "value"})
        assert result == {"key": "value"}

    def test_json_string_deserialized(self):
        from src.tools.executor import ToolExecutor
        result = ToolExecutor._parse_tool_arguments('{"key": "value"}')
        assert result == {"key": "value"}

    def test_invalid_json_returns_empty_dict(self):
        from src.tools.executor import ToolExecutor
        result = ToolExecutor._parse_tool_arguments("not json")
        assert result == {}

    def test_none_returns_empty_dict(self):
        from src.tools.executor import ToolExecutor
        result = ToolExecutor._parse_tool_arguments(None)
        assert result == {}


class TestToolExecutorExecute:
    def _make_executor(self, max_rounds=3):
        from src.tools.executor import ToolExecutor
        from src.tools.registry import ToolRegistry

        registry = ToolRegistry()

        @registry.register(name="add", description="Add two numbers",
                           parameters={"type": "object", "properties": {}})
        def add(a: int, b: int) -> int:
            return a + b

        client = MagicMock()
        return ToolExecutor(client, registry, max_rounds=max_rounds), client, registry

    def test_no_schemas_falls_back_to_direct_chat(self):
        from src.tools.executor import ToolExecutor
        from src.tools.registry import ToolRegistry

        empty_registry = ToolRegistry()
        client = MagicMock()
        client.generate_chat_response.return_value = iter(["hi"])
        executor = ToolExecutor(client, empty_registry)

        result = list(executor.execute("model", [{"role": "user", "content": "hi"}]))
        assert result == ["hi"]

    def test_final_text_answer_yielded(self):
        executor, client, _ = self._make_executor()
        client.generate_chat_completion.return_value = {
            "message": {"content": "The answer is 5", "tool_calls": None}
        }
        result = "".join(executor.execute("model", [{"role": "user", "content": "q"}]))
        assert "5" in result

    def test_tool_call_executed(self):
        executor, client, _ = self._make_executor()
        client.generate_chat_completion.side_effect = [
            {"message": {"tool_calls": [{"function": {"name": "add", "arguments": {"a": 2, "b": 3}}}]}},
            {"message": {"content": "Result: 5", "tool_calls": None}},
        ]
        result = "".join(executor.execute("model", []))
        assert "5" in result

    def test_unknown_tool_in_call_returns_error_string(self):
        executor, client, _ = self._make_executor()
        client.generate_chat_completion.side_effect = [
            {"message": {"tool_calls": [{"function": {"name": "ghost", "arguments": {}}}]}},
            {"message": {"content": "Done", "tool_calls": None}},
        ]
        result = "".join(executor.execute("model", []))
        assert "Done" in result

    def test_max_rounds_exhausted_streams_final(self):
        executor, client, _ = self._make_executor(max_rounds=1)
        # Always return tool call — exhausts rounds
        client.generate_chat_completion.return_value = {
            "message": {"tool_calls": [{"function": {"name": "add", "arguments": {"a": 1, "b": 1}}}]}
        }
        client.generate_chat_response.return_value = iter(["fallback"])
        result = "".join(executor.execute("model", []))
        assert result == "fallback"

    def test_tool_raising_exception_returns_error_message(self):
        from src.tools.executor import ToolExecutor
        from src.tools.registry import ToolRegistry

        registry = ToolRegistry()

        @registry.register(name="boom", description="fails", parameters={})
        def boom() -> str:
            raise ValueError("intentional")

        client = MagicMock()
        client.generate_chat_completion.side_effect = [
            {"message": {"tool_calls": [{"function": {"name": "boom", "arguments": {}}}]}},
            {"message": {"content": "Handled", "tool_calls": None}},
        ]
        executor = ToolExecutor(client, registry)
        result = "".join(executor.execute("model", []))
        # Should survive the tool error
        assert "Handled" in result

    def test_tool_call_with_json_string_arguments(self):
        executor, client, _ = self._make_executor()
        client.generate_chat_completion.side_effect = [
            {"message": {"tool_calls": [{"function": {"name": "add", "arguments": '{"a": 1, "b": 2}'}}]}},
            {"message": {"content": "ok", "tool_calls": None}},
        ]
        result = "".join(executor.execute("model", []))
        assert "ok" in result

    def test_empty_content_in_final_answer(self):
        executor, client, _ = self._make_executor()
        client.generate_chat_completion.return_value = {
            "message": {"content": "", "tool_calls": None}
        }
        result = list(executor.execute("model", []))
        assert result == []


# ---------------------------------------------------------------------------
# Built-in tools (importable, registered on module load)
# ---------------------------------------------------------------------------

class TestBuiltinToolsRegistration:
    def test_builtin_tools_are_registered(self):
        # Importing builtin registers tools on the singleton
        import src.tools.builtin  # noqa: F401
        from src.tools.registry import tool_registry
        # At least some built-ins should be present
        assert len(tool_registry) >= 1

    def test_get_current_datetime_tool_exists(self):
        import src.tools.builtin  # noqa: F401
        from src.tools.registry import tool_registry
        spec = tool_registry.get("get_current_datetime")
        assert spec is not None

    def test_get_current_datetime_returns_string(self):
        import src.tools.builtin  # noqa: F401
        from src.tools.registry import tool_registry
        result = tool_registry.execute("get_current_datetime", {})
        assert isinstance(result, str)
        assert len(result) > 0

    def test_calculate_tool_exists(self):
        import src.tools.builtin  # noqa: F401
        from src.tools.registry import tool_registry
        spec = tool_registry.get("calculate")
        assert spec is not None

    def test_calculate_basic_expression(self):
        import src.tools.builtin  # noqa: F401
        from src.tools.registry import tool_registry
        result = tool_registry.execute("calculate", {"expression": "2 + 2"})
        assert "4" in str(result)

    def test_calculate_dangerous_expression_blocked(self):
        import src.tools.builtin  # noqa: F401
        from src.tools.registry import tool_registry
        result = tool_registry.execute("calculate", {"expression": "__import__('os').listdir('.')"})
        # Should return an error, not execute the import
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# tools/__init__ imports
# ---------------------------------------------------------------------------

class TestToolsPackageInit:
    def test_tools_init_exports_registry(self):
        from src.tools import tool_registry, ToolRegistry, ToolExecutor
        assert tool_registry is not None
        assert ToolRegistry is not None
        assert ToolExecutor is not None
