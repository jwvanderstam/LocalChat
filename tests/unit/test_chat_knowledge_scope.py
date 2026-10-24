"""GKB-3 — chat can read the global knowledge tier, and a workspace API key cannot.

GKB-1 built the tier and GKB-2 fills it, but no chat request could reach it: retrieval
took `knowledge_scope` and nothing exposed it, so a contribution was stored and never
used in an answer. The chat request now carries it, a key asking for anything but the
workspace's own documents is refused (2026-10-09), and a citation says which tier it
came from.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.db.workspace_keys import generate_api_key
from src.models import ChatRequest
from src.rag.retrieval import RetrievalResult
from src.security_fastapi import check_knowledge_scope_access
from src.services import chat
from tests.utils.auth import auth_headers, authenticated_state

pytestmark = pytest.mark.unit

WS = "11111111-1111-1111-1111-111111111111"
_KEY_REFUSAL = (403, "API key is not valid for the global knowledge tier")


class TestTheRequestField:
    def test_it_defaults_to_the_workspace_alone(self):
        assert ChatRequest(message="hi").knowledge_scope == "local"

    @pytest.mark.parametrize("value", ["local", "global", "hybrid"])
    def test_each_tier_is_accepted(self, value):
        assert ChatRequest(message="hi", knowledge_scope=value).knowledge_scope == value

    def test_anything_else_is_refused(self):
        with pytest.raises(ValidationError):
            ChatRequest(message="hi", knowledge_scope="everything")


def _request(headers: dict[str, str]) -> MagicMock:
    request = MagicMock()
    request.headers = headers
    return request


class TestTheCheck:
    @pytest.mark.parametrize("scope", ["global", "hybrid"])
    def test_a_key_asking_beyond_its_workspace_is_refused(self, scope):
        key, _, _ = generate_api_key()
        request = _request({"Authorization": f"Bearer {key}"})
        assert check_knowledge_scope_access(request, scope) == _KEY_REFUSAL

    def test_a_key_asking_for_its_own_workspace_passes(self):
        key, _, _ = generate_api_key()
        assert check_knowledge_scope_access(_request({"Authorization": f"Bearer {key}"}), "local") is None

    @pytest.mark.parametrize("scope", ["global", "hybrid"])
    def test_a_signed_in_user_may_read_the_tier(self, scope):
        assert check_knowledge_scope_access(_request(auth_headers()), scope) is None


def _client(state: MagicMock) -> TestClient:
    from src.routes_fastapi.api_routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state = state
    state.doc_processor.retrieve_context.return_value = []
    return TestClient(app, raise_server_exceptions=False)


def _post(client: TestClient, body: dict, headers: dict[str, str]):
    with patch("src.routes_fastapi.api_routes.config") as cfg, \
         patch("src.services.chat.config") as chat_cfg:
        cfg.app_state.get_active_model.return_value = "llama3.2"
        for c in (cfg, chat_cfg):
            c.WEB_SEARCH_ENABLED = False
            c.MCP_ENABLED = False
            c.AGGREGATOR_AGENT_ENABLED = False
            c.QUERY_PLANNER_ENABLED = False
            c.LONG_TERM_MEMORY_ENABLED = False
        return client.post("/api/chat", json=body, headers=headers)


class TestTheChatRoute:
    def test_a_key_asking_for_the_global_tier_is_refused_before_any_retrieval(self):
        state = authenticated_state()
        state.db.api_keys.resolve.return_value = (WS, "editor")
        client = _client(state)
        key, _, _ = generate_api_key()
        resp = _post(client, {"message": "what did other projects learn?", "knowledge_scope": "global"},
                     {"Authorization": f"Bearer {key}"})
        assert (resp.status_code, resp.json()["message"], state.doc_processor.retrieve_context.called) == (
            403, _KEY_REFUSAL[1], False)

    def test_a_signed_in_user_asking_hybrid_reaches_retrieval_with_it(self):
        state = authenticated_state(workspaces=[{"id": WS}])
        client = _client(state)
        _post(client, {"message": "what did other projects learn?", "knowledge_scope": "hybrid"},
              auth_headers(**{"X-Workspace-ID": WS}))
        assert state.doc_processor.retrieve_context.call_args.kwargs["knowledge_scope"] == "hybrid"

    def test_a_request_that_names_no_tier_retrieves_locally(self):
        state = authenticated_state(workspaces=[{"id": WS}])
        client = _client(state)
        _post(client, {"message": "what is in our documents?"}, auth_headers(**{"X-Workspace-ID": WS}))
        assert state.doc_processor.retrieve_context.call_args.kwargs["knowledge_scope"] == "local"


def _result(filename: str, tier: str | None) -> RetrievalResult:
    metadata = {"knowledge_tier": tier} if tier else {}
    return RetrievalResult("text", filename, 0, 0.8, metadata, 1)


class TestTheService:
    def test_each_source_names_its_tier(self):
        processor = MagicMock()
        processor.retrieve_context.return_value = [_result("ours.md", None), _result("theirs.md", "global")]
        processor.format_context_for_llm.return_value = "ctx"
        with patch.object(chat.config, "MCP_ENABLED", False):
            _, sources = chat.get_rag_context("q", processor, [0], scope=WS, knowledge_scope="hybrid")
        assert [(s["filename"], s["knowledge_tier"]) for s in sources] == [
            ("ours.md", "local"), ("theirs.md", "global")]

    def test_a_global_question_does_not_go_through_mcp(self):
        """MCP's search reads one workspace; the tier would be dropped silently."""
        processor = MagicMock()
        processor.retrieve_context.return_value = []
        with patch.object(chat.config, "MCP_ENABLED", True), \
             patch.object(chat, "try_mcp_rag") as mcp:
            chat.get_rag_context("q", processor, [0], scope=WS, knowledge_scope="global")
        assert (mcp.called, processor.retrieve_context.call_args.kwargs["knowledge_scope"]) == (False, "global")

    def test_a_local_question_still_goes_through_mcp(self):
        processor = MagicMock()
        with patch.object(chat.config, "MCP_ENABLED", True), \
             patch.object(chat, "try_mcp_rag", return_value=("ctx", [])) as mcp:
            chat.get_rag_context("q", processor, [0], scope=WS, knowledge_scope="local")
        assert mcp.called is True

    def test_a_hybrid_question_does_not_go_through_the_aggregator(self):
        fields = {"use_rag": True, "enhance": False, "message": "q", "knowledge_scope": "hybrid",
                  "conversation_id": None}
        processor = MagicMock()
        processor.retrieve_context.return_value = []
        db = MagicMock()
        with patch.object(chat.config, "AGGREGATOR_AGENT_ENABLED", True), \
             patch.object(chat.config, "MCP_ENABLED", False), \
             patch.object(chat, "retrieve_via_aggregator") as agg, \
             patch.object(chat, "get_filename_filter", return_value=[]):
            chat.retrieve_contexts(fields, processor, db, [0], scope=WS)
        assert (agg.called, processor.retrieve_context.call_args.kwargs["knowledge_scope"]) == (False, "hybrid")
