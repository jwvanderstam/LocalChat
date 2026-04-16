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
        max_rounds: int | None = None,
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
    def _try_parse_content_tool_call(content: str) -> dict[str, Any] | None:
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

    @staticmethod
    def _format_data_as_text(data: Any, indent: int = 0) -> str:
        """Recursively convert a dict/list/scalar to a readable plain-text string."""
        pad = "  " * indent
        if isinstance(data, dict):
            lines = []
            for k, v in data.items():
                label = str(k).replace("_", " ").title()
                if isinstance(v, (dict, list)):
                    lines.append(f"{pad}**{label}:**")
                    lines.append(ToolExecutor._format_data_as_text(v, indent + 1))
                else:
                    lines.append(f"{pad}- {label}: {v}")
            return "\n".join(lines)
        if isinstance(data, list):
            return "\n".join(
                f"{pad}- {ToolExecutor._format_data_as_text(item, indent + 1)}"
                for item in data
            )
        return f"{pad}{data}"

    def execute(
        self,
        model: str,
        messages: list[dict[str, Any]],
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

        working_messages: list[dict[str, Any]] = list(messages)
        inline_mode: bool = False

        for round_num in range(1, self._max_rounds + 1):
            logger.debug(
                f"[TOOLS] Round {round_num}/{self._max_rounds}: "
                f"{len(working_messages)} messages, {len(schemas)} tool(s)"
            )

            active_tools = None if inline_mode else schemas
            response = self._client.generate_chat_completion(
                model, working_messages, tools=active_tools
            )
            assistant_msg = response.get("message", {})
            tool_calls = assistant_msg.get("tool_calls")

            if not tool_calls:
                answer, tool_calls, inline_mode = self._handle_no_tool_calls(
                    assistant_msg.get("content", ""), inline_mode
                )
                if answer is not None:
                    if answer:
                        yield answer
                    return

            if not inline_mode:
                working_messages.append(assistant_msg)

            self._append_tool_results(tool_calls, inline_mode, working_messages)

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

    def _handle_no_tool_calls(
        self, content: str, inline_mode: bool
    ) -> tuple:
        """
        Process a round where the model returned no tool_calls field.

        Returns ``(answer, tool_calls, new_inline_mode)``.  When ``answer``
        is not ``None`` it is the final text to yield (empty string means
        yield nothing); otherwise ``tool_calls`` is a list to execute next.
        """
        inlined = self._try_parse_content_tool_call(content)
        if inlined is None:
            return content, None, inline_mode
        if inline_mode:
            logger.debug("[TOOLS] Model echoing result as JSON; formatting as text")
            args = inlined.get("function", {}).get("arguments", {})
            text = self._format_data_as_text(args) if args else content
            return text, None, inline_mode
        logger.debug("[TOOLS] Detected inline JSON tool call in content field")
        return None, [inlined], True

    def _append_tool_results(
        self,
        tool_calls: list,
        inline_mode: bool,
        working_messages: list[dict[str, Any]],
    ) -> None:
        """Execute each tool call and append results to working_messages."""
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

    def _run_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Execute a single tool and return its result as a string."""
        logger.info(
            f"[TOOLS] Calling: {name}("
            f"{json.dumps(arguments, default=str)[:200]})"
        )

        if name not in self._registry:
            error = f"Unknown tool: {name}"
            logger.warning(f"[TOOLS] {error}")
            return error

        # Guard: some small models (e.g. llama3.2 3B) echo the JSON Schema
        # property dict as the argument value instead of an actual string.
        spec = self._registry.get(name)
        if spec is not None:
            props = spec.parameters.get("properties", {})
            for k, v in arguments.items():
                if props.get(k, {}).get("type") == "string" and isinstance(v, dict):
                    logger.warning(
                        f"[TOOLS] Argument '{k}' for '{name}' received a schema "
                        "dict instead of a string — model generated invalid tool call"
                    )
                    return (
                        f"Error: argument '{k}' must be a plain string, not a schema "
                        "object. Call the tool again with the actual value as a string."
                    )

        try:
            result = self._registry.execute(name, arguments)
        except Exception as exc:
            logger.error(f"[TOOLS] Tool '{name}' raised: {exc}", exc_info=True)
            return f"Tool error: {exc}"

        if not isinstance(result, str):
            result = json.dumps(result, default=str)

        logger.debug(f"[TOOLS] Result ({name}): {result[:200]}")
        return result
