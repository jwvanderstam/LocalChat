"""BUG-4 — the OAuth callbacks store a token against a real user, or not at all.

Both callbacks used to fall back to the literal string ``"admin"`` when no
caller could be resolved, writing a non-UUID into a user-id column — the same
shape as the ``'anonymous'`` defect RBAC-1 fixed.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.routes_fastapi import oauth_routes


@pytest.fixture(autouse=True)
def _clear_states():
    oauth_routes._oauth_states.clear()
    yield
    oauth_routes._oauth_states.clear()


def _token_exchange_succeeds():
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "access_token": "at", "refresh_token": "rt", "expires_in": 3600, "scope": "a b",
    }
    return patch.object(oauth_routes._requests, "post", return_value=response)


@pytest.mark.unit
@pytest.mark.parametrize("provider", ["microsoft", "google"])
class TestOAuthCallbackIdentity:

    def test_callback_stores_no_token_without_an_authenticated_user(
        self, unauthenticated_client, app, provider
    ):
        app.state.db.upsert_oauth_token = MagicMock()
        oauth_routes._oauth_states["s1"] = "/"

        with _token_exchange_succeeds():
            resp = unauthenticated_client.get(
                f"/api/oauth/{provider}/callback", params={"code": "c1", "state": "s1"}
            )

        assert resp.status_code == 401
        app.state.db.upsert_oauth_token.assert_not_called()

    def test_callback_stores_the_token_against_the_authenticated_user(
        self, client, app, provider
    ):
        app.state.db.upsert_oauth_token = MagicMock()
        oauth_routes._oauth_states["s1"] = "/"

        with _token_exchange_succeeds():
            resp = client.get(
                f"/api/oauth/{provider}/callback", params={"code": "c1", "state": "s1"}
            )

        assert resp.status_code == 200
        stored = app.state.db.upsert_oauth_token.call_args.kwargs["user_id"]
        assert stored != "admin"
        assert stored


@pytest.mark.unit
@pytest.mark.parametrize("provider", ["microsoft", "google"])
class TestOAuthStatusAndDisconnectIdentity:
    """The other four sites that used to invent an identity, and had no test at all."""

    def test_status_reads_the_callers_own_token(self, client, app, provider):
        app.state.db.get_oauth_token = MagicMock(return_value=None)

        resp = client.get(f"/api/oauth/{provider}/status")

        assert resp.status_code == 200
        assert resp.json() == {"connected": False}
        looked_up, asked_provider = app.state.db.get_oauth_token.call_args[0]
        assert asked_provider == provider
        assert looked_up and looked_up != "admin"

    def test_disconnect_removes_the_callers_own_token(self, client, app, provider):
        app.state.db.delete_oauth_token = MagicMock(return_value=True)

        resp = client.delete(f"/api/oauth/{provider}/disconnect")

        assert resp.status_code == 200
        assert resp.json() == {"success": True, "removed": True}
        deleted_for, asked_provider = app.state.db.delete_oauth_token.call_args[0]
        assert asked_provider == provider
        assert deleted_for and deleted_for != "admin"

    def test_status_refuses_an_unauthenticated_caller(self, unauthenticated_client, app, provider):
        app.state.db.get_oauth_token = MagicMock()

        resp = unauthenticated_client.get(f"/api/oauth/{provider}/status")

        assert resp.status_code == 401
        app.state.db.get_oauth_token.assert_not_called()
