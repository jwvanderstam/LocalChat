"""RBAC-2 — the route permission audit, asserted.

Before this pass 49 of 102 routes carried no authorisation check at all, including
`POST /api/models/pull`, `DELETE /api/models/delete` and `POST /api/plugins/reload`.
None of them did an internal check either.

Every test runs with the RBAC bypass OFF. The existing suite runs with
`state.testing = True`, which short-circuits every check — that is why these routes
had coverage and no authorisation (LESSONS_LEARNED Ch. 12).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.security_fastapi import create_access_token

WS = "11111111-1111-1111-1111-111111111111"
USER = "33333333-3333-3333-3333-333333333333"


@pytest.fixture(autouse=True)
def _rbac_on():
    with patch("src.security_fastapi._ADMIN_PASSWORD_RAW", "set-so-rbac-is-live"), \
         patch("src.security_fastapi.config.DEMO_MODE", False):
        yield


def _auth(role: str = "user") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(USER, {'role': role})}"}


def _client(module: str, prefix: str, member_role: str | None = None):
    import importlib
    router = importlib.import_module(f"src.routes_fastapi.{module}").router
    state = MagicMock()
    state.testing = False
    state.db.is_connected = True
    state.db.get_workspace_member_role.return_value = member_role
    state.db.get_default_workspace_id.return_value = WS
    # Without this, MagicMock returns a truthy mock and require_auth reads every
    # token as revoked — a 401 that looks exactly like "not authenticated".
    state.db.is_token_revoked.return_value = False
    app = FastAPI()
    app.include_router(router, prefix=prefix)
    app.state = state
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.unit
class TestModelManagementIsAdminOnly:
    """Decision: model pull/delete affects the whole node — disk, VRAM, everyone's model."""

    @pytest.mark.parametrize(
        ("verb", "path"),
        [("post", "/pull"), ("delete", "/delete"), ("post", "/unload"),
         ("post", "/active"), ("post", "/test"), ("get", ""), ("get", "/active")],
    )
    def test_non_admin_is_refused(self, verb, path):
        client = _client("model_routes", "/api/models")
        kwargs = {"json": {}} if verb == "post" else {}
        resp = getattr(client, verb)(f"/api/models{path}", headers=_auth(), **kwargs)
        assert resp.status_code == 403

    @pytest.mark.parametrize(("verb", "path"), [("post", "/pull"), ("delete", "/delete")])
    def test_unauthenticated_is_refused(self, verb, path):
        client = _client("model_routes", "/api/models")
        kwargs = {"json": {}} if verb == "post" else {}
        resp = getattr(client, verb)(f"/api/models{path}", **kwargs)
        assert resp.status_code == 401

    def test_admin_is_allowed_through_the_guard(self):
        client = _client("model_routes", "/api/models")
        resp = client.get("/api/models", headers=_auth(role="admin"))
        assert resp.status_code != 403


@pytest.mark.unit
class TestPluginRoutesAreAdminOnly:
    """Reloading plugins re-executes plugin code in-process."""

    def test_reload_refuses_non_admin(self):
        client = _client("api_routes", "/api")
        assert client.post("/api/plugins/reload", headers=_auth()).status_code == 403

    def test_reload_refuses_anonymous(self):
        client = _client("api_routes", "/api")
        assert client.post("/api/plugins/reload").status_code == 401

    def test_listing_refuses_non_admin(self):
        client = _client("api_routes", "/api")
        assert client.get("/api/plugins", headers=_auth()).status_code == 403


@pytest.mark.unit
class TestConnectorsRequireWorkspaceOwner:
    """Connectors hold credentials and feed one workspace — owner's business."""

    def test_editor_may_not_create(self):
        client = _client("connector_routes", "/api", member_role="editor")
        resp = client.post("/api/connectors", headers=_auth(), json={"connector_type": "local_folder"})
        assert resp.status_code == 403

    def test_owner_may_list(self):
        client = _client("connector_routes", "/api", member_role="owner")
        assert client.get("/api/connectors", headers=_auth()).status_code != 403

    def test_non_member_may_not_trigger_sync(self):
        client = _client("connector_routes", "/api", member_role=None)
        assert client.post("/api/connectors/c1/sync", headers=_auth()).status_code == 403

    def test_webhook_stays_open(self):
        """Deliberate: external systems POST here without a bearer token."""
        client = _client("connector_routes", "/api", member_role=None)
        assert client.post("/api/connectors/c1/webhook", json={}).status_code != 401


@pytest.mark.unit
class TestWorkspaceListingRequiresLogin:
    """No workspace context exists yet on these, so it is plain authentication."""

    def test_anonymous_cannot_list_workspaces(self):
        assert _client("workspace_routes", "/api").get("/api/workspaces").status_code == 401

    def test_anonymous_cannot_create_a_workspace(self):
        resp = _client("workspace_routes", "/api").post("/api/workspaces", json={"name": "x"})
        assert resp.status_code == 401

    def test_authenticated_user_may_list(self):
        client = _client("workspace_routes", "/api", member_role="viewer")
        assert client.get("/api/workspaces", headers=_auth()).status_code != 401


@pytest.mark.unit
class TestPublicRoutesStayPublic:
    """The allowlist. Each is public for a stated reason, not by omission."""

    def test_health_needs_no_auth(self):
        """The container healthcheck calls this with no credentials."""
        assert _client("settings_routes", "/api").get("/api/health").status_code != 401

    def test_oauth_callback_needs_no_auth(self):
        """The identity provider redirects here and carries no bearer token."""
        client = _client("oauth_routes", "/api")
        assert client.get("/api/oauth/microsoft/callback").status_code != 401

    def test_oauth_authorize_does_need_auth(self):
        """Starting the flow is a user action, unlike receiving its callback."""
        client = _client("oauth_routes", "/api")
        assert client.get("/api/oauth/microsoft/authorize").status_code == 401
