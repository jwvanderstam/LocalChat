"""GKB-2 — who may write the global knowledge tier, and what the routes hand the database.

The tier is read by every workspace, so the guards are the point. Contributing needs a
global admin even from a workspace's owner: any user can create a workspace and own it,
so ``ws:owner`` alone would let anyone publish to everyone. Withdrawing only narrows the
tier, so the owner may do that alone.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.utils.auth import (
    ADMIN_ID,
    USER_ID,
    admin_headers,
    auth_headers,
    authenticated_state,
)

pytestmark = pytest.mark.unit

WS = "11111111-1111-1111-1111-111111111111"
CONTRIBUTED = [{"document_id": 7, "global_document_id": 70, "filename": "retro.md",
                "chunks": 3, "updated": False}]


def _client(*, role: str, member_role: str | None, headers: dict[str, str]) -> TestClient:
    from src.routes_fastapi.gkb_routes import router

    state = authenticated_state(role=role, member_role=member_role)
    state.db.workspaces.get.return_value = {"id": WS, "name": "Project A"}
    state.db.contribute_documents.return_value = CONTRIBUTED
    state.db.archive_contributions.return_value = 2
    state.db.list_contributions.return_value = [{"id": 70, "filename": "retro.md"}]
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state = state
    client = TestClient(app, raise_server_exceptions=False)
    client.headers.update(headers)
    return client


def _admin() -> TestClient:
    return _client(role="admin", member_role=None, headers=admin_headers())


def _owner() -> TestClient:
    return _client(role="user", member_role="owner", headers=auth_headers())


class TestContribute:
    def test_an_admin_contributes_and_is_recorded_as_the_contributor(self):
        client = _admin()
        resp = client.post(f"/api/workspaces/{WS}/contribute", json={"document_ids": [7]})
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "contributed": CONTRIBUTED}
        client.app.state.db.contribute_documents.assert_called_once_with(WS, [7], ADMIN_ID)

    def test_a_workspace_owner_who_is_not_an_admin_is_refused(self):
        client = _owner()
        resp = client.post(f"/api/workspaces/{WS}/contribute", json={"document_ids": [7]})
        assert resp.status_code == 403
        client.app.state.db.contribute_documents.assert_not_called()

    def test_a_workspace_api_key_is_refused(self):
        client = _client(role="user", member_role=None, headers={"X-API-Key": "lcw_bridge"})
        client.app.state.db.api_keys.resolve.return_value = (WS, "editor")
        resp = client.post(f"/api/workspaces/{WS}/contribute", json={"document_ids": [7]})
        assert resp.status_code == 401
        client.app.state.db.contribute_documents.assert_not_called()

    @pytest.mark.parametrize("body", [
        {"document_ids": []},
        {"document_ids": list(range(1, 102))},
        {"document_ids": ["retro.md"]},
        {},
    ], ids=["empty", "over-the-cap", "not-ids", "missing"])
    def test_a_malformed_selection_is_refused_before_the_database(self, body):
        client = _admin()
        resp = client.post(f"/api/workspaces/{WS}/contribute", json=body)
        assert resp.status_code == 400
        client.app.state.db.contribute_documents.assert_not_called()

    def test_the_cap_itself_is_accepted(self):
        client = _admin()
        resp = client.post(f"/api/workspaces/{WS}/contribute",
                           json={"document_ids": list(range(1, 101))})
        assert resp.status_code == 200

    def test_a_document_outside_the_workspace_is_not_found(self):
        client = _admin()
        client.app.state.db.contribute_documents.return_value = None
        resp = client.post(f"/api/workspaces/{WS}/contribute", json={"document_ids": [7, 8]})
        assert resp.status_code == 404

    def test_an_unknown_workspace_is_not_found_and_nothing_is_copied(self):
        client = _admin()
        client.app.state.db.workspaces.get.return_value = None
        resp = client.post(f"/api/workspaces/{WS}/contribute", json={"document_ids": [7]})
        assert resp.status_code == 404
        client.app.state.db.contribute_documents.assert_not_called()


class TestArchive:
    def test_the_owner_withdraws_and_is_recorded_as_the_archiver(self):
        client = _owner()
        resp = client.delete(f"/api/workspaces/{WS}/contributions")
        assert resp.json() == {"success": True, "archived": 2}
        client.app.state.db.archive_contributions.assert_called_once_with(WS, USER_ID)

    def test_an_editor_is_refused(self):
        client = _client(role="user", member_role="editor", headers=auth_headers())
        resp = client.delete(f"/api/workspaces/{WS}/contributions")
        assert resp.status_code == 403
        client.app.state.db.archive_contributions.assert_not_called()


@pytest.mark.parametrize(("method", "path", "db_call"), [
    ("post", f"/api/workspaces/{WS}/contribute", "contribute_documents"),
    ("delete", f"/api/workspaces/{WS}/contributions", "archive_contributions"),
    ("get", "/api/gkb/documents", "list_contributions"),
], ids=["contribute", "archive", "list"])
def test_a_database_failure_is_a_500_that_names_nothing(method, path, db_call):
    client = _admin()
    getattr(client.app.state.db, db_call).side_effect = RuntimeError("relation documents: secret")
    kwargs = {"json": {"document_ids": [7]}} if method == "post" else {}
    resp = getattr(client, method)(path, **kwargs)
    assert (resp.status_code, resp.json()) == (
        500, {"success": False, "message": "Internal server error"})


class TestList:
    def test_an_admin_sees_every_contribution(self):
        resp = _admin().get("/api/gkb/documents")
        assert resp.json() == {"success": True, "documents": [{"id": 70, "filename": "retro.md"}]}

    def test_a_plain_user_is_refused(self):
        client = _owner()
        resp = client.get("/api/gkb/documents")
        assert resp.status_code == 403
        client.app.state.db.list_contributions.assert_not_called()
