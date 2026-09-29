"""The aggregator's worker threads see the request's workspace scope.

`ToolRouter._local_docs` reads the scope from a contextvar the request binds (P0-2), and
`AggregatorAgent` dispatches tools on a `ThreadPoolExecutor`. A contextvar does not follow a
plain `pool.submit`, so with `AGGREGATOR_AGENT_ENABLED=true` every local-docs job raised
`ScopeUnavailableError` in its thread: fail-closed, nothing leaked, but retrieval came back
empty and marked partial on every request.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.agent.aggregator import AggregatorAgent
from src.utils.scope import request_scope

pytestmark = pytest.mark.unit

WS = "11111111-1111-1111-1111-111111111111"


def _run_local_docs(queries: int = 1):
    """Run the aggregator on local_docs with WS bound; return the workspaces retrieval saw."""
    seen: list = []

    def _retrieve(query, **kwargs):
        seen.append(kwargs.get("workspace_id"))
        return []

    with patch("src.config.MCP_ENABLED", False), \
         patch("src.rag.processor.doc_processor.retrieve_context", side_effect=_retrieve), \
         request_scope(WS):
        from src.rag.planner import QueryPlan

        plan = None
        if queries > 1:
            plan = QueryPlan(
                intent="multi_hop",
                sub_questions=[f"q{i}" for i in range(queries)],
                tools=["local_docs"],
            )
        result = AggregatorAgent().run("q", plan=plan, tools=["local_docs"], max_retries=0)
    return seen, result


def test_a_worker_thread_retrieves_in_the_request_workspace():
    seen, result = _run_local_docs()
    assert seen == [WS]
    assert result.partial is False


def test_every_parallel_job_carries_the_scope():
    seen, result = _run_local_docs(queries=3)
    assert seen == [WS, WS, WS]
    assert result.partial is False


def test_chat_with_the_aggregator_retrieves_in_the_callers_workspace():
    """The whole path, not just the thread: the route used to bind the scope only for the
    stream, after retrieval had already run, so there was nothing for a worker to copy."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.routes_fastapi.api_routes import router
    from tests.utils.auth import auth_headers, authenticated_state

    state = authenticated_state(role="user", member_role="viewer", workspaces=[{"id": WS}])
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state = state
    seen: list = []

    def _retrieve(query, **kwargs):
        seen.append(kwargs.get("workspace_id"))
        return []

    with patch("src.routes_fastapi.api_routes.config") as cfg, \
         patch("src.services.chat.config") as chat_cfg, \
         patch("src.config.MCP_ENABLED", False), \
         patch("src.rag.processor.doc_processor.retrieve_context", side_effect=_retrieve):
        cfg.app_state.get_active_model.return_value = "llama3.2"
        for c in (cfg, chat_cfg):
            c.WEB_SEARCH_ENABLED = False
            c.MCP_ENABLED = False
            c.QUERY_PLANNER_ENABLED = False
            c.LONG_TERM_MEMORY_ENABLED = False
        chat_cfg.AGGREGATOR_AGENT_ENABLED = True
        chat_cfg.TOP_K_RESULTS = 5
        chat_cfg.AGENT_MAX_RETRIES = 0
        TestClient(app, raise_server_exceptions=False).post(
            "/api/chat",
            json={"message": "what is in the report?", "use_rag": True},
            headers=auth_headers(**{"X-Workspace-ID": WS}),
        )

    assert seen == [WS]
