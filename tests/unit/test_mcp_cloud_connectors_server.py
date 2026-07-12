"""Unit tests for the cloud-connectors MCP server (mcp_servers/cloud_connectors/server.py)."""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import src.db as db_module
import src.rag as rag_module
from mcp_servers.cloud_connectors import server


@pytest.fixture
def client() -> TestClient:
    return TestClient(server.app)


@pytest.mark.unit
def test_search_returns_context_and_sources_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    results = [
        ("chunk one", "sharepoint.docx", 0, 0.91234),
        ("chunk two", "onedrive.pdf", 1, 0.8),
    ]
    doc_processor = Mock()
    doc_processor.retrieve_context = Mock(return_value=results)
    doc_processor.format_context_for_llm = Mock(return_value="formatted context")
    monkeypatch.setattr(rag_module, "doc_processor", doc_processor)

    result = server.search("find the policy doc")

    assert result == {
        "context": "formatted context",
        "sources": [
            {"filename": "sharepoint.docx", "chunk_index": 0, "similarity": 0.9123},
            {"filename": "onedrive.pdf", "chunk_index": 1, "similarity": 0.8},
        ],
    }


@pytest.mark.unit
def test_search_passes_top_k_to_retrieve_context(monkeypatch: pytest.MonkeyPatch) -> None:
    doc_processor = Mock()
    doc_processor.retrieve_context = Mock(return_value=[])
    monkeypatch.setattr(rag_module, "doc_processor", doc_processor)

    server.search("query", top_k=3)

    doc_processor.retrieve_context.assert_called_once_with("query", top_k=3)


@pytest.mark.unit
def test_search_returns_empty_context_and_sources_when_no_results(monkeypatch: pytest.MonkeyPatch) -> None:
    doc_processor = Mock()
    doc_processor.retrieve_context = Mock(return_value=[])
    monkeypatch.setattr(rag_module, "doc_processor", doc_processor)

    result = server.search("no matches")

    assert result == {"context": "", "sources": []}


@pytest.mark.unit
def test_search_returns_error_dict_when_retrieve_context_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    doc_processor = Mock()
    doc_processor.retrieve_context = Mock(side_effect=RuntimeError("connector offline"))
    monkeypatch.setattr(rag_module, "doc_processor", doc_processor)

    result = server.search("query")

    assert result == {"context": "", "sources": [], "error": "connector offline"}


@pytest.mark.unit
def test_list_sources_returns_connectors_when_db_connected(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_db = Mock()
    mock_db.is_connected = True
    mock_db.list_connectors = Mock(return_value=[{"id": 1, "name": "sharepoint-prod"}])
    monkeypatch.setattr(db_module, "db", mock_db)

    result = server.list_sources()

    assert result == [{"id": 1, "name": "sharepoint-prod"}]


@pytest.mark.unit
def test_list_sources_returns_empty_list_when_db_not_connected(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_db = Mock()
    mock_db.is_connected = False
    mock_db.list_connectors = Mock(return_value=[{"id": 1, "name": "should-not-be-called"}])
    monkeypatch.setattr(db_module, "db", mock_db)

    result = server.list_sources()

    assert result == []
    mock_db.list_connectors.assert_not_called()


@pytest.mark.unit
def test_list_sources_returns_empty_list_when_db_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_db = Mock()
    mock_db.is_connected = True
    mock_db.list_connectors = Mock(side_effect=RuntimeError("db down"))
    monkeypatch.setattr(db_module, "db", mock_db)

    result = server.list_sources()

    assert result == []


@pytest.mark.unit
def test_main_parses_args_and_runs_server(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}
    monkeypatch.setattr(server._server, "run", lambda **kwargs: calls.update(kwargs))
    monkeypatch.setattr("sys.argv", ["cloud-connectors", "--host", "127.0.0.1", "--port", "5333", "--debug"])

    server._main()

    assert calls == {"host": "127.0.0.1", "port": 5333, "debug": True}


@pytest.mark.unit
def test_health_endpoint_reports_server_name(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "server": "cloud-connectors"}


@pytest.mark.unit
def test_tools_list_endpoint_includes_search_and_list_sources(client: TestClient) -> None:
    resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    tool_names = {t["name"] for t in resp.json()["result"]["tools"]}
    assert tool_names == {"search", "list_sources"}


@pytest.mark.unit
def test_tools_call_search_endpoint_returns_content(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    doc_processor = Mock()
    doc_processor.retrieve_context = Mock(return_value=[])
    monkeypatch.setattr(rag_module, "doc_processor", doc_processor)

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
    assert body["result"]["content"][0]["text"] == '{"context": "", "sources": []}'


@pytest.mark.unit
def test_tools_call_list_sources_endpoint_returns_content(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    mock_db = Mock()
    mock_db.is_connected = False
    monkeypatch.setattr(db_module, "db", mock_db)

    resp = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_sources", "arguments": {}}},
    )
    body = resp.json()
    assert body["result"]["content"][0]["text"] == "[]"
