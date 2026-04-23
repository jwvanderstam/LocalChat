"""
MCP Server Base
===============

Lightweight JSON-RPC 2.0 server base class for LocalChat MCP domain servers.
Each server exposes tools via POST /mcp and a GET /health endpoint.

Protocol:
  - tools/list  → {"jsonrpc":"2.0","id":N,"method":"tools/list","params":{}}
  - tools/call  → {"jsonrpc":"2.0","id":N,"method":"tools/call","params":{"name":"<tool>","arguments":{...}}}
  - health      → {"jsonrpc":"2.0","id":N,"method":"health","params":{}}
"""

import json
import logging
from typing import Any, Callable

from flask import Flask, jsonify, request

logger = logging.getLogger(__name__)


def _rpc_ok(id_: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _rpc_error(id_: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


class MCPServer:
    """
    Base class for LocalChat MCP domain servers.

    Each subclass registers tools via register_tool() and then either:
      - calls run() for standalone operation, or
      - passes get_wsgi_app() to gunicorn.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._tools: dict[str, dict] = {}
        self._handlers: dict[str, Callable] = {}

        self.app = Flask(name)
        self.app.json.sort_keys = False

        @self.app.route("/mcp", methods=["POST"])
        def handle_rpc():  # noqa: ANN202
            body = request.get_json(force=True, silent=True) or {}
            id_ = body.get("id")
            method = body.get("method", "")
            params = body.get("params") or {}

            if method == "health":
                return jsonify(_rpc_ok(id_, {"status": "ok", "server": self.name}))

            if method == "tools/list":
                return jsonify(_rpc_ok(id_, {"tools": list(self._tools.values())}))

            if method == "tools/call":
                tool_name = params.get("name", "")
                args = params.get("arguments") or {}
                if tool_name not in self._handlers:
                    return jsonify(_rpc_error(id_, -32601, f"Tool not found: {tool_name}"))
                try:
                    result = self._handlers[tool_name](**args)
                    content = [{"type": "text", "text": json.dumps(result)}]
                    return jsonify(_rpc_ok(id_, {"content": content}))
                except Exception as exc:
                    logger.error("[%s] Tool '%s' raised: %s", self.name, str(tool_name).replace('\r','').replace('\n',' '), exc, exc_info=True)
                    return jsonify(_rpc_error(id_, -32000, "Tool execution failed"))

            return jsonify(_rpc_error(id_, -32601, f"Method not found: {method}"))

        @self.app.route("/health", methods=["GET"])
        def health():  # noqa: ANN202
            return jsonify({"status": "ok", "server": self.name})

    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: dict,
        handler: Callable,
    ) -> None:
        """Register a tool with its JSON Schema and handler function."""
        self._tools[name] = {
            "name": name,
            "description": description,
            "inputSchema": input_schema,
        }
        self._handlers[name] = handler

    def get_wsgi_app(self) -> Flask:
        """Return the Flask WSGI app (for gunicorn)."""
        return self.app

    def run(self, host: str = "0.0.0.0", port: int = 5001, debug: bool = False) -> None:
        """Run the server in development mode."""
        logger.info(f"[{self.name}] Starting on {host}:{port}")
        self.app.run(host=host, port=port, debug=debug)
