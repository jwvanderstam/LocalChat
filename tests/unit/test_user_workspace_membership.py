"""Creating a user must produce an account that can actually be used.

The first Users screen created accounts with no workspace membership. After RBAC-1
that means the user can sign in and is then refused everything — chat, conversations,
documents all 403. A create that succeeds and a grant that never happens is worse
than a failure, because it looks like it worked.

Membership is therefore granted in the same request, and the screen shows each user's
workspace access so an account without one is visible rather than merely broken.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.utils.auth import admin_headers, authenticated_state

WS = "11111111-1111-1111-1111-111111111111"
USER = "33333333-3333-3333-3333-333333333333"


def _client():
    from src.routes_fastapi.auth_routes import router

    state = authenticated_state(role="admin")
    state.db.create_user.return_value = USER
    state.db.get_user_by_id.return_value = {"id": USER, "username": "jo", "role": "user"}
    state.db.get_user_workspaces.return_value = [{"id": WS, "name": "Default", "role": "editor"}]
    state.db.remove_workspace_member.return_value = True
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state = state
    client = TestClient(app, raise_server_exceptions=False)
    client.headers.update(admin_headers())
    return client


@pytest.mark.unit
class TestCreateGrantsMembership:
    def test_membership_is_granted_in_the_same_request(self):
        client = _client()
        client.post("/api/users", json={
            "username": "jo", "password": "pw",
            "workspace_id": WS, "workspace_role": "editor",
        })
        client.app.state.db.add_workspace_member.assert_called_once_with(WS, USER, "editor")

    def test_the_requested_workspace_role_is_used(self):
        client = _client()
        client.post("/api/users", json={
            "username": "jo", "password": "pw", "workspace_id": WS, "workspace_role": "viewer",
        })
        assert client.app.state.db.add_workspace_member.call_args[0][2] == "viewer"

    def test_creating_without_a_workspace_still_works(self):
        """Not every caller has one to give — the API stays usable, the UI insists."""
        client = _client()
        resp = client.post("/api/users", json={"username": "jo", "password": "pw"})
        assert resp.status_code == 201
        client.app.state.db.add_workspace_member.assert_not_called()

    def test_an_invalid_workspace_role_is_refused(self):
        client = _client()
        resp = client.post("/api/users", json={
            "username": "jo", "password": "pw", "workspace_id": WS, "workspace_role": "root",
        })
        assert resp.status_code == 400

    def test_an_invalid_role_creates_no_user(self):
        """Validation must precede the write, or a rejected request still leaves a row."""
        client = _client()
        client.post("/api/users", json={
            "username": "jo", "password": "pw", "workspace_id": WS, "workspace_role": "root",
        })
        client.app.state.db.create_user.assert_not_called()


@pytest.mark.unit
class TestMembershipManagement:
    def test_a_users_workspaces_can_be_listed(self):
        resp = _client().get(f"/api/users/{USER}/workspaces")
        assert resp.json()["workspaces"][0]["name"] == "Default"

    def test_access_can_be_granted_afterwards(self):
        client = _client()
        client.post(f"/api/users/{USER}/workspaces", json={"workspace_id": WS, "role": "owner"})
        client.app.state.db.add_workspace_member.assert_called_once_with(WS, USER, "owner")

    def test_access_can_be_revoked(self):
        client = _client()
        resp = client.delete(f"/api/users/{USER}/workspaces/{WS}")
        assert resp.status_code == 200

    def test_revoking_a_missing_membership_is_404(self):
        client = _client()
        client.app.state.db.remove_workspace_member.return_value = False
        assert client.delete(f"/api/users/{USER}/workspaces/{WS}").status_code == 404

    def test_removing_the_last_owner_is_refused_with_409(self):
        """remove_workspace_member raises ValueError rather than stranding a workspace."""
        client = _client()
        client.app.state.db.remove_workspace_member.side_effect = ValueError(
            "Cannot remove the last owner")
        resp = client.delete(f"/api/users/{USER}/workspaces/{WS}")
        assert resp.status_code == 409 and "last owner" in resp.json()["message"]

    def test_granting_without_a_workspace_id_is_refused(self):
        resp = _client().post(f"/api/users/{USER}/workspaces", json={"role": "editor"})
        assert resp.status_code == 400


@pytest.mark.unit
class TestFallbackPicksAUsableWorkspace:
    """A fresh session sends no X-Workspace-ID, and the fallback decides what happens.

    Falling straight to the global default meant a user granted access to a *second*
    workspace was refused everything until they switched manually — which on first
    login they had no way to discover. Granting membership appeared not to work.
    """

    def _request(self, *, member_of, default_ws):
        from unittest.mock import MagicMock

        from fastapi import Request

        db = MagicMock()
        db.is_connected = True
        db.get_default_workspace_id.return_value = default_ws
        db.get_user_workspaces.return_value = [{"id": w} for w in member_of]
        db.get_workspace_member_role.side_effect = (
            lambda ws, uid: "editor" if ws in member_of else None
        )
        scope = {
            "type": "http", "headers": [], "query_string": b"",
            "path": "/api/documents/list", "method": "GET", "app": MagicMock(),
        }
        req = Request(scope)
        req.scope["app"].state.db = db
        return req, db

    def test_a_member_of_only_a_second_workspace_is_allowed(self):
        from unittest.mock import patch

        from src.security_fastapi import check_workspace_access, create_access_token

        req, _ = self._request(member_of=["ws-other"], default_ws="ws-default")
        token = create_access_token(USER, {"role": "user"})
        req.scope["headers"] = [(b"authorization", f"Bearer {token}".encode())]
        with patch("src.security_fastapi._ADMIN_PASSWORD_RAW", "live"):
            assert check_workspace_access(req, None, "viewer") is None

    def test_a_user_with_no_membership_is_still_refused(self):
        from unittest.mock import patch

        from src.security_fastapi import check_workspace_access, create_access_token

        req, _ = self._request(member_of=[], default_ws="ws-default")
        token = create_access_token(USER, {"role": "user"})
        req.scope["headers"] = [(b"authorization", f"Bearer {token}".encode())]
        with patch("src.security_fastapi._ADMIN_PASSWORD_RAW", "live"):
            denial = check_workspace_access(req, None, "viewer")
        assert denial is not None and denial[0] == 403

    def test_lookup_failure_falls_through_to_the_default(self):
        """A convenience for an omitted header must not become a way to deny requests."""
        from unittest.mock import patch

        from src.security_fastapi import check_workspace_access, create_access_token

        req, db = self._request(member_of=["ws-default"], default_ws="ws-default")
        db.get_user_workspaces.side_effect = RuntimeError("db blip")
        token = create_access_token(USER, {"role": "user"})
        req.scope["headers"] = [(b"authorization", f"Bearer {token}".encode())]
        with patch("src.security_fastapi._ADMIN_PASSWORD_RAW", "live"):
            assert check_workspace_access(req, None, "viewer") is None
