"""
Tests for src/mcp_client.py

Covers:
  - CircuitBreaker: state transitions CLOSED→OPEN→HALF_OPEN→CLOSED
  - CircuitBreaker: failure threshold, recovery timeout
  - MCPClient._rpc: circuit open fast-path, transport errors, RPC errors, success
  - MCPClient.call_tool: JSON text content decoding, fallback
  - MCPClient.health: TTL cache, unhealthy server, circuit open
  - MCPClientRegistry: health_summary structure
"""

import json
import time
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------

class TestCircuitBreakerStates:
    def _make_cb(self, threshold=3, recovery=60):
        from src.mcp_client import CircuitBreaker
        return CircuitBreaker(failure_threshold=threshold, recovery_timeout=recovery)

    def test_initial_state_is_closed(self):
        cb = self._make_cb()
        assert cb.state == "closed"

    def test_is_available_when_closed(self):
        cb = self._make_cb()
        assert cb.is_available() is True

    def test_opens_after_threshold_failures(self):
        cb = self._make_cb(threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == "open"

    def test_not_open_before_threshold(self):
        cb = self._make_cb(threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "closed"

    def test_is_not_available_when_open(self):
        cb = self._make_cb(threshold=1)
        cb.record_failure()
        assert cb.is_available() is False

    def test_transitions_to_half_open_after_recovery_timeout(self):
        from src.mcp_client import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=30)
        cb.record_failure()
        assert cb.state == "open"
        # Simulate recovery timeout elapsed
        cb._opened_at = time.monotonic() - 31
        assert cb.state == "half_open"

    def test_half_open_is_available(self):
        from src.mcp_client import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=30)
        cb.record_failure()
        cb._opened_at = time.monotonic() - 31
        assert cb.is_available() is True

    def test_success_resets_to_closed(self):
        cb = self._make_cb(threshold=1)
        cb.record_failure()
        assert cb.state == "open"
        cb.record_success()
        assert cb.state == "closed"

    def test_success_resets_failure_count(self):
        cb = self._make_cb(threshold=5)
        for _ in range(4):
            cb.record_failure()
        cb.record_success()
        # 4 more failures should NOT open the circuit (count was reset)
        for _ in range(4):
            cb.record_failure()
        assert cb.state == "closed"

    def test_failure_during_half_open_reopens(self):
        from src.mcp_client import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=30)
        cb.record_failure()
        cb._opened_at = time.monotonic() - 31
        assert cb.state == "half_open"
        cb.record_failure()
        assert cb.state == "open"

    def test_open_stays_open_within_recovery_window(self):
        from src.mcp_client import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60)
        cb.record_failure()
        # Only 10 seconds elapsed — still open
        cb._opened_at = time.monotonic() - 10
        assert cb.state == "open"


# ---------------------------------------------------------------------------
# MCPClient._rpc
# ---------------------------------------------------------------------------

class TestMCPClientRpc:
    def _make_client(self, base_url="http://localhost:5001", timeout=10):
        from src.mcp_client import MCPClient
        with patch("src.mcp_client.config") as cfg:
            cfg.MCP_CIRCUIT_FAILURE_THRESHOLD = 5
            cfg.MCP_CIRCUIT_RECOVERY_TIMEOUT = 60
            client = MCPClient("test", base_url, timeout)
        return client

    def test_raises_when_circuit_open(self):
        client = self._make_client()
        # Force circuit open
        client._cb._state = "open"
        client._cb._opened_at = time.monotonic()  # recently opened
        with pytest.raises(RuntimeError, match="circuit open"):
            client._rpc("tools/list", {})

    def test_transport_error_trips_circuit(self):
        client = self._make_client()
        client._session.post = MagicMock(side_effect=ConnectionError("refused"))
        with pytest.raises(RuntimeError, match="transport error"):
            client._rpc("tools/list", {})
        assert client._cb._failures == 1

    def test_http_error_trips_circuit(self):
        import requests
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("500")
        client._session.post = MagicMock(return_value=mock_resp)
        with pytest.raises(RuntimeError, match="transport error"):
            client._rpc("health", {})
        assert client._cb._failures == 1

    def test_rpc_error_does_not_trip_circuit(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "jsonrpc": "2.0", "id": 1,
            "error": {"code": -32601, "message": "Method not found"}
        }
        client._session.post = MagicMock(return_value=mock_resp)
        with pytest.raises(RuntimeError, match="RPC error"):
            client._rpc("unknown/method", {})
        # Circuit breaker NOT tripped for protocol errors
        assert client._cb._failures == 0

    def test_success_returns_result_and_resets_circuit(self):
        client = self._make_client()
        client._cb._failures = 3  # some prior failures
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "jsonrpc": "2.0", "id": 1,
            "result": {"tools": []}
        }
        client._session.post = MagicMock(return_value=mock_resp)
        result = client._rpc("tools/list", {})
        assert result == {"tools": []}
        assert client._cb._failures == 0

    def test_increments_request_id(self):
        client = self._make_client()
        captured = []
        def fake_post(url, json=None, timeout=None):
            captured.append(json["id"])
            mock_resp = MagicMock()
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = {"jsonrpc": "2.0", "id": json["id"], "result": {}}
            return mock_resp
        client._session.post = fake_post
        client._rpc("health", {})
        client._rpc("health", {})
        assert captured == [1, 2]


# ---------------------------------------------------------------------------
# MCPClient.call_tool
# ---------------------------------------------------------------------------

