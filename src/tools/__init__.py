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

Author: LocalChat Team
"""

from .registry import tool_registry, ToolRegistry, ToolSpec
from .executor import ToolExecutor

# Import built-in tools so their @register decorators run at import time.
from . import builtin as _builtin  # noqa: F401

__all__ = ["tool_registry", "ToolRegistry", "ToolSpec", "ToolExecutor"]
