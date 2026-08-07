"""Workspace API keys — a workspace as a programmatic endpoint.

The use case is a chatbot bridge (Discord via n8n, Slack, a scheduled job) that
queries one workspace. Before this, such a bridge had to log in as a person: a
non-human principal wearing a human's schema, with a password it never resets, a
session that expires mid-conversation, and an audit trail naming someone who was
asleep at the time.

A key is scoped to exactly one workspace. The tests that matter most are the ones
proving it cannot reach a second one.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.db.workspace_keys import KEY_PREFIX, _hash_key, generate_api_key
from src.security_fastapi import check_workspace_access

WS_A = "11111111-1111-1111-1111-111111111111"
WS_B = "22222222-2222-2222-2222-222222222222"


@pytest.fixture(autouse=True)
def _rbac_on():
    # DEMO_MODE is gone (SEC-1); only the admin-password branch remains to neutralise.
    with patch("src.security_fastapi._ADMIN_PASSWORD_RAW", "set-so-rbac-is-live"):
        yield


def _request(headers: dict[str, str], db) -> Request:
    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "query_string": b"",
        "path": "/api/chat",
        "method": "POST",
        "app": MagicMock(),
    }
    req = Request(scope)
    req.scope["app"].state.db = db
    req.scope["app"].state.testing = False
    return req


def _db(*, resolves_to=(WS_A, "viewer")):
    db = MagicMock()
    db.is_connected = True
    db.resolve_workspace_api_key.return_value = resolves_to
    db.get_default_workspace_id.return_value = WS_B  # deliberately NOT the key's
    return db


@pytest.mark.unit
class TestKeyGeneration:
    def test_key_carries_the_identifying_prefix(self):
        full, _, _ = generate_api_key()
        assert full.startswith(KEY_PREFIX)

    def test_stored_prefix_is_a_fragment_not_the_key(self):
        full, prefix, _ = generate_api_key()
        assert prefix != full and full.startswith(prefix)

    def test_hash_is_not_the_key(self):
        full, _, key_hash = generate_api_key()
        assert key_hash != full and key_hash == _hash_key(full)

    def test_two_keys_differ(self):
        assert generate_api_key()[0] != generate_api_key()[0]


@pytest.mark.unit
class TestRowsAreJsonSerialisable:
    """psycopg returns UUID and datetime; these rows go straight into a JSONResponse.

    The route tests below mock the DB and hand back plain dicts, so they never see
    the real row shape — this failed only against a live database.
    """

    def test_uuid_and_datetime_are_converted(self):
        import json
        from datetime import UTC, datetime
        from uuid import uuid4

        from src.db.workspace_keys import _jsonable

        row = _jsonable({"id": uuid4(), "created_at": datetime.now(UTC), "name": "bridge"})
        json.dumps(row)  # raises TypeError if either value survived unconverted

    def test_plain_values_pass_through(self):
        from src.db.workspace_keys import _jsonable

        assert _jsonable({"role": "viewer", "n": 3}) == {"role": "viewer", "n": 3}


@pytest.mark.unit
class TestKeyIsConfinedToItsWorkspace:
    """The property that makes a key a workspace credential rather than a global one."""

    def test_key_authorises_its_own_workspace(self):
        req = _request({"X-API-Key": "lcw_secret", "X-Workspace-ID": WS_A}, _db())
        assert check_workspace_access(req, None, "viewer") is None

    def test_key_cannot_reach_another_workspace_by_header(self):
        """Changing X-Workspace-ID must not widen the key's reach."""
        req = _request({"X-API-Key": "lcw_secret", "X-Workspace-ID": WS_B}, _db())
        denial = check_workspace_access(req, None, "viewer")
        assert denial is not None and denial[0] == 403

    def test_key_cannot_reach_another_workspace_by_path(self):
        """A route passing its path workspace explicitly is checked the same way."""
        req = _request({"X-API-Key": "lcw_secret"}, _db())
        denial = check_workspace_access(req, WS_B, "viewer")
        assert denial is not None and denial[0] == 403

    def test_omitting_the_header_pins_the_key_workspace_not_the_default(self):
        """The bug this guards: no header, so scope would fall through to the
        default workspace downstream while the check passed against the key's."""
        db = _db()
        req = _request({"X-API-Key": "lcw_secret"}, db)
        assert check_workspace_access(req, None, "viewer") is None
        assert req.state.resolved_workspace_id == WS_A

    def test_pinned_scope_wins_in_get_workspace_id(self):
        from src.utils.workspace import get_workspace_id

        db = _db()
        req = _request({"X-API-Key": "lcw_secret"}, db)
        check_workspace_access(req, None, "viewer")
        assert get_workspace_id(req) == WS_A


