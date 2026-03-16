"""
Tool Executor
=============

Manages the multi-turn tool-calling loop between the LLM and registered
tools.  The executor:

1. Sends the conversation (with tool schemas) to the model.
2. If the model returns ``tool_calls``, executes each tool.
3. Appends tool results and repeats (up to ``max_rounds``).
4. When the model returns plain content, yields it to the caller.

Usage:
    >>> executor = ToolExecutor(ollama_client, tool_registry)
    >>> for chunk in executor.execute("llama3.2", messages):
    ...     print(chunk, end="")

Author: LocalChat Team
"""

from __future__ import annotations

import json
from typing import Any, Dict, Generator, List, Optional

from .. import config
from ..ollama_client import OllamaClient
from ..utils.logging_config import get_logger
from .registry import ToolRegistry

logger = get_logger(__name__)


class ToolExecutor:
    """
    Orchestrates the tool-calling loop between an Ollama model and a
    ``ToolRegistry``.

    Args:
        client: ``OllamaClient`` instance for API communication.
        registry: ``ToolRegistry`` holding the available tools.
        max_rounds: Maximum number of tool-call iterations before forcing
            a final streamed response (default from ``config.TOOL_MAX_ROUNDS``).
    """

    def __init__(
        self,
        client: OllamaClient,
        registry: ToolRegistry,
        max_rounds: Optional[int] = None,
    ) -> None:
        self._client = client
        self._registry = registry
        self._max_rounds: int = max_rounds or getattr(config, "TOOL_MAX_ROUNDS", 5)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_tool_arguments(arguments) -> dict:
        """Deserialise tool arguments to a dict, handling JSON strings."""
        if isinstance(arguments, dict):
            return arguments
        try:
            return json.loads(arguments)
        except (json.JSONDecodeError, TypeError):
            return {}

    def execute(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        stream: bool = True,
    ) -> Generator[str, None, None]:
        """
        Run a chat completion with automatic tool execution.

        Yields:
            Text chunks of the model's final answer.

        The method is a generator so it can be plugged directly into the
        existing SSE streaming pipeline.
        """
        schemas = self._registry.get_ollama_schemas()
        if not schemas:
            yield from self._client.generate_chat_response(
                model, messages, stream=stream
            )
            return

        working_messages: List[Dict[str, Any]] = list(messages)

        for round_num in range(1, self._max_rounds + 1):
            logger.debug(
                f"[TOOLS] Round {round_num}/{self._max_rounds}: "
                f"{len(working_messages)} messages, {len(schemas)} tool(s)"
            )

            response = self._client.generate_chat_completion(
                model, working_messages, tools=schemas
            )
            assistant_msg = response.get("message", {})
            tool_calls = assistant_msg.get("tool_calls")

            if not tool_calls:
                # Model produced a final text answer - yield it.
                content = assistant_msg.get("content", "")
                if content:
                    yield content
                return

            # --- Execute tool calls -----------------------------------
            working_messages.append(assistant_msg)

            for tc in tool_calls:
                func = tc.get("function", {})
                name = func.get("name", "")
                arguments = self._parse_tool_arguments(func.get("arguments", {}))

                result = self._run_tool(name, arguments)

                working_messages.append({"role": "tool", "content": result})

        # Exhausted all rounds - stream a final answer without tools.
        logger.warning(
            f"[TOOLS] Reached max rounds ({self._max_rounds}), "
            "streaming final response without tools"
        )
        yield from self._client.generate_chat_response(
            model, working_messages, stream=stream
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _run_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        """Execute a single tool and return its result as a string."""
        logger.info(
            f"[TOOLS] Calling: {name}("
            f"{json.dumps(arguments, default=str)[:200]})"
        )

        if name not in self._registry:
            error = f"Unknown tool: {name}"
            logger.warning(f"[TOOLS] {error}")
            return error

        try:
            result = self._registry.execute(name, arguments)
        except Exception as exc:
            logger.error(f"[TOOLS] Tool '{name}' raised: {exc}", exc_info=True)
            return f"Tool error: {exc}"

        if not isinstance(result, str):
            result = json.dumps(result, default=str)

        logger.debug(f"[TOOLS] Result ({name}): {result[:200]}")
        return result
