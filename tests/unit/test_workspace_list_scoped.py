"""The workspace switcher must not advertise workspaces you cannot enter.

Everyone saw every workspace. Selecting one you were not a member of produced a
correct Access Denied — but the list had already disclosed its name, and offering it
as a choice reads as a broken switcher rather than a boundary.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.security_fastapi import create_access_token

MINE = {"id": "11111111-1111-1111-1111-111111111111", "name": "Mine"}
THEIRS = {"id": "22222222-2222-2222-2222-222222222222", "name": "Theirs"}
USER = "33333333-3333-3333-3333-333333333333"


@pytest.fixture(autouse=True)
def _rbac_on():
    with patch("src.security_fastapi._ADMIN_PASSWORD_RAW", "set-so-rbac-is-live"):
        yield


def _client(*, global_role: str = "user", testing: bool = False):
    from src.routes_fastapi.workspace_routes import router

    state = MagicMock()
    state.testing = testing
    state.db.is_connected = True
    state.db.is_token_revoked.return_value = False
    state.db.list_workspaces.return_value = [dict(MINE), dict(THEIRS)]
    state.db.get_user_workspaces.return_value = [dict(MINE)]
    state.db.get_user_by_id.return_value = {"id": USER, "role": global_role}
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state = state
    return TestClient(app, raise_server_exceptions=False)


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(USER, {'role': 'user'})}"}


@pytest.mark.unit
class TestListIsScopedToMembership:
    def test_a_member_sees_only_their_own(self):
        resp = _client().get("/api/workspaces", headers=_auth())
        assert [w["name"] for w in resp.json()["workspaces"]] == ["Mine"]

    def test_a_workspace_they_cannot_enter_is_not_named(self):
        """The disclosure, not just the tidiness: the name itself was the leak."""
        resp = _client().get("/api/workspaces", headers=_auth())
        assert "Theirs" not in resp.text

    def test_an_admin_still_sees_everything(self):
        """They can reach any workspace anyway; hiding them would only obstruct."""
        resp = _client(global_role="admin").get("/api/workspaces", headers=_auth())
        assert len(resp.json()["workspaces"]) == 2

    def test_the_role_comes_from_the_database_not_the_token(self):
        """A demotion takes effect immediately rather than at the next login."""
        client = _client(global_role="user")
        admin_token = create_access_token(USER, {"role": "admin"})
        resp = client.get("/api/workspaces", headers={"Authorization": f"Bearer {admin_token}"})
        assert len(resp.json()["workspaces"]) == 1

    def test_the_bypass_still_lists_everything(self):
        """With no caller to scope by, narrowing would empty the switcher."""
        resp = _client(testing=True).get("/api/workspaces")
        assert len(resp.json()["workspaces"]) == 2
