"""Unit tests for the web-search MCP server (mcp_servers/web_search/server.py)."""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import src.rag.web_search as web_search_module
from mcp_servers.web_search import server
from src.rag.web_search import WebSearchResult


@pytest.fixture
def client() -> TestClient:
    return TestClient(server.app)


def _mock_provider_class(results: list[WebSearchResult], formatted: str = "formatted web context") -> Mock:
    instance = Mock()
    instance.search = Mock(return_value=results)
    instance.format_web_context = Mock(return_value=formatted)
    provider_class = Mock(return_value=instance)
    return provider_class


@pytest.mark.unit
def test_search_returns_context_and_results_from_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    results = [
        WebSearchResult(title="Result A", url="https://a.example", snippet="snippet a"),
        WebSearchResult(title="Result B", url="https://b.example", snippet="snippet b"),
    ]
    provider_class = _mock_provider_class(results)
    monkeypatch.setattr(web_search_module, "WebSearchProvider", provider_class)

    result = server.search("what is the weather")

    assert result["context"] == "formatted web context"
    assert result["result_count"] == 2
    assert result["results"] == [
        {"title": "Result A", "url": "https://a.example", "snippet": "snippet a"},
        {"title": "Result B", "url": "https://b.example", "snippet": "snippet b"},
    ]


@pytest.mark.unit
def test_search_returns_empty_results_when_provider_finds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    provider_class = _mock_provider_class([])
    monkeypatch.setattr(web_search_module, "WebSearchProvider", provider_class)

    result = server.search("nothing found query")

    assert result["result_count"] == 0
    assert result["results"] == []


@pytest.mark.unit
def test_search_constructs_provider_with_max_results(monkeypatch: pytest.MonkeyPatch) -> None:
    provider_class = _mock_provider_class([])
    monkeypatch.setattr(web_search_module, "WebSearchProvider", provider_class)

    server.search("query", max_results=3)

    provider_class.assert_called_once_with(max_results=3)


@pytest.mark.unit
def test_list_sources_returns_duckduckgo_provider_info() -> None:
    result = server.list_sources()

    assert result == [
        {
            "name": "DuckDuckGo",
            "type": "web_search",
            "status": "active",
            "requires_api_key": False,
        }
    ]


@pytest.mark.unit
def test_main_parses_args_and_runs_server(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}
    monkeypatch.setattr(server._server, "run", lambda **kwargs: calls.update(kwargs))
    monkeypatch.setattr("sys.argv", ["web-search", "--host", "127.0.0.1", "--port", "5222", "--debug"])

    server._main()

    assert calls == {"host": "127.0.0.1", "port": 5222, "debug": True}


@pytest.mark.unit
def test_health_endpoint_reports_server_name(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "server": "web-search"}


@pytest.mark.unit
def test_tools_list_endpoint_includes_search_and_list_sources(client: TestClient) -> None:
    resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    tool_names = {t["name"] for t in resp.json()["result"]["tools"]}
    assert tool_names == {"search", "list_sources"}


@pytest.mark.unit
def test_tools_call_search_endpoint_returns_content(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    provider_class = _mock_provider_class(
        [WebSearchResult(title="R", url="https://r.example", snippet="s")], formatted="ctx"
    )
    monkeypatch.setattr(web_search_module, "WebSearchProvider", provider_class)

    resp = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "search", "arguments": {"query": "test"}},
        },
    )
    body = resp.json()
    assert '"context": "ctx"' in body["result"]["content"][0]["text"]


@pytest.mark.unit
def test_tools_call_list_sources_endpoint_returns_content(client: TestClient) -> None:
    resp = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_sources", "arguments": {}}},
    )
    body = resp.json()
    assert "DuckDuckGo" in body["result"]["content"][0]["text"]
