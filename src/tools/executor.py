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

    @staticmethod
    def _try_parse_content_tool_call(content: str) -> Optional[Dict[str, Any]]:
        """
        Detect a tool call emitted as a raw JSON string in the content field.

        Some models (e.g. Llama 3.2) do not support the structured
        ``tool_calls`` field and instead output a JSON object such as::

            {"name": "search_documents", "parameters": {"query": "..."}}

        Returns a normalised tool_calls entry dict, or ``None``.
        """
        if not content:
            return None
        stripped = content.strip()
        if not stripped.startswith("{"):
            return None
        try:
            data = json.loads(stripped)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(data, dict) or "name" not in data:
            return None
        args = (
            data.get("parameters")
            or data.get("arguments")
            or data.get("input")
            or {}
        )
        return {"function": {"name": data["name"], "arguments": args}}

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
        # True once we know the model emits tool calls as raw JSON in content
        # rather than via the structured tool_calls field.
        inline_mode: bool = False

        for round_num in range(1, self._max_rounds + 1):
            logger.debug(
                f"[TOOLS] Round {round_num}/{self._max_rounds}: "
                f"{len(working_messages)} messages, {len(schemas)} tool(s)"
            )

            # In inline mode don't send schemas — the model can't use them
            # properly and they cause it to loop by emitting more JSON.
            response = self._client.generate_chat_completion(
                model, working_messages, tools=(None if inline_mode else schemas)
            )
            assistant_msg = response.get("message", {})
            tool_calls = assistant_msg.get("tool_calls")

            if not tool_calls:
                content = assistant_msg.get("content", "")
                # Models that don't support structured tool_calls may emit
                # the call as a raw JSON object in the content field.
                inlined = self._try_parse_content_tool_call(content)
                if inlined is not None:
                    logger.debug("[TOOLS] Detected inline JSON tool call in content field")
                    inline_mode = True
                    tool_calls = [inlined]
                else:
                    # Genuine final answer — stream it.
                    if content:
                        yield content
                    return

            # --- Execute tool calls -----------------------------------
            # For models that understand the tool role, keep the standard
            # message chain.  For inline-mode models, skip appending the
            # raw-JSON assistant message (it confuses them) and instead
            # feed the result back as a plain user turn.
            if not inline_mode:
                working_messages.append(assistant_msg)

            for tc in tool_calls:
                func = tc.get("function", {})
                name = func.get("name", "")
                arguments = self._parse_tool_arguments(func.get("arguments", {}))

                result = self._run_tool(name, arguments)

                if inline_mode:
                    working_messages.append({
                        "role": "user",
                        "content": (
                            f"Tool '{name}' returned:\n{result}\n\n"
                            "Using this information, answer the original question "
                            "in plain natural language. Do not output JSON."
                        ),
                    })
                else:
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
