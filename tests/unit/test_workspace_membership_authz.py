"""BUG-3 regression tests — workspace membership authorisation.

Before the fix, five routes were reachable without workspace membership:

* ``GET``/``POST /api/workspaces/{id}/members`` had no authorisation check at all,
  so an unauthenticated caller could enumerate members and add themselves as owner.
* ``DELETE /api/workspaces/{id}`` and the member ``PUT``/``DELETE`` checked
  ``if role is not None and role != "owner"`` — a non-member gets ``role is None``,
  skips the branch, and proceeds. Non-membership granted access.

Every test here sets ``testing = False`` and patches ``_ADMIN_PASSWORD_RAW`` so the
RBAC bypass is off; the existing suite runs with ``testing = True``, which short-circuits
every check and is why these routes were never covered.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.routes_fastapi.workspace_routes import router
from src.security_fastapi import create_access_token

WS = "11111111-1111-1111-1111-111111111111"
OTHER_USER = "22222222-2222-2222-2222-222222222222"


def _client(member_role: str | None) -> TestClient:
    """App whose caller has *member_role* in workspace WS (None = not a member)."""
    state = MagicMock()
    state.db.is_connected = True
    state.db.get_workspace_member_role.return_value = member_role
    state.db.list_workspace_members.return_value = [{"user_id": OTHER_USER, "role": "owner"}]
    state.db.delete_workspace.return_value = True
    state.db.get_default_workspace_id.return_value = "ws-default"
    state.db.remove_workspace_member.return_value = True

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state = state
    return TestClient(app, raise_server_exceptions=True)


def _auth(role: str = "user") -> dict[str, str]:
    token = create_access_token("33333333-3333-3333-3333-333333333333", {"role": role})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _rbac_on():
    """Force the real authorisation path; an empty admin password bypasses everything."""
    # DEMO_MODE is gone (SEC-1); only the admin-password branch remains to neutralise.
    with patch("src.security_fastapi._ADMIN_PASSWORD_RAW", "set-so-rbac-is-live"):
        yield


@pytest.mark.unit
class TestUnauthenticatedIsRejected:
    def test_add_member_without_token_is_401(self):
        """The privilege-escalation path: no token, no check, self-added as owner."""
        client = _client(member_role=None)
        resp = client.post(f"/api/workspaces/{WS}/members", json={"user_id": OTHER_USER, "role": "owner"})
        assert resp.status_code == 401

    def test_add_member_without_token_does_not_write(self):
        client = _client(member_role=None)
        client.post(f"/api/workspaces/{WS}/members", json={"user_id": OTHER_USER, "role": "owner"})
        client.app.state.db.add_workspace_member.assert_not_called()

    def test_list_members_without_token_is_401(self):
        client = _client(member_role=None)
        resp = client.get(f"/api/workspaces/{WS}/members")
        assert resp.status_code == 401

    def test_list_members_without_token_leaks_nothing(self):
        client = _client(member_role=None)
        resp = client.get(f"/api/workspaces/{WS}/members")
        assert OTHER_USER not in resp.text

    def test_delete_workspace_without_token_is_401(self):
        client = _client(member_role=None)
        resp = client.delete(f"/api/workspaces/{WS}")
        assert resp.status_code == 401


@pytest.mark.unit
class TestAuthenticatedNonMemberIsRejected:
    """The hole that needed no unauthenticated access: a real user, not a member."""

    def test_delete_workspace_as_non_member_is_403(self):
        client = _client(member_role=None)
        resp = client.delete(f"/api/workspaces/{WS}", headers=_auth())
        assert resp.status_code == 403

    def test_delete_workspace_as_non_member_does_not_delete(self):
        client = _client(member_role=None)
        client.delete(f"/api/workspaces/{WS}", headers=_auth())
        client.app.state.db.delete_workspace.assert_not_called()

    def test_add_member_as_non_member_is_403(self):
        client = _client(member_role=None)
        resp = client.post(
            f"/api/workspaces/{WS}/members",
            json={"user_id": OTHER_USER, "role": "owner"},
            headers=_auth(),
        )
        assert resp.status_code == 403

    def test_update_member_as_non_member_is_403(self):
        client = _client(member_role=None)
        resp = client.put(
            f"/api/workspaces/{WS}/members/{OTHER_USER}",
            json={"role": "viewer"},
            headers=_auth(),
        )
        assert resp.status_code == 403

    def test_remove_member_as_non_member_is_403(self):
        client = _client(member_role=None)
        resp = client.delete(f"/api/workspaces/{WS}/members/{OTHER_USER}", headers=_auth())
        assert resp.status_code == 403

    def test_remove_member_as_non_member_does_not_remove(self):
        client = _client(member_role=None)
        client.delete(f"/api/workspaces/{WS}/members/{OTHER_USER}", headers=_auth())
        client.app.state.db.remove_workspace_member.assert_not_called()


@pytest.mark.unit
class TestInsufficientMemberRoleIsRejected:
    """A member, but below the required level — the case the old check did handle."""

    def test_viewer_cannot_delete_workspace(self):
        client = _client(member_role="viewer")
        resp = client.delete(f"/api/workspaces/{WS}", headers=_auth())
        assert resp.status_code == 403

    def test_editor_cannot_add_member(self):
        client = _client(member_role="editor")
        resp = client.post(
            f"/api/workspaces/{WS}/members",
            json={"user_id": OTHER_USER, "role": "viewer"},
            headers=_auth(),
        )
        assert resp.status_code == 403

    def test_viewer_may_list_members(self):
        """Listing needs membership, not ownership — a viewer is enough."""
        client = _client(member_role="viewer")
        resp = client.get(f"/api/workspaces/{WS}/members", headers=_auth())
        assert resp.status_code == 200


@pytest.mark.unit
class TestPermittedCallersStillPass:
    def test_owner_may_add_member(self):
        client = _client(member_role="owner")
        resp = client.post(
            f"/api/workspaces/{WS}/members",
            json={"user_id": OTHER_USER, "role": "editor"},
            headers=_auth(),
        )
        assert resp.status_code == 200

    def test_owner_add_member_writes_the_requested_role(self):
        client = _client(member_role="owner")
        client.post(
            f"/api/workspaces/{WS}/members",
            json={"user_id": OTHER_USER, "role": "editor"},
            headers=_auth(),
        )
        client.app.state.db.add_workspace_member.assert_called_once_with(WS, OTHER_USER, "editor")

    def test_owner_may_delete_workspace(self):
        client = _client(member_role="owner")
        resp = client.delete(f"/api/workspaces/{WS}", headers=_auth())
        assert resp.status_code == 200

    def test_global_admin_may_delete_without_membership(self):
        """Global admin short-circuits workspace membership, as it does elsewhere."""
        client = _client(member_role=None)
        resp = client.delete(f"/api/workspaces/{WS}", headers=_auth(role="admin"))
        assert resp.status_code == 200

    def test_authorisation_uses_the_path_workspace_not_a_header(self):
        """Guards the query/path trap: the checked workspace must be the one in the URL."""
        client = _client(member_role="owner")
        client.delete(f"/api/workspaces/{WS}", headers={**_auth(), "X-Workspace-ID": "99999999-9999-9999-9999-999999999999"})
        checked_ws = client.app.state.db.get_workspace_member_role.call_args[0][0]
        assert checked_ws == WS

