"""
Tool Registry
=============

Central registry that stores tool specifications and their callable handlers.
Tools are registered via the ``@tool_registry.register`` decorator and can
be looked up / executed by name at runtime.

Example:
    >>> @tool_registry.register(
    ...     name="greet",
    ...     description="Return a greeting.",
    ...     parameters={
    ...         "type": "object",
    ...         "properties": {"name": {"type": "string", "description": "Who to greet"}},
    ...         "required": ["name"],
    ...     },
    ... )
    ... def greet(name: str) -> str:
    ...     return f"Hello, {name}!"

Author: LocalChat Team
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from ..utils.logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolSpec:
    """Immutable specification for a registered tool."""

    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Callable[..., Any]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class ToolRegistry:
    """
    Central registry for tool definitions and their handlers.

    Attributes:
        names: Read-only list of registered tool names.
    """

    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}

    # -- registration -------------------------------------------------------

    def register(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """
        Decorator that registers a function as a tool.

        Args:
            name: Unique tool name (used in Ollama ``tool_calls``).
            description: Human-readable description shown to the model.
            parameters: JSON-Schema object describing accepted arguments.

        Returns:
            The original function, unmodified.
        """

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            if name in self._tools:
                logger.warning(f"Overwriting existing tool: {name}")
            self._tools[name] = ToolSpec(
                name=name,
                description=description,
                parameters=parameters,
                handler=func,
            )
            logger.debug(f"Registered tool: {name}")
            return func

        return decorator

    # -- look-up / execution ------------------------------------------------

    def get(self, name: str) -> Optional[ToolSpec]:
        """Return the ``ToolSpec`` for *name*, or ``None``."""
        return self._tools.get(name)

    def execute(self, name: str, arguments: Dict[str, Any]) -> Any:
        """
        Execute a tool by name.

        Args:
            name: Registered tool name.
            arguments: Keyword arguments forwarded to the handler.

        Returns:
            Whatever the handler returns.

        Raises:
            KeyError: If *name* is not registered.
        """
        spec = self._tools.get(name)
        if spec is None:
            raise KeyError(f"Unknown tool: {name}")
        return spec.handler(**arguments)

    # -- Ollama schema export -----------------------------------------------

    def get_ollama_schemas(self) -> List[Dict[str, Any]]:
        """Return all tool definitions in the Ollama ``tools`` format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
            for spec in self._tools.values()
        ]

    # -- convenience --------------------------------------------------------

    @property
    def names(self) -> List[str]:
        """List of registered tool names."""
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __repr__(self) -> str:
        return f"ToolRegistry({self.names})"


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

tool_registry = ToolRegistry()
