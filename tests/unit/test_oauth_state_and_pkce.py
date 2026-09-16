"""P1-3 — the OAuth state carries who started the flow, expires, and uses PKCE.

Audit finding M3, three problems in one store:

* The callback resolved the user from the **session**, but it is reached by a
  redirect *from the provider* — a cross-site navigation — and the session cookie is
  ``SameSite=strict``, so no cookie is sent. It returned 401 **after** exchanging the
  authorization code, which spends the code and connects nothing.
* The state was bound to the provider name, not to a user, and **never expired** —
  entries accumulated in memory for the life of the process.
* No PKCE, so an intercepted redirect is enough to exchange the code for a token.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from src.routes_fastapi import oauth_routes

USER = "33333333-3333-3333-3333-333333333333"
OTHER = "44444444-4444-4444-4444-444444444444"


@pytest.fixture(autouse=True)
def _clear_states():
    oauth_routes._oauth_states.clear()
    yield
    oauth_routes._oauth_states.clear()


@pytest.mark.unit
class TestTheStateCarriesTheUser:
    def test_the_callback_can_resolve_the_user_without_a_session(self):
        state, _ = oauth_routes._remember_authorization("google", USER)
        pending = oauth_routes._claim_authorization(state, "google")
        assert pending is not None
        assert pending.user_id == USER

    def test_two_users_get_unrelated_states(self):
        first, _ = oauth_routes._remember_authorization("google", USER)
        second, _ = oauth_routes._remember_authorization("google", OTHER)

        assert first != second
        assert oauth_routes._claim_authorization(first, "google").user_id == USER
        assert oauth_routes._claim_authorization(second, "google").user_id == OTHER

    def test_a_state_is_single_use(self):
        """A replayed callback must not connect a second token."""
        state, _ = oauth_routes._remember_authorization("google", USER)
        assert oauth_routes._claim_authorization(state, "google") is not None
        assert oauth_routes._claim_authorization(state, "google") is None

    def test_an_unknown_state_is_refused(self):
        assert oauth_routes._claim_authorization("never-issued", "google") is None

    def test_a_missing_state_is_refused(self):
        assert oauth_routes._claim_authorization(None, "google") is None
        assert oauth_routes._claim_authorization("", "google") is None

    def test_one_providers_state_does_not_work_at_the_other(self):
        """The two flows must not be interchangeable."""
        state, _ = oauth_routes._remember_authorization("google", USER)
        assert oauth_routes._claim_authorization(state, "microsoft") is None

    def test_a_state_rejected_for_the_wrong_provider_is_still_consumed(self):
        """Otherwise it could be retried against the right one after a probe."""
        state, _ = oauth_routes._remember_authorization("google", USER)
        oauth_routes._claim_authorization(state, "microsoft")
        assert oauth_routes._claim_authorization(state, "google") is None


@pytest.mark.unit
class TestStatesExpireAndAreSweptUp:
    def test_an_expired_state_is_refused(self, monkeypatch):
        state, _ = oauth_routes._remember_authorization("google", USER)
        stale = oauth_routes._oauth_states[state]
        oauth_routes._oauth_states[state] = type(stale)(
            provider=stale.provider,
            user_id=stale.user_id,
            code_verifier=stale.code_verifier,
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        assert oauth_routes._claim_authorization(state, "google") is None

    def test_a_fresh_state_is_not_refused(self):
        """The boundary on the other side — expiring everything would pass the above."""
        state, _ = oauth_routes._remember_authorization("google", USER)
        assert oauth_routes._claim_authorization(state, "google") is not None

    def test_starting_a_flow_prunes_states_that_have_expired(self):
        """They used to accumulate for the life of the process."""
        stale_state, _ = oauth_routes._remember_authorization("google", USER)
        stale = oauth_routes._oauth_states[stale_state]
        oauth_routes._oauth_states[stale_state] = type(stale)(
            provider=stale.provider,
            user_id=stale.user_id,
            code_verifier=stale.code_verifier,
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )

        oauth_routes._remember_authorization("google", OTHER)

        assert stale_state not in oauth_routes._oauth_states

    def test_pruning_leaves_live_states_alone(self):
        live, _ = oauth_routes._remember_authorization("google", USER)
        oauth_routes._remember_authorization("google", OTHER)
        assert live in oauth_routes._oauth_states


@pytest.mark.unit
class TestPkce:
    def test_the_challenge_is_the_s256_of_the_verifier(self):
        state, challenge = oauth_routes._remember_authorization("google", USER)
        verifier = oauth_routes._claim_authorization(state, "google").code_verifier

        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
            .decode("ascii")
            .rstrip("=")
        )
        assert challenge == expected

    def test_the_challenge_is_not_the_verifier(self):
        """`plain` PKCE would pass the equality above if both were the same string."""
        state, challenge = oauth_routes._remember_authorization("google", USER)
        verifier = oauth_routes._claim_authorization(state, "google").code_verifier
        assert challenge != verifier

    def test_the_challenge_carries_no_base64_padding(self):
        """RFC 7636 requires base64url without '=' — providers reject it otherwise."""
        _, challenge = oauth_routes._remember_authorization("google", USER)
        assert "=" not in challenge

    def test_every_flow_gets_its_own_verifier(self):
        first, _ = oauth_routes._remember_authorization("google", USER)
        second, _ = oauth_routes._remember_authorization("google", USER)
        assert (
            oauth_routes._claim_authorization(first, "google").code_verifier
            != oauth_routes._claim_authorization(second, "google").code_verifier
        )


@pytest.mark.unit
class TestTheAuthorizeRedirectAsksForPkce:
    """A verifier the provider was never told about protects nothing."""

    @pytest.mark.parametrize("provider", ["microsoft", "google"])
    def test_the_redirect_carries_the_challenge_and_method(self, client, provider, monkeypatch):
        from urllib.parse import parse_qs, urlparse

        from src import config

        monkeypatch.setattr(config, "MICROSOFT_CLIENT_ID", "ms-client")
        monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", "google-client")

        resp = client.get(f"/api/oauth/{provider}/authorize", follow_redirects=False)

        assert resp.status_code in (302, 307)
        query = parse_qs(urlparse(resp.headers["location"]).query)
        assert query["code_challenge_method"] == ["S256"]
        assert query["code_challenge"][0]
        assert query["state"][0]

    @pytest.mark.parametrize("provider", ["microsoft", "google"])
    def test_the_state_it_issued_belongs_to_the_caller(self, client, provider, monkeypatch):
        from urllib.parse import parse_qs, urlparse

        from src import config
        from tests.utils.auth import ADMIN_ID

        monkeypatch.setattr(config, "MICROSOFT_CLIENT_ID", "ms-client")
        monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", "google-client")

        resp = client.get(f"/api/oauth/{provider}/authorize", follow_redirects=False)
        state = parse_qs(urlparse(resp.headers["location"]).query)["state"][0]

        assert oauth_routes._oauth_states[state].user_id == ADMIN_ID

    @pytest.mark.parametrize("provider", ["microsoft", "google"])
    def test_an_unauthenticated_caller_starts_no_flow(
        self, unauthenticated_client, provider, monkeypatch
    ):
        from src import config

        monkeypatch.setattr(config, "MICROSOFT_CLIENT_ID", "ms-client")
        monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", "google-client")

        resp = unauthenticated_client.get(
            f"/api/oauth/{provider}/authorize", follow_redirects=False
        )

        assert resp.status_code == 401
        assert not oauth_routes._oauth_states
