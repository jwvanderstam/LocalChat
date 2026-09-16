"""P0-2 — enabling MCP must not remove workspace isolation, and must not be open.

Audit finding C3, three separate holes that only together made it exploitable:

1. `get_rag_context` dropped `workspace_id` when `MCP_ENABLED=true` and returned the
   MCP result, so chat retrieval stopped being workspace-scoped the moment the flag
   was turned on.
2. The MCP `search()` tool could not accept a workspace at all, and retrieval reads a
   missing workspace as *every* workspace.
3. The MCP servers had no authentication of any kind — whatever reached `POST /mcp`
   was served, from a process sitting on the same network as the database.

Decision D4 kept the servers and authorised them, rather than removing them.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from mcp_servers.base import MCPServer
from src.utils.scope import (
    ALL_WORKSPACES,
    ScopeUnavailableError,
    current_request_scope,
    request_scope,
)

WS = "11111111-1111-1111-1111-111111111111"
OTHER_WS = "22222222-2222-2222-2222-222222222222"
TOKEN = "a-shared-secret"


@pytest.mark.unit
class TestTheServersAreNotOpen:
    """Hole 3. They hold no session and no user, so the token is all there is."""

    def _server(self) -> MCPServer:
        srv = MCPServer("fixture")
        srv.register_tool(
            name="echo",
            description="echo",
            input_schema={"type": "object", "properties": {}},
            handler=lambda: {"ok": True},
        )
        return srv

    def test_an_unconfigured_server_serves_nobody(self, monkeypatch):
        """Unset is closed, not open — the opposite would restore the finding."""
        monkeypatch.setattr("mcp_servers.base._AUTH_TOKEN", "")
        client = TestClient(self._server().get_asgi_app())
        resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert resp.status_code == 401

    def test_a_configured_server_still_refuses_the_wrong_token(self, monkeypatch):
        monkeypatch.setattr("mcp_servers.base._AUTH_TOKEN", TOKEN)
        client = TestClient(self._server().get_asgi_app())
        client.headers.update({"Authorization": "Bearer wrong"})
        resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert resp.status_code == 401

    def test_the_right_token_is_accepted(self, monkeypatch):
        """The negative space: refusing everything would satisfy the two above."""
        monkeypatch.setattr("mcp_servers.base._AUTH_TOKEN", TOKEN)
        client = TestClient(self._server().get_asgi_app())
        client.headers.update({"Authorization": f"Bearer {TOKEN}"})
        resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert resp.status_code == 200
        assert resp.json()["result"]["tools"][0]["name"] == "echo"

    def test_a_bare_token_without_the_bearer_scheme_is_refused(self, monkeypatch):
        monkeypatch.setattr("mcp_servers.base._AUTH_TOKEN", TOKEN)
        client = TestClient(self._server().get_asgi_app())
        client.headers.update({"Authorization": TOKEN})
        resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert resp.status_code == 401


@pytest.mark.unit
class TestEnablingMcpDoesNotWidenTheScope:
    """Hole 1. The flag changed where retrieval happened *and* what it could see."""

    def _chat_module(self):
        from src.services import chat

        return chat

    def test_the_workspace_reaches_the_mcp_search(self):
        chat = self._chat_module()
        registry = MagicMock()
        registry.local_docs.call_tool.return_value = {"context": "ctx", "sources": []}

        with patch.dict("sys.modules", {}), patch("src.mcp_client.mcp_registry", registry):
            chat.try_mcp_rag("q", [], [0], WS)

        arguments = registry.local_docs.call_tool.call_args[0][1]
        assert arguments["workspace_id"] == WS

    def test_an_unscoped_chat_request_does_not_go_through_mcp(self):
        """No workspace, no MCP: it falls through to the direct path, which scopes."""
        chat = self._chat_module()
        doc_processor = MagicMock()
        doc_processor.retrieve_context.return_value = []

        with (
            patch.object(chat.config, "MCP_ENABLED", True),
            patch.object(chat, "try_mcp_rag") as mcp_call,
        ):
            chat.get_rag_context("q", doc_processor, [0], workspace_id=None)

        assert not mcp_call.called
        assert doc_processor.retrieve_context.called


@pytest.mark.unit
class TestTheSearchToolRequiresAWorkspace:
    """Hole 2, on both servers that retrieve."""

    def test_local_docs_refuses_without_one(self):
        from mcp_servers.local_docs import server

        with pytest.raises(ValueError, match="workspace_id is required"):
            server.search("anything")

    def test_cloud_connectors_refuses_without_one(self):
        from mcp_servers.cloud_connectors import server

        with pytest.raises(ValueError, match="workspace_id is required"):
            server.search("anything")

    def test_both_schemas_tell_the_model_it_is_required(self):
        """A handler that refuses is right; a schema that omits it invites the failure."""
        from mcp_servers.cloud_connectors import server as cloud
        from mcp_servers.local_docs import server as local

        for module in (local, cloud):
            schema = next(
                t for t in module._server._tools.values() if t["name"] == "search"
            )["inputSchema"]
            assert "workspace_id" in schema["required"]


@pytest.mark.unit
class TestToolsReadTheRequestScope:
    """The LLM calls these mid-answer, so there is no argument to carry a workspace."""

    def test_the_bound_scope_is_what_they_read(self):
        with request_scope(WS):
            assert current_request_scope() == WS

    def test_nesting_restores_the_outer_scope(self):
        with request_scope(WS):
            with request_scope(OTHER_WS):
                assert current_request_scope() == OTHER_WS
            assert current_request_scope() == WS

    def test_reading_it_unbound_raises_rather_than_meaning_everything(self):
        with pytest.raises(ScopeUnavailableError):
            current_request_scope()

    def test_an_admin_scope_is_said_out_loud(self):
        """Installation-wide is reachable, but only by naming it."""
        with request_scope(ALL_WORKSPACES):
            assert current_request_scope() is ALL_WORKSPACES

    def test_the_document_search_tool_refuses_outside_a_request(self):
        from src.tools.registry import tool_registry

        with pytest.raises(ScopeUnavailableError):
            tool_registry.execute("search_documents", {"query": "anything"})

    def test_the_tool_router_scopes_its_direct_retrieval(self):
        from src.agent.tool_router import ToolRouter

        doc_processor = MagicMock()
        doc_processor.retrieve_context.return_value = []
        with (
            patch("src.rag.processor.doc_processor", doc_processor),
            request_scope(WS),
        ):
            ToolRouter()._local_docs("q", None, 5)

        assert doc_processor.retrieve_context.call_args.kwargs["workspace_id"] == WS
