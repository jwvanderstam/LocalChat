"""Setting METRICS_TOKEN must not disable the observability dashboard.

`/api/metrics` and `/api/metrics.json` have two legitimate callers that
authenticate differently: a scraper presenting METRICS_TOKEN as a bearer token,
and the admin dashboard, which is a browser holding an httpOnly session cookie.
The browser cannot present the token — shipping it to the page would publish the
very secret it is.

Requiring the token from both is what made the deployment guide's own security
advice break a feature: with METRICS_TOKEN set, `settings.html` fetched
`/api/metrics.json` and silently got a 403.

The dashboard's admin is established by `resolve_principal`, like every other
guard: the role comes from the database and a revoked token is refused. Reading
the JWT's `role` claim, as this check once did, let a demoted administrator keep
reading metrics until the token expired (audit H2's shape).
"""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from src import monitoring
from src.routes_fastapi import settings_routes
from tests.utils.auth import admin_headers, auth_headers, authenticated_state

pytestmark = pytest.mark.unit

TOKEN = "the-scraper-token"


def _request(*, authorization=None):
    req = MagicMock()
    # Starlette headers are case-insensitive; a plain dict would hide a case mismatch.
    req.headers = Headers({"Authorization": authorization} if authorization else {})
    req.cookies = {}
    return req


@pytest.fixture
def token_set(monkeypatch):
    monkeypatch.setattr("src.config.METRICS_TOKEN", TOKEN)


def _dashboard_get(*, headers, role, revoked=False):
    """GET /api/metrics.json through the real router and the real resolver."""
    app = FastAPI()
    app.include_router(settings_routes.router, prefix="/api")
    app.state = authenticated_state(role=role)
    app.state.db.is_token_revoked.return_value = revoked
    return TestClient(app).get("/api/metrics.json", headers=headers)


class TestWithNoTokenConfigured:
    def test_everything_is_allowed(self, monkeypatch):
        """Unset METRICS_TOKEN is what makes the endpoint public — documented, not a bug."""
        monkeypatch.setattr("src.config.METRICS_TOKEN", "")

        assert monitoring._check_metrics_auth(_request()) is True


class TestAScraper:
    def test_the_matching_bearer_token_is_admitted(self, token_set):
        assert monitoring._check_metrics_auth(_request(authorization=f"Bearer {TOKEN}")) is True

    def test_a_wrong_token_is_refused(self, token_set):
        assert monitoring._check_metrics_auth(_request(authorization="Bearer nope")) is False

    def test_no_credentials_at_all_are_refused(self, token_set):
        assert monitoring._check_metrics_auth(_request()) is False


class TestTheAdminDashboard:
    def test_an_admin_session_is_admitted_without_the_token(self, token_set):
        """The case the 403 was breaking."""
        response = _dashboard_get(headers=admin_headers(), role="admin")

        assert response.status_code == 200

    def test_a_demoted_admin_is_refused_while_the_token_still_says_admin(self, token_set):
        """The token was minted while the caller was an admin; the database says user now."""
        response = _dashboard_get(headers=admin_headers(), role="user")

        assert response.status_code == 403

    def test_a_revoked_admin_token_is_refused(self, token_set):
        response = _dashboard_get(headers=admin_headers(), role="admin", revoked=True)

        assert response.status_code == 403

    def test_a_non_admin_session_is_refused(self, token_set):
        """Metrics stay an administrative surface; any signed-in user is not enough."""
        response = _dashboard_get(headers=auth_headers(role="editor"), role="editor")

        assert response.status_code == 403


class TestItFailsClosed:
    def test_an_unresolvable_caller_is_refused_rather_than_raising(self, token_set, monkeypatch):
        def explode(req):
            raise RuntimeError("principal resolution is broken")

        monkeypatch.setattr("src.security_fastapi.resolve_principal", explode)

        assert monitoring._check_metrics_auth(_request()) is False
