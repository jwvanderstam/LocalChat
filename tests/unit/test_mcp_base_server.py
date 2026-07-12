"""Unit tests for the shared MCPServer JSON-RPC 2.0 dispatcher (mcp_servers/base.py)."""

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mcp_servers.base import MCPServer


def _echo(text: str) -> dict[str, str]:
    return {"echoed": text}


def _boom() -> None:
    raise ValueError("kaboom")


@pytest.fixture
def server() -> MCPServer:
    srv = MCPServer("test-server")
    srv.register_tool(
        name="echo",
        description="Echoes the input text",
        input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        handler=_echo,
    )
    srv.register_tool(
        name="boom",
        description="Always raises",
        input_schema={"type": "object", "properties": {}},
        handler=_boom,
    )
    return srv


@pytest.fixture
def client(server: MCPServer) -> TestClient:
    return TestClient(server.get_asgi_app())


@pytest.mark.unit
def test_get_asgi_app_returns_fastapi_instance(server: MCPServer) -> None:
    assert isinstance(server.get_asgi_app(), FastAPI)


@pytest.mark.unit
def test_register_tool_stores_metadata_and_handler(server: MCPServer) -> None:
    assert server._tools["echo"] == {
        "name": "echo",
        "description": "Echoes the input text",
        "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    }
    assert server._handlers["echo"] is _echo


@pytest.mark.unit
def test_health_method_returns_ok_status(client: TestClient) -> None:
    resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "health", "params": {}})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"jsonrpc": "2.0", "id": 1, "result": {"status": "ok", "server": "test-server"}}


@pytest.mark.unit
def test_health_get_endpoint_returns_ok_status(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "server": "test-server"}


@pytest.mark.unit
def test_tools_list_returns_all_registered_tools(client: TestClient) -> None:
    resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    body = resp.json()
    tool_names = {t["name"] for t in body["result"]["tools"]}
    assert tool_names == {"echo", "boom"}
    assert body["id"] == 2


@pytest.mark.unit
def test_tools_call_dispatches_to_handler_with_arguments(client: TestClient) -> None:
    resp = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"text": "hello"}},
        },
    )
    body = resp.json()
    assert body["result"]["content"] == [{"type": "text", "text": '{"echoed": "hello"}'}]


@pytest.mark.unit
def test_tools_call_unknown_tool_returns_method_not_found_error(client: TestClient) -> None:
    resp = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "nope", "arguments": {}}},
    )
    body = resp.json()
    assert body["error"]["code"] == -32601
    assert "nope" in body["error"]["message"]


@pytest.mark.unit
def test_tools_call_handler_exception_returns_generic_error_without_leaking_details(client: TestClient) -> None:
    resp = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "boom", "arguments": {}}},
    )
    body = resp.json()
    assert body["error"] == {"code": -32000, "message": "Tool execution failed"}
    assert "kaboom" not in resp.text


@pytest.mark.unit
def test_unknown_method_returns_method_not_found_error(client: TestClient) -> None:
    resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 6, "method": "not/a/method", "params": {}})
    body = resp.json()
    assert body["error"]["code"] == -32601
    assert "not/a/method" in body["error"]["message"]


@pytest.mark.unit
def test_malformed_json_body_is_treated_as_empty_request(client: TestClient) -> None:
    resp = client.post("/mcp", content=b"{not valid json", headers={"content-type": "application/json"})
    body = resp.json()
    assert body["id"] is None
    assert body["error"]["code"] == -32601


@pytest.mark.unit
def test_non_dict_json_body_is_treated_as_empty_request(client: TestClient) -> None:
    resp = client.post("/mcp", json=[1, 2, 3])
    body = resp.json()
    assert body["id"] is None
    assert body["error"]["code"] == -32601


@pytest.mark.unit
def test_tools_call_missing_arguments_defaults_to_empty_dict(client: TestClient) -> None:
    # "echo" requires "text"; omitting arguments entirely should surface the
    # resulting TypeError as a generic tool-execution error, not a 500.
    resp = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "echo"}},
    )
    body = resp.json()
    assert body["error"] == {"code": -32000, "message": "Tool execution failed"}


@pytest.mark.unit
def test_run_starts_uvicorn_with_configured_host_and_port(server: MCPServer, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {}

    def fake_run(app: FastAPI, host: str, port: int, log_level: str) -> None:
        calls["app"] = app
        calls["host"] = host
        calls["port"] = port
        calls["log_level"] = log_level

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", fake_run)
    server.run(host="127.0.0.1", port=9999, debug=True)
    assert calls == {"app": server.app, "host": "127.0.0.1", "port": 9999, "log_level": "debug"}
