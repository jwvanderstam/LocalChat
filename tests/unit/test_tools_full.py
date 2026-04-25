"""Tests for ToolRegistry, ToolExecutor, and built-in tools."""

import ast
import json
from unittest.mock import MagicMock, patch

import pytest

from src.tools.builtin import _ast_eval

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
# PluginLoader edge cases
# ---------------------------------------------------------------------------

class TestPluginLoaderEdgeCases:
    """Edge cases for PluginLoader discovered from real plugin files."""

    def _make_loader(self):
        from src.tools.plugin_loader import PluginLoader
        from src.tools.registry import ToolRegistry

        registry = ToolRegistry()
        return PluginLoader(registry=registry), registry

    def test_load_all_nonexistent_dir_returns_zero(self, tmp_path):
        loader, _ = self._make_loader()
        assert loader.load_all(tmp_path / "does_not_exist") == 0

    def test_underscore_prefixed_files_are_skipped(self, tmp_path):
        (tmp_path / "_private.py").write_text("X = 1\n")
        loader, _ = self._make_loader()
        assert loader.load_all(tmp_path) == 0

    def test_syntax_error_plugin_recorded_with_error(self, tmp_path):
        (tmp_path / "bad_plugin.py").write_text("def missing_colon()\n    pass\n")
        loader, _ = self._make_loader()
        loader.load_all(tmp_path)
        plugins = loader.list_plugins()
        assert len(plugins) == 1
        assert plugins[0]["error"] is not None

    def test_plugin_defining_no_tools_loads_with_empty_tool_list(self, tmp_path):
        (tmp_path / "empty_plugin.py").write_text("X = 1\n")
        loader, _ = self._make_loader()
        count = loader.load_all(tmp_path)
        assert count == 1
        assert loader.list_plugins()[0]["tools"] == []

    def test_plugin_meta_is_read(self, tmp_path):
        (tmp_path / "meta_plugin.py").write_text(
            'PLUGIN_META = {"name": "Test Plugin", "version": "2.0"}\nX = 1\n'
        )
        loader, _ = self._make_loader()
        loader.load_all(tmp_path)
        p = loader.list_plugins()[0]
        assert p["meta"]["name"] == "Test Plugin"
        assert p["meta"]["version"] == "2.0"

    def test_unload_removes_plugin_record(self, tmp_path):
        (tmp_path / "removable.py").write_text("X = 1\n")
        loader, _ = self._make_loader()
        loader.load_all(tmp_path)
        assert loader.loaded_count == 1
        assert loader.unload("removable") is True
        assert loader.loaded_count == 0

    def test_unload_unknown_plugin_returns_false(self):
        loader, _ = self._make_loader()
        assert loader.unload("nonexistent") is False

    def test_reload_unknown_plugin_raises_key_error(self):
        loader, _ = self._make_loader()
        with pytest.raises(KeyError):
            loader.reload("unknown_plugin")

    def test_reload_is_idempotent(self, tmp_path):
        (tmp_path / "stable.py").write_text("X = 1\n")
        loader, _ = self._make_loader()
        loader.load_all(tmp_path)
        loader.reload("stable")
        loader.reload("stable")
        assert loader.loaded_count == 1

    def test_list_plugins_returns_expected_keys(self, tmp_path):
        (tmp_path / "listed.py").write_text("X = 1\n")
        loader, _ = self._make_loader()
        loader.load_all(tmp_path)
        p = loader.list_plugins()[0]
        for key in ("name", "path", "tools", "tool_count", "meta", "error"):
            assert key in p


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

    def test_calculate_negative_number(self):
        import src.tools.builtin  # noqa: F401
        from src.tools.registry import tool_registry
        result = tool_registry.execute("calculate", {"expression": "-5"})
        assert "-5" in result

    def test_calculate_unary_plus(self):
        import src.tools.builtin  # noqa: F401
        from src.tools.registry import tool_registry
        result = tool_registry.execute("calculate", {"expression": "2 + -3"})
        assert "-1" in result


# ---------------------------------------------------------------------------
# _ast_eval — direct tests for error branches
# ---------------------------------------------------------------------------

class TestAstEvalEdgeCases:
    def test_unsupported_unary_operator_raises(self):
        node = ast.UnaryOp(op=ast.Invert(), operand=ast.Constant(value=5))
        with pytest.raises(ValueError, match="Unsupported operator"):
            _ast_eval(node)

    def test_unsupported_binop_operator_raises(self):
        node = ast.BinOp(
            left=ast.Constant(value=4),
            op=ast.LShift(),
            right=ast.Constant(value=1),
        )
        with pytest.raises(ValueError, match="Unsupported operator"):
            _ast_eval(node)

    def test_unsupported_expression_type_raises(self):
        node = ast.Name(id="x", ctx=ast.Load())
        with pytest.raises(ValueError, match="Unsupported expression"):
            _ast_eval(node)

    def test_unsupported_literal_type_raises(self):
        node = ast.Constant(value="not_a_number")
        with pytest.raises(ValueError, match="Unsupported literal"):
            _ast_eval(node)


# ---------------------------------------------------------------------------
# tools/__init__ imports
# ---------------------------------------------------------------------------

class TestToolsPackageInit:
    def test_tools_init_exports_registry(self):
        from src.tools import ToolExecutor, ToolRegistry, tool_registry
        assert tool_registry is not None
        assert ToolRegistry is not None
        assert ToolExecutor is not None
