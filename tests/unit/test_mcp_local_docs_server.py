"""Unit tests for the local-docs MCP server (mcp_servers/local_docs/server.py)."""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from mcp_servers.local_docs import server

WS = "11111111-1111-1111-1111-111111111111"
_TOKEN = "test-mcp-token"


@pytest.fixture(autouse=True)
def _configured_token(monkeypatch) -> None:
    """The MCP servers refuse every call without a shared token (audit C3)."""
    monkeypatch.setattr("mcp_servers.base._AUTH_TOKEN", _TOKEN)


@pytest.fixture
def client() -> TestClient:
    client = TestClient(server.app)
    client.headers.update({"Authorization": f"Bearer {_TOKEN}"})
    return client


def _mock_services(retrieve_results: list, documents: list) -> tuple[Mock, Mock]:
    doc_processor = Mock()
    doc_processor.retrieve_context = Mock(return_value=retrieve_results)
    doc_processor.format_context_for_llm = Mock(return_value="formatted context")
    db = Mock()
    db.get_all_documents = Mock(return_value=documents)
    return doc_processor, db


@pytest.mark.unit
def test_search_returns_context_and_sources_when_results_found(monkeypatch: pytest.MonkeyPatch) -> None:
    results = [
        ("chunk one", "report.pdf", 0, 0.9123, {"page_number": 1, "section_title": "Intro"}, "chunk-1"),
        ("chunk two", "report.pdf", 1, 0.8456, {"page_number": 2, "section_title": None}, "chunk-2"),
    ]
    doc_processor, db = _mock_services(results, [])
    monkeypatch.setattr(server, "_get_services", lambda: (doc_processor, db))

    result = server.search("what is in the report?", workspace_id=WS)

    assert result["context"] == "formatted context"
    assert result["sources"] == [
        {
            "filename": "report.pdf",
            "chunk_index": 0,
            "similarity": 0.9123,
            "page_number": 1,
            "section_title": "Intro",
            "chunk_id": "chunk-1",
        },
        {
            "filename": "report.pdf",
            "chunk_index": 1,
            "similarity": 0.8456,
            "page_number": 2,
            "section_title": None,
            "chunk_id": "chunk-2",
        },
    ]


@pytest.mark.unit
def test_search_returns_empty_context_and_sources_when_no_results(monkeypatch: pytest.MonkeyPatch) -> None:
    doc_processor, db = _mock_services([], [])
    monkeypatch.setattr(server, "_get_services", lambda: (doc_processor, db))

    result = server.search("no matches here", workspace_id=WS)

    assert result == {"context": "", "sources": []}
    doc_processor.format_context_for_llm.assert_not_called()


@pytest.mark.unit
def test_search_passes_filenames_filter_from_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    doc_processor, db = _mock_services([], [])
    monkeypatch.setattr(server, "_get_services", lambda: (doc_processor, db))

    server.search("query", filters={"filenames": ["a.pdf", "b.pdf"]}, workspace_id=WS)

    doc_processor.retrieve_context.assert_called_once_with(
        "query", filename_filter=["a.pdf", "b.pdf"], workspace_id=WS
    )


@pytest.mark.unit
def test_search_defaults_filename_filter_to_empty_list_when_filters_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc_processor, db = _mock_services([], [])
    monkeypatch.setattr(server, "_get_services", lambda: (doc_processor, db))

    server.search("query", workspace_id=WS)

    # The workspace reaches the query — the point of the finding, not a detail.
    doc_processor.retrieve_context.assert_called_once_with(
        "query", filename_filter=[], workspace_id=WS
    )


@pytest.mark.unit
def test_search_truncates_results_to_top_k(monkeypatch: pytest.MonkeyPatch) -> None:
    results = [
        (f"chunk {i}", "doc.pdf", i, 0.5, {}, f"chunk-{i}")
        for i in range(5)
    ]
    doc_processor, db = _mock_services(results, [])
    monkeypatch.setattr(server, "_get_services", lambda: (doc_processor, db))

    result = server.search("query", top_k=2, workspace_id=WS)

    assert len(result["sources"]) == 2


