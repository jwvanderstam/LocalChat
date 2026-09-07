"""Setting METRICS_TOKEN must not disable the observability dashboard.

`/api/metrics` and `/api/metrics.json` have two legitimate callers that
authenticate differently: a scraper presenting METRICS_TOKEN as a bearer token,
and the admin dashboard, which is a browser holding an httpOnly session cookie.
The browser cannot present the token — shipping it to the page would publish the
very secret it is.

Requiring the token from both is what made the deployment guide's own security
advice break a feature: with METRICS_TOKEN set, `settings.html` fetched
`/api/metrics.json` and silently got a 403.
"""

from unittest.mock import MagicMock

import pytest

from src import monitoring

pytestmark = pytest.mark.unit

TOKEN = "the-scraper-token"


def _request(*, authorization=None, claims=None):
    req = MagicMock()
    req.headers = {"authorization": authorization} if authorization else {}
    req.cookies = {}
    req._claims = claims or {}
    return req


@pytest.fixture
def token_set(monkeypatch):
    monkeypatch.setattr("src.config.METRICS_TOKEN", TOKEN)


@pytest.fixture
def claims(monkeypatch):
    """Stand in for the session the browser actually carries."""
    holder = {}

    def _claims_from_request(req):
        return holder.get("value", {})

    monkeypatch.setattr("src.security_fastapi._claims_from_request", _claims_from_request)
    return holder


class TestWithNoTokenConfigured:
    def test_everything_is_allowed(self, monkeypatch):
        """Unset METRICS_TOKEN is what makes the endpoint public — documented, not a bug."""
        monkeypatch.setattr("src.config.METRICS_TOKEN", "")

        assert monitoring._check_metrics_auth(_request()) is True


class TestAScraper:
    def test_the_matching_bearer_token_is_admitted(self, token_set, claims):
        assert monitoring._check_metrics_auth(_request(authorization=f"Bearer {TOKEN}")) is True

    def test_a_wrong_token_is_refused(self, token_set, claims):
        assert monitoring._check_metrics_auth(_request(authorization="Bearer nope")) is False

    def test_no_credentials_at_all_are_refused(self, token_set, claims):
        assert monitoring._check_metrics_auth(_request()) is False


class TestTheAdminDashboard:
    def test_an_admin_session_is_admitted_without_the_token(self, token_set, claims):
        """The case the 403 was breaking."""
        claims["value"] = {"sub": "admin", "role": "admin"}

        assert monitoring._check_metrics_auth(_request()) is True

    def test_a_non_admin_session_is_refused(self, token_set, claims):
        """Metrics stay an administrative surface; any signed-in user is not enough."""
        claims["value"] = {"sub": "someone", "role": "editor"}

        assert monitoring._check_metrics_auth(_request()) is False

    def test_a_session_with_no_role_is_refused(self, token_set, claims):
        claims["value"] = {"sub": "someone"}

        assert monitoring._check_metrics_auth(_request()) is False


class TestItFailsClosed:
    def test_an_unreadable_session_is_refused_rather_than_raising(self, token_set, monkeypatch):
        def explode(req):
            raise RuntimeError("token verification is broken")

        monkeypatch.setattr("src.security_fastapi._claims_from_request", explode)

        assert monitoring._check_metrics_auth(_request()) is False
