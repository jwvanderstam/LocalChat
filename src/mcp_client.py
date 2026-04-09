"""
MCP Client
==========

HTTP client for communicating with LocalChat MCP domain servers via
JSON-RPC 2.0.  Features per-server circuit breakers, TTL-cached health
checks, and a module-level registry singleton.

Usage:
    from src.mcp_client import mcp_registry

    # When MCP_ENABLED=true, use instead of direct imports:
    result = mcp_registry.local_docs.call_tool("search", {
        "query": "...", "filters": {}, "top_k": 10
    })
    # → {"context": "...", "sources": [...]}
"""

import json
import threading
import time
from typing import Any

import requests

from . import config
from .utils.logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """
    Three-state circuit breaker (CLOSED → OPEN → HALF_OPEN → CLOSED).

    CLOSED:    All calls pass through.
    OPEN:      All calls rejected immediately; server assumed down.
    HALF_OPEN: One probe call allowed; success → CLOSED, failure → OPEN.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._state = self.CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            if self._state == self.OPEN and time.monotonic() - self._opened_at >= self.recovery_timeout:
                self._state = self.HALF_OPEN
            return self._state

    def is_available(self) -> bool:
        return self.state != self.OPEN

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._state = self.CLOSED

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                if self._state != self.OPEN:
                    logger.warning(
                        f"[CircuitBreaker] Circuit opened after {self._failures} consecutive failures"
                    )
                self._state = self.OPEN
                self._opened_at = time.monotonic()


# ---------------------------------------------------------------------------
# MCPClient — single server
# ---------------------------------------------------------------------------

_HEALTH_CACHE_TTL: float = 30.0  # seconds


class MCPClient:
    """
    JSON-RPC 2.0 HTTP client for a single MCP server.

    Thread-safe.  Maintains a requests.Session for connection pooling.
    Circuit breaker prevents cascade failures when a server is down.
    Health checks are TTL-cached (30 s) to avoid spamming the UI status poll.
    """

    def __init__(self, name: str, base_url: str, timeout: int = 30) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers["Content-Type"] = "application/json"
        self._cb = CircuitBreaker(
            failure_threshold=config.MCP_CIRCUIT_FAILURE_THRESHOLD,
            recovery_timeout=config.MCP_CIRCUIT_RECOVERY_TIMEOUT,
        )
        self._req_id = 0
        self._id_lock = threading.Lock()
        # TTL health cache
        self._health_cache: bool | None = None
        self._health_checked_at: float = 0.0
        self._health_lock = threading.Lock()

    def _next_id(self) -> int:
        with self._id_lock:
            self._req_id += 1
            return self._req_id

    def _rpc(self, method: str, params: dict) -> Any:
        """
        Execute one JSON-RPC call.  Raises RuntimeError on circuit open or
        any transport/protocol error.
        """
        if not self._cb.is_available():
            raise RuntimeError(f"[MCP:{self.name}] circuit open — server assumed unavailable")

        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params,
        }
        try:
            resp = self._session.post(
                f"{self.base_url}/mcp",
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            self._cb.record_failure()
            raise RuntimeError(f"[MCP:{self.name}] transport error: {exc}") from exc

        if "error" in data:
            # Protocol-level error — don't trip the circuit breaker.
            raise RuntimeError(f"[MCP:{self.name}] RPC error {data['error']['code']}: {data['error']['message']}")

        self._cb.record_success()
        return data.get("result")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def call_tool(self, name: str, arguments: dict) -> Any:
        """Call a named tool and return the decoded result dict/list."""
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        content = (result or {}).get("content", [])
        if content and content[0].get("type") == "text":
            return json.loads(content[0]["text"])
        return result

    def list_tools(self) -> list[dict]:
        """Return tool schemas from the server."""
        result = self._rpc("tools/list", {})
        return (result or {}).get("tools", [])

    def health(self) -> bool:
        """
        Return True if the server is reachable and healthy.

        Result is cached for _HEALTH_CACHE_TTL seconds so the UI status
        poll (which hits /api/status ~every second) doesn't hammer the servers.
        """
        with self._health_lock:
            now = time.monotonic()
            if self._health_cache is not None and now - self._health_checked_at < _HEALTH_CACHE_TTL:
                return self._health_cache
            try:
                result = self._rpc("health", {})
                ok = (result or {}).get("status") == "ok"
            except Exception:
                ok = False
            self._health_cache = ok
            self._health_checked_at = now
            return ok

    @property
    def circuit_state(self) -> str:
        return self._cb.state


# ---------------------------------------------------------------------------
# MCPClientRegistry — module-level singleton
# ---------------------------------------------------------------------------

class MCPClientRegistry:
    """Registry of all MCP server clients for LocalChat."""

    def __init__(self) -> None:
        self.local_docs = MCPClient(
            "local-docs",
            config.MCP_LOCAL_DOCS_URL,
            config.MCP_TIMEOUT,
        )
        self.web_search = MCPClient(
            "web-search",
            config.MCP_WEB_SEARCH_URL,
            config.MCP_TIMEOUT,
        )
        self.cloud_connectors = MCPClient(
            "cloud-connectors",
            config.MCP_CLOUD_CONNECTORS_URL,
            config.MCP_TIMEOUT,
        )

    def health_summary(self) -> dict[str, dict]:
        """Return health status for all servers (cached per server)."""
        servers = {
            "local_docs": (self.local_docs, config.MCP_LOCAL_DOCS_URL),
            "web_search": (self.web_search, config.MCP_WEB_SEARCH_URL),
            "cloud_connectors": (self.cloud_connectors, config.MCP_CLOUD_CONNECTORS_URL),
        }
        return {
            key: {
                "url": url,
                "healthy": client.health(),
                "circuit": client.circuit_state,
            }
            for key, (client, url) in servers.items()
        }


# Singleton — created once per process.
mcp_registry = MCPClientRegistry()
