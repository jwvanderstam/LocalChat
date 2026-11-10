"""The active-workspace routes answer only for a workspace the caller belongs to.

`GET /api/workspaces/active` reads `X-Workspace-ID` and `POST /api/workspaces/switch` reads
`workspace_id` from the body; both needed only a session, then returned whichever workspace
was named — its name, description and system prompt — to a user with no membership in it.
Found writing R-5's header- and body-borne probes (QP-9 review).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.utils.auth import auth_headers, authenticated_state

pytestmark = pytest.mark.unit

FOREIGN = "22222222-2222-2222-2222-222222222222"
_WORKSPACE = {"id": FOREIGN, "name": "B", "description": "", "system_prompt": "B's secret prompt"}


def _client(member_role: str | None) -> tuple[TestClient, object]:
    from src.routes_fastapi.workspace_routes import router

    state = authenticated_state(member_role=member_role)
    state.db.workspaces.get.return_value = _WORKSPACE
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state = state
    client = TestClient(app, raise_server_exceptions=False)
    client.headers.update(auth_headers())
    return client, state


def test_a_non_member_is_refused_the_active_workspace():
    client, state = _client(member_role=None)
    resp = client.get("/api/workspaces/active", headers={"X-Workspace-ID": FOREIGN})
    assert resp.status_code == 403
    state.db.workspaces.get.assert_not_called()


def test_a_non_member_cannot_switch_into_a_workspace():
    client, state = _client(member_role=None)
    resp = client.post("/api/workspaces/switch", json={"workspace_id": FOREIGN})
    assert resp.status_code == 403
    state.db.workspaces.get.assert_not_called()


def test_a_member_reads_their_active_workspace():
    client, _ = _client(member_role="viewer")
    resp = client.get("/api/workspaces/active", headers={"X-Workspace-ID": FOREIGN})
    assert resp.json()["workspace"]["id"] == FOREIGN


def test_a_member_switches_into_their_workspace():
    client, _ = _client(member_role="viewer")
    resp = client.post("/api/workspaces/switch", json={"workspace_id": FOREIGN})
    assert resp.json()["workspace"]["id"] == FOREIGN
