"""BUG-4 — the OAuth callbacks store a token against a real user, or not at all.

Both callbacks used to fall back to the literal string ``"admin"`` when no
caller could be resolved, writing a non-UUID into a user-id column — the same
shape as the ``'anonymous'`` defect RBAC-1 fixed.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.routes_fastapi import oauth_routes

USER = "33333333-3333-3333-3333-333333333333"


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

    def test_callback_stores_no_token_without_a_valid_state(
        self, unauthenticated_client, app, provider
    ):
        """No pending authorization, no identity, no write.

        This used to assert a 401 from the session. Since P1-3 the callback does
        not consult the session at all — it cannot, because the provider's redirect
        is cross-site and the cookie is SameSite=strict — so the state is what
        carries the identity, and an absent one refuses just as firmly.
        """
        app.state.db.upsert_oauth_token = MagicMock()

        with _token_exchange_succeeds():
            resp = unauthenticated_client.get(
                f"/api/oauth/{provider}/callback", params={"code": "c1", "state": "s1"}
            )

        assert resp.status_code == 400
        app.state.db.upsert_oauth_token.assert_not_called()

    def test_callback_stores_the_token_against_the_user_who_authorised(
        self, unauthenticated_client, app, provider
    ):
        """BUG-4's guarantee, now carried by the state rather than the session.

        The client here is deliberately unauthenticated: a real browser arrives at
        this endpoint with no cookie, and the flow must still complete.
        """
        app.state.db.upsert_oauth_token = MagicMock()
        state, _ = oauth_routes._remember_authorization(provider, USER)

        with _token_exchange_succeeds():
            resp = unauthenticated_client.get(
                f"/api/oauth/{provider}/callback", params={"code": "c1", "state": state}
            )

        assert resp.status_code == 200
        stored = app.state.db.upsert_oauth_token.call_args.kwargs["user_id"]
        assert stored == USER
        assert stored != "admin"


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
