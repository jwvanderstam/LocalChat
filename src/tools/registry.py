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

"""

from __future__ import annotations

import inspect
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
    parameters: dict[str, Any]
    handler: Callable[..., Any]
    source: str = "builtin"


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
        self._tools: dict[str, ToolSpec] = {}

    # -- registration -------------------------------------------------------

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        source: str = "builtin",
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """
        Decorator that registers a function as a tool.

        Args:
            name: Unique tool name (used in Ollama ``tool_calls``).
            description: Human-readable description shown to the model.
            parameters: JSON-Schema object describing accepted arguments.
            source: Origin label — ``"builtin"`` or the plugin stem name.

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
                source=source,
            )
            logger.debug(f"Registered tool: {name} (source={source!r})")
            return func

        return decorator

    # -- look-up / execution ------------------------------------------------

    def get(self, name: str) -> ToolSpec | None:
        """Return the ``ToolSpec`` for *name*, or ``None``."""
        return self._tools.get(name)

    def unregister(self, name: str) -> bool:
        """
        Remove a tool from the registry by name.

        Args:
            name: Registered tool name to remove.

        Returns:
            ``True`` if the tool existed and was removed, ``False`` otherwise.
        """
        if name in self._tools:
            del self._tools[name]
            logger.debug(f"Unregistered tool: {name}")
            return True
        return False

    def get_by_source(self, source: str) -> list[ToolSpec]:
        """Return all tools whose ``source`` matches *source*."""
        return [s for s in self._tools.values() if s.source == source]

    def execute(self, name: str, arguments: dict[str, Any]) -> Any:
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
        # Drop any keys that the handler does not accept.  LLMs occasionally
        # inject extra fields (e.g. "object", "parameters") that are not part
        # of the tool schema.
        sig = inspect.signature(spec.handler)
        valid_params = sig.parameters
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in valid_params.values()):
            # Handler accepts **kwargs — forward everything as-is.
            filtered = arguments
        else:
            filtered = {k: v for k, v in arguments.items() if k in valid_params}
            dropped = set(arguments) - set(filtered)
            if dropped:
                logger.debug(f"[TOOLS] Dropping unexpected arguments for '{name}': {dropped}")
        return spec.handler(**filtered)

    # -- Ollama schema export -----------------------------------------------

    def get_ollama_schemas(self) -> list[dict[str, Any]]:
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
    def names(self) -> list[str]:
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
