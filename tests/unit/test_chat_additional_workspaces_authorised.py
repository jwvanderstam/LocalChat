"""Chat's ``additional_workspace_ids`` are authorised, not trusted.

The workspace guard authorised the request's own workspace and nothing else, and the
extra ids went straight into document and memory retrieval. Any caller who knew a
workspace's id could therefore retrieve from it through chat — a workspace API key
included, whose scope is documented as impossible to widen.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.db.workspace_keys import generate_api_key
from src.security_fastapi import check_additional_workspace_access
from tests.utils.auth import admin_headers, auth_headers, authenticated_state

pytestmark = pytest.mark.unit

OWN = "11111111-1111-1111-1111-111111111111"
SHARED = "22222222-2222-2222-2222-222222222222"
FOREIGN = "33333333-3333-3333-3333-333333333333"


def _state(role: str = "user") -> MagicMock:
    """A plain user who is a viewer of OWN and SHARED and a member of nothing else."""
    state = authenticated_state(role=role, workspaces=[{"id": OWN}])
    roles = {OWN: "viewer", SHARED: "viewer"}
    state.db.get_workspace_member_role.side_effect = lambda ws, _user: roles.get(ws)
    return state


def _request(state: MagicMock, headers: dict[str, str]) -> MagicMock:
    request = MagicMock()
    request.app.state = state
    request.headers = headers
    return request


class TestTheCheck:
    def test_no_additional_workspaces_needs_no_lookup(self):
        state = _state()
        assert check_additional_workspace_access(_request(state, auth_headers()), [], "viewer") is None
        state.db.get_workspace_member_role.assert_not_called()

    def test_a_workspace_the_caller_belongs_to_is_allowed(self):
        state = _state()
        assert check_additional_workspace_access(_request(state, auth_headers()), [SHARED], "viewer") is None

    def test_one_foreign_workspace_refuses_the_whole_request(self):
        state = _state()
        denial = check_additional_workspace_access(
            _request(state, auth_headers()), [SHARED, FOREIGN], "viewer"
        )
        assert denial is not None and denial[0] == 403

    def test_an_admin_may_name_any_workspace(self):
        state = _state(role="admin")
        assert check_additional_workspace_access(_request(state, admin_headers()), [FOREIGN], "viewer") is None

    def test_a_workspace_api_key_may_name_none(self):
        state = _state()
        key, _, _ = generate_api_key()
        denial = check_additional_workspace_access(
            _request(state, {"Authorization": f"Bearer {key}"}), [SHARED], "viewer"
        )
        assert denial is not None and denial[0] == 403


def _chat_client(state: MagicMock) -> tuple[FastAPI, TestClient]:
    from src.routes_fastapi.api_routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state = state
    state.doc_processor.retrieve_context.return_value = []
    return app, TestClient(app, raise_server_exceptions=False)


class TestTheChatRoute:
    def test_a_foreign_workspace_is_refused_before_any_retrieval(self):
        state = _state()
        _, client = _chat_client(state)

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
                json={"message": "what are the salaries?", "additional_workspace_ids": [FOREIGN]},
                headers=auth_headers(**{"X-Workspace-ID": OWN}),
            )

        assert resp.status_code == 403
        state.doc_processor.retrieve_context.assert_not_called()