@pytest.mark.unit
def test_list_sources_returns_formatted_document_list(monkeypatch: pytest.MonkeyPatch) -> None:
    documents = [
        {"id": 1, "filename": "a.pdf", "chunk_count": 4, "doc_type": "pdf"},
        {"id": 2, "filename": "b.docx"},
    ]
    doc_processor, db = _mock_services([], documents)
    monkeypatch.setattr(server, "_get_services", lambda: (doc_processor, db))

    result = server.list_sources()

    assert result == [
        {"id": 1, "filename": "a.pdf", "chunk_count": 4, "doc_type": "pdf"},
        {"id": 2, "filename": "b.docx", "chunk_count": 0, "doc_type": None},
    ]


@pytest.mark.unit
def test_get_services_returns_doc_processor_and_db_singletons() -> None:
    doc_processor, db = server._get_services()

    assert doc_processor is not None
    assert db is not None
    assert hasattr(doc_processor, "retrieve_context")
    assert hasattr(db, "get_all_documents")


@pytest.mark.unit
def test_main_parses_args_and_runs_server(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}
    monkeypatch.setattr(server._server, "run", lambda **kwargs: calls.update(kwargs))
    monkeypatch.setattr("sys.argv", ["local-docs", "--host", "127.0.0.1", "--port", "5111", "--debug"])

    server._main()

    assert calls == {"host": "127.0.0.1", "port": 5111, "debug": True}


@pytest.mark.unit
def test_health_endpoint_reports_server_name(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "server": "local-docs"}


@pytest.mark.unit
def test_tools_list_endpoint_includes_search_and_list_sources(client: TestClient) -> None:
    resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    tool_names = {t["name"] for t in resp.json()["result"]["tools"]}
    assert tool_names == {"search", "list_sources"}


@pytest.mark.unit
def test_tools_call_search_endpoint_returns_content(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    doc_processor, db = _mock_services(
        [("chunk", "doc.pdf", 0, 0.7, {"page_number": None, "section_title": None}, None)], []
    )
    monkeypatch.setattr(server, "_get_services", lambda: (doc_processor, db))

    resp = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "search",
                "arguments": {"query": "test", "workspace_id": WS},
            },
        },
    )
    body = resp.json()
    assert "content" in body["result"]
    assert '"sources"' in body["result"]["content"][0]["text"]


def test_tools_call_search_over_rpc_refuses_without_a_workspace(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    """Over the wire as well as in-process: no workspace, no search."""
    doc_processor, db = _mock_services([], [])
    monkeypatch.setattr(server, "_get_services", lambda: (doc_processor, db))

    resp = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "search", "arguments": {"query": "test"}},
        },
    )
    assert "error" in resp.json()
    assert not doc_processor.retrieve_context.called


@pytest.mark.unit
def test_tools_call_list_sources_endpoint_returns_content(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    doc_processor, db = _mock_services([], [{"id": 1, "filename": "a.pdf", "chunk_count": 1, "doc_type": "pdf"}])
    monkeypatch.setattr(server, "_get_services", lambda: (doc_processor, db))

    resp = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_sources", "arguments": {}}},
    )
    body = resp.json()
    assert body["result"]["content"][0]["text"] == (
        '[{"id": 1, "filename": "a.pdf", "chunk_count": 1, "doc_type": "pdf"}]'
    )


def test_search_refuses_to_run_without_a_workspace() -> None:
    """C3 — this tool could not accept a workspace, and retrieval reads a missing
    one as "every workspace", so MCP_ENABLED=true removed isolation from chat."""
    with pytest.raises(ValueError, match="workspace_id is required"):
        server.search("anything")


def test_the_search_schema_requires_a_workspace() -> None:
    """The model is told so too, not just the handler."""
    schema = next(
        t for t in server._server._tools.values() if t["name"] == "search"
    )["inputSchema"]
    assert "workspace_id" in schema["required"]
