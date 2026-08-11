"""RBAC-1 UI half — GET /api/users/me reports whether the caller may write.

The frontend hides upload/delete controls from viewers. It must not decide that by
comparing role names itself: a second copy of the role hierarchy is exactly what let
the workspace member routes drift out of sync (BUG-3). ``can_write`` is therefore
answered by the same ``check_workspace_access`` the write routes call.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.routes_fastapi.auth_routes import router
from src.security_fastapi import create_access_token

WS = "11111111-1111-1111-1111-111111111111"
USER = "33333333-3333-3333-3333-333333333333"


def _client(member_role: str | None, global_role: str = "user"):
    state = MagicMock()
    state.db.is_connected = True
    state.db.is_token_revoked.return_value = False
    state.db.get_workspace_member_role.return_value = member_role
    state.db.get_default_workspace_id.return_value = WS
    state.db.get_user_by_id.return_value = {"id": USER, "username": "jo", "role": global_role}
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state = state
    return TestClient(app, raise_server_exceptions=False)


def _auth(role: str = "user") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(USER, {'role': role})}"}


@pytest.mark.unit
class TestCanWriteMirrorsTheRouteCheck:
    def test_viewer_cannot_write(self):
        resp = _client("viewer").get("/api/users/me", headers=_auth())
        assert resp.json()["can_write"] is False

    def test_editor_can_write(self):
        resp = _client("editor").get("/api/users/me", headers=_auth())
        assert resp.json()["can_write"] is True

    def test_owner_can_write(self):
        resp = _client("owner").get("/api/users/me", headers=_auth())
        assert resp.json()["can_write"] is True

    def test_non_member_cannot_write(self):
        resp = _client(None).get("/api/users/me", headers=_auth())
        assert resp.json()["can_write"] is False

    def test_global_admin_can_write_without_membership(self):
        resp = _client(None, global_role="admin").get("/api/users/me", headers=_auth(role="admin"))
        assert resp.json()["can_write"] is True


@pytest.mark.unit
class TestIdentityPayload:
    def test_reports_the_workspace_role(self):
        resp = _client("viewer").get("/api/users/me", headers={**_auth(), "X-Workspace-ID": WS})
        assert resp.json()["workspace_role"] == "viewer"

    def test_reports_the_global_role(self):
        resp = _client("editor", global_role="admin").get("/api/users/me", headers=_auth())
        assert resp.json()["role"] == "admin"

    def test_reports_the_caller_id(self):
        resp = _client("editor").get("/api/users/me", headers=_auth())
        assert resp.json()["user_id"] == USER

    def test_role_is_checked_against_the_header_workspace(self):
        client = _client("editor")
        client.get("/api/users/me", headers={**_auth(), "X-Workspace-ID": WS})
        assert client.app.state.db.get_workspace_member_role.call_args[0][0] == WS


@pytest.mark.unit
class TestRouteOrdering:
    def test_me_is_not_captured_by_the_admin_user_id_route(self):
        """/users/me must be registered before /users/{user_id}, which is admin-only.

        Registered the other way round, a non-admin caller hits require_admin_dep and
        gets 403 — the FastAPI ordering gotcha in CLAUDE.md.
        """
        resp = _client("viewer").get("/api/users/me", headers=_auth())
        assert resp.status_code == 200

    def test_unauthenticated_is_refused(self):
        resp = _client(None).get("/api/users/me")
        assert resp.json()["can_write"] is False

