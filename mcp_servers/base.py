"""
MCP Server Base
===============

Lightweight JSON-RPC 2.0 server base class for LocalChat MCP domain servers.
Each server exposes tools via POST /mcp and a GET /health endpoint.

Protocol:
  - tools/list  -> {"jsonrpc":"2.0","id":N,"method":"tools/list","params":{}}
  - tools/call  -> {"jsonrpc":"2.0","id":N,"method":"tools/call","params":{"name":"<tool>","arguments":{...}}}
  - health      -> {"jsonrpc":"2.0","id":N,"method":"health","params":{}}

Built on FastAPI/Starlette (ASGI). Run via uvicorn with the module-level
``app`` object, or call ``run()`` for standalone development.
"""

import hmac
import json
import logging
import os
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

#: Read from the environment rather than src.config so a server can be started
#: without importing the application. Same variable either way.
_AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN", "")


def _authorised(request: Request) -> bool:
    """True when the caller presents the shared secret.

    These servers hold no session and no user: whatever reaches them is served, so
    this is the whole of their access control. An unset token refuses everything
    rather than serving anonymously — they sit on the compose network with the
    database and retrieve from every workspace, so open-by-default is the wrong
    failure (audit C3).

    compare_digest, not ==, so a wrong token cannot be found a character at a time.
    """
    if not _AUTH_TOKEN:
        return False
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return False
    return hmac.compare_digest(header[7:].strip(), _AUTH_TOKEN)


def _rpc_ok(id_: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _rpc_error(id_: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


class MCPServer:
    """
    Base class for LocalChat MCP domain servers.

    Each subclass registers tools via register_tool() and then either:
      - calls run() for standalone operation, or
      - passes get_asgi_app() to uvicorn.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._tools: dict[str, dict] = {}
        self._handlers: dict[str, Callable] = {}

        self.app = FastAPI(title=f"MCP server: {name}", docs_url=None, redoc_url=None)

        @self.app.post("/mcp")
        async def handle_rpc(request: Request) -> JSONResponse:
            if not _authorised(request):
                if not _AUTH_TOKEN:
                    logger.error(
                        "[%s] MCP_AUTH_TOKEN is not set; refusing every call. "
                        "Set it on this server and on the application.", self.name
                    )
                return JSONResponse(
                    _rpc_error(None, -32001, "Unauthorised"), status_code=401
                )
            try:
                body = await request.json()
            except Exception:  # noqa: BLE001 — a JSON-RPC body that will not parse is an empty body; the dispatcher below returns the protocol's own error
                body = {}
            if not isinstance(body, dict):
                body = {}

            id_ = body.get("id")
            method = body.get("method", "")
            params = body.get("params") or {}

            if method == "health":
                return JSONResponse(_rpc_ok(id_, {"status": "ok", "server": self.name}))

            if method == "tools/list":
                return JSONResponse(_rpc_ok(id_, {"tools": list(self._tools.values())}))

            if method == "tools/call":
                tool_name = params.get("name", "")
                args = params.get("arguments") or {}
                if tool_name not in self._handlers:
                    return JSONResponse(_rpc_error(id_, -32601, f"Tool not found: {tool_name}"))
                try:
                    result = self._handlers[tool_name](**args)
                    content = [{"type": "text", "text": json.dumps(result)}]
                    return JSONResponse(_rpc_ok(id_, {"content": content}))
                except Exception as exc:
                    safe_name = str(tool_name).replace("\r", "").replace("\n", " ")
                    logger.error("[%s] Tool '%s' raised: %s", self.name, safe_name, exc, exc_info=True)
                    return JSONResponse(_rpc_error(id_, -32000, "Tool execution failed"))

            return JSONResponse(_rpc_error(id_, -32601, f"Method not found: {method}"))

        @self.app.get("/health")
        async def health() -> JSONResponse:
            return JSONResponse({"status": "ok", "server": self.name})

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

    def get_asgi_app(self) -> FastAPI:
        """Return the FastAPI ASGI app (for uvicorn)."""
        return self.app

    def run(self, host: str = "0.0.0.0", port: int = 5001, debug: bool = False) -> None:
        """Run the server in development mode via uvicorn."""
        import uvicorn  # noqa: PLC0415

        logger.info(f"[{self.name}] Starting on {host}:{port}")
        uvicorn.run(self.app, host=host, port=port, log_level="debug" if debug else "info")