@pytest.mark.unit
class TestKeyRoleIsEnforced:
    def test_viewer_key_is_refused_write_access(self):
        req = _request({"X-API-Key": "lcw_secret", "X-Workspace-ID": WS_A}, _db())
        denial = check_workspace_access(req, None, "editor")
        assert denial is not None and denial[0] == 403

    def test_editor_key_may_write(self):
        db = _db(resolves_to=(WS_A, "editor"))
        req = _request({"X-API-Key": "lcw_secret", "X-Workspace-ID": WS_A}, db)
        assert check_workspace_access(req, None, "editor") is None

    def test_key_never_receives_the_global_admin_shortcut(self):
        """A key is scoped by construction; nothing about it should escape that."""
        db = _db(resolves_to=(WS_A, "viewer"))
        req = _request({"X-API-Key": "lcw_secret", "X-Workspace-ID": WS_B}, db)
        denial = check_workspace_access(req, None, "viewer")
        assert denial is not None and denial[0] == 403


@pytest.mark.unit
class TestInvalidKeys:
    def test_revoked_or_unknown_key_is_401(self):
        db = _db(resolves_to=None)
        req = _request({"X-API-Key": "lcw_gone"}, db)
        denial = check_workspace_access(req, None, "viewer")
        assert denial is not None and denial[0] == 401

    def test_a_jwt_is_not_mistaken_for_a_key(self):
        """Bearer carries both; only the lcw_ prefix selects the key path."""
        db = _db()
        req = _request({"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.x.y"}, db)
        check_workspace_access(req, None, "viewer")
        db.resolve_workspace_api_key.assert_not_called()

    def test_key_is_accepted_as_a_bearer_token(self):
        """n8n and most webhook tools only offer an Authorization field."""
        db = _db()
        req = _request({"Authorization": f"Bearer {KEY_PREFIX}secret", "X-Workspace-ID": WS_A}, db)
        assert check_workspace_access(req, None, "viewer") is None


@pytest.mark.unit
class TestKeyManagementRoutes:
    def _client(self, member_role: str = "owner"):
        from src.routes_fastapi.workspace_routes import router

        state = MagicMock()
        state.testing = True  # these assert route wiring, not authorisation
        state.db.is_connected = True
        state.db.get_workspace_member_role.return_value = member_role
        state.db.create_workspace_api_key.return_value = (
            "lcw_plaintext_shown_once",
            {"id": "k1", "name": "discord-bridge", "key_prefix": "lcw_plain", "role": "viewer"},
        )
        state.db.list_workspace_api_keys.return_value = [
            {"id": "k1", "name": "discord-bridge", "key_prefix": "lcw_plain", "role": "viewer"}
        ]
        state.db.revoke_workspace_api_key.return_value = True
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.state = state
        return TestClient(app, raise_server_exceptions=False)

    def test_create_returns_the_plaintext_key_once(self):
        resp = self._client().post(f"/api/workspaces/{WS_A}/keys", json={"name": "discord-bridge"})
        assert resp.json()["key"] == "lcw_plaintext_shown_once"

    def test_listing_never_returns_a_key_or_hash(self):
        resp = self._client().get(f"/api/workspaces/{WS_A}/keys")
        body = resp.text
        assert "key_hash" not in body and "lcw_plaintext" not in body

    def test_owner_role_cannot_be_issued_to_a_key(self):
        """A key that can mint keys turns one leak into permanent control."""
        resp = self._client().post(
            f"/api/workspaces/{WS_A}/keys", json={"name": "x", "role": "owner"})
        assert resp.status_code == 400

    def test_revoke_scopes_the_delete_to_the_workspace(self):
        client = self._client()
        client.delete(f"/api/workspaces/{WS_A}/keys/k1")
        kwargs = client.app.state.db.revoke_workspace_api_key.call_args.kwargs
        assert kwargs["workspace_id"] == WS_A
