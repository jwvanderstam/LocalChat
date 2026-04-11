"""
Tool Calling Module
===================

Registry-based tool calling system for LLM function calling via Ollama.

Provides a central ``ToolRegistry`` for declarative tool definitions, a
``ToolExecutor`` that manages the multi-turn tool-call loop, and a set of
useful built-in tools (document search, datetime, calculator).

Usage:
    >>> from src.tools import tool_registry, ToolExecutor
    >>> executor = ToolExecutor(ollama_client, tool_registry)
    >>> for chunk in executor.execute(model, messages):
    ...     print(chunk, end="")

"""

# Import built-in tools so their @register decorators run at import time.
from . import builtin as _builtin  # noqa: F401
from .executor import ToolExecutor
from .plugin_loader import PluginLoader
from .registry import ToolRegistry, ToolSpec, tool_registry

# Module-level singleton — call plugin_loader.load_all(plugins_dir) at startup.
plugin_loader = PluginLoader(registry=tool_registry)

__all__ = [
    "tool_registry",
    "ToolRegistry",
    "ToolSpec",
    "ToolExecutor",
    "PluginLoader",
    "plugin_loader",
]
