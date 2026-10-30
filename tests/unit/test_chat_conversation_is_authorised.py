"""R-3 (QP-9 review) — chat refuses a conversation outside the caller's workspace.

`POST /api/chat` took `conversation_id` from the body and appended both turns to it on an
all-workspaces connection, without asking whose it was. A viewer of workspace A who knew a
conversation id in B wrote into B's history, and memory extraction then read that turn as
B's own user speaking. The id is now checked against the authorised scope before any
retrieval, and the write itself is bounded by the scope.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.utils.auth import auth_headers, authenticated_state

pytestmark = pytest.mark.unit

OWN = "11111111-1111-1111-1111-111111111111"
CONVERSATION = "55555555-5555-5555-5555-555555555555"


def _post(document_filter: list[str] | None) -> tuple[int, MagicMock]:
    """Chat in OWN naming CONVERSATION, which the database reports as *document_filter*."""
    from src.routes_fastapi.api_routes import router

    state = authenticated_state(member_role="viewer", workspaces=[{"id": OWN}])
    state.db.conversations.document_filter.return_value = document_filter
    state.doc_processor.retrieve_context.return_value = []
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state = state
    client = TestClient(app, raise_server_exceptions=False)

    with patch("src.routes_fastapi.api_routes.config") as cfg, \
         patch("src.services.chat.config") as chat_cfg:
        cfg.app_state.get_active_model.return_value = "llama3.2"
        for c in (cfg, chat_cfg):
            c.WEB_SEARCH_ENABLED = False
            c.MCP_ENABLED = False
            c.AGGREGATOR_AGENT_ENABLED = False
            c.QUERY_PLANNER_ENABLED = False
            c.LONG_TERM_MEMORY_ENABLED = False
        resp = client.post(
            "/api/chat",
            json={"message": "hello", "conversation_id": CONVERSATION},
            headers=auth_headers(**{"X-Workspace-ID": OWN}),
        )
    return resp.status_code, state


def test_a_conversation_outside_the_scope_is_not_found():
    status, _ = _post(document_filter=None)
    assert status == 404


def test_a_conversation_outside_the_scope_is_refused_before_retrieval():
    _, state = _post(document_filter=None)
    state.doc_processor.retrieve_context.assert_not_called()


def test_a_conversation_outside_the_scope_gets_no_message_written():
    _, state = _post(document_filter=None)
    state.db.conversations.save_message.assert_not_called()


def test_the_conversation_is_looked_up_in_the_authorised_scope():
    _, state = _post(document_filter=None)
    assert state.db.conversations.document_filter.call_args.kwargs["scope"] == OWN


def test_the_callers_own_conversation_is_answered():
    # The permitted case: without it the refusals above would pass on a route that
    # refuses every conversation.
    status, _ = _post(document_filter=[])
    assert status == 200