class TestMCPClientCallTool:
    def _make_client(self):
        from src.mcp_client import MCPClient
        with patch("src.mcp_client.config") as cfg:
            cfg.MCP_CIRCUIT_FAILURE_THRESHOLD = 5
            cfg.MCP_CIRCUIT_RECOVERY_TIMEOUT = 60
            client = MCPClient("test", "http://localhost:5001", 10)
        return client

    def _mock_rpc(self, client, return_value):
        client._rpc = MagicMock(return_value=return_value)

    def test_decodes_text_content(self):
        client = self._make_client()
        payload = {"context": "some text", "sources": []}
        self._mock_rpc(client, {
            "content": [{"type": "text", "text": json.dumps(payload)}]
        })
        result = client.call_tool("search", {"query": "test"})
        assert result == payload

    def test_returns_raw_result_when_no_text_content(self):
        client = self._make_client()
        raw = {"tools": [{"name": "search"}]}
        self._mock_rpc(client, raw)
        result = client.call_tool("list_tools", {})
        assert result == raw

    def test_returns_none_when_rpc_returns_none(self):
        client = self._make_client()
        self._mock_rpc(client, None)
        result = client.call_tool("search", {})
        assert result is None

    def test_returns_result_when_content_type_not_text(self):
        client = self._make_client()
        raw = {"content": [{"type": "image", "data": "..."}]}
        self._mock_rpc(client, raw)
        result = client.call_tool("search", {})
        assert result == raw


# ---------------------------------------------------------------------------
# MCPClient.health (TTL cache)
# ---------------------------------------------------------------------------

class TestMCPClientHealth:
    def _make_client(self):
        from src.mcp_client import MCPClient
        with patch("src.mcp_client.config") as cfg:
            cfg.MCP_CIRCUIT_FAILURE_THRESHOLD = 5
            cfg.MCP_CIRCUIT_RECOVERY_TIMEOUT = 60
            client = MCPClient("test", "http://localhost:5001", 10)
        return client

    def test_healthy_server_returns_true(self):
        client = self._make_client()
        client._rpc = MagicMock(return_value={"status": "ok"})
        assert client.health() is True

    def test_unhealthy_status_returns_false(self):
        client = self._make_client()
        client._rpc = MagicMock(return_value={"status": "degraded"})
        assert client.health() is False

    def test_rpc_exception_returns_false(self):
        client = self._make_client()
        client._rpc = MagicMock(side_effect=RuntimeError("circuit open"))
        assert client.health() is False

    def test_result_is_cached(self):
        client = self._make_client()
        client._rpc = MagicMock(return_value={"status": "ok"})
        client.health()
        client.health()
        # Second call should use cache — only 1 RPC call
        assert client._rpc.call_count == 1

    def test_cache_expires_after_ttl(self):
        from src.mcp_client import _HEALTH_CACHE_TTL
        client = self._make_client()
        client._rpc = MagicMock(return_value={"status": "ok"})
        client.health()
        # Expire the cache
        client._health_checked_at = time.monotonic() - (_HEALTH_CACHE_TTL + 1)
        client.health()
        assert client._rpc.call_count == 2

    def test_circuit_state_property(self):
        client = self._make_client()
        assert client.circuit_state == "closed"


# ---------------------------------------------------------------------------
# MCPClientRegistry
# ---------------------------------------------------------------------------

class TestMCPClientRegistry:
    def _make_registry(self):
        from src.mcp_client import MCPClientRegistry
        with patch("src.mcp_client.config") as cfg:
            cfg.MCP_CIRCUIT_FAILURE_THRESHOLD = 5
            cfg.MCP_CIRCUIT_RECOVERY_TIMEOUT = 60
            cfg.MCP_TIMEOUT = 10
            cfg.MCP_LOCAL_DOCS_URL = "http://localhost:5001"
            cfg.MCP_WEB_SEARCH_URL = "http://localhost:5002"
            cfg.MCP_CLOUD_CONNECTORS_URL = "http://localhost:5003"
            reg = MCPClientRegistry()
        return reg

    def test_has_three_clients(self):
        reg = self._make_registry()
        assert hasattr(reg, "local_docs")
        assert hasattr(reg, "web_search")
        assert hasattr(reg, "cloud_connectors")

    def test_health_summary_has_all_keys(self):
        reg = self._make_registry()
        # Mock health() on each client to avoid real HTTP calls
        for attr in ("local_docs", "web_search", "cloud_connectors"):
            getattr(reg, attr).health = MagicMock(return_value=False)
        summary = reg.health_summary()
        assert set(summary.keys()) == {"local_docs", "web_search", "cloud_connectors"}

    def test_health_summary_entry_structure(self):
        reg = self._make_registry()
        for attr in ("local_docs", "web_search", "cloud_connectors"):
            getattr(reg, attr).health = MagicMock(return_value=True)
        summary = reg.health_summary()
        for entry in summary.values():
            assert "url" in entry
            assert "healthy" in entry
            assert "circuit" in entry

    def test_health_summary_reflects_health_value(self):
        reg = self._make_registry()
        reg.local_docs.health = MagicMock(return_value=True)
        reg.web_search.health = MagicMock(return_value=False)
        reg.cloud_connectors.health = MagicMock(return_value=False)
        summary = reg.health_summary()
        assert summary["local_docs"]["healthy"] is True
        assert summary["web_search"]["healthy"] is False
