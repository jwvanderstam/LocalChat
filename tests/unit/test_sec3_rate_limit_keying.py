"""SEC-3 — rate limits key on the real client, and cover more than login.

The defect these guard: ``get_remote_address`` reads ``request.client.host``,
which behind a reverse proxy is the proxy. Every caller then shares one bucket,
so ``RATELIMIT_LOGIN`` stops being per-source — one attacker exhausts the budget
for everyone. Trusting ``X-Forwarded-For`` unconditionally would be the opposite
defect, so both directions are asserted.
"""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src import config
from src.app_fastapi import _init_security

# Imported for their side effect: @limiter.limit registers each route's limit at
# import time, and the autouse fixture below snapshots that registry at setup.
import src.routes_fastapi.api_routes  # noqa: E402,F401  isort:skip
import src.routes_fastapi.auth_routes  # noqa: E402,F401  isort:skip
import src.routes_fastapi.document_routes  # noqa: E402,F401  isort:skip
import src.routes_fastapi.model_routes  # noqa: E402,F401  isort:skip
from src.security_fastapi import limiter  # noqa: E402

pytestmark = pytest.mark.unit

# TestClient reports this as the peer address; _TrustedHosts keeps non-IP values
# as literals, so it can stand in for a proxy's address.
_PEER = "testclient"


@pytest.fixture(autouse=True)
def _isolate_limiter():
    """Buckets and the route registry are process-wide.

    Each ``_app()`` re-decorates a function with the same module+name, so without
    restoring ``_route_limits`` the limits accumulate and every later request
    counts several times over.
    """
    was_enabled = limiter.enabled
    saved_routes = dict(limiter._route_limits)
    limiter.reset()
    yield
    limiter.reset()
    limiter._route_limits.clear()
    limiter._route_limits.update(saved_routes)
    limiter.enabled = was_enabled


def _app(monkeypatch, trusted_proxies: list[str]) -> TestClient:
    monkeypatch.setattr(config, "TRUSTED_PROXY_IPS", trusted_proxies)
    monkeypatch.setattr(config, "RATELIMIT_ENABLED", True)

    app = FastAPI()

    @app.get("/limited")
    @limiter.limit("2 per minute")
    def limited(request: Request) -> dict:
        return {"client": request.client.host if request.client else None}

    # The real wiring function, not a copy of it — this is what the fix changed.
    _init_security(app, testing=False)
    return TestClient(app)


def _get(client: TestClient, forwarded_for: str):
    return client.get("/limited", headers={"X-Forwarded-For": forwarded_for})


class TestProxyHeaderTrust:
    def test_untrusted_proxy_ignores_forwarded_for_so_callers_share_one_bucket(
        self, monkeypatch
    ):
        """No trusted proxy: the header is forgeable, so it must not be believed."""
        client = _app(monkeypatch, [])

        assert _get(client, "10.0.0.1").status_code == 200
        assert _get(client, "10.0.0.2").status_code == 200
        # Third request, third distinct claimed address — still the same bucket.
        assert _get(client, "10.0.0.3").status_code == 429

    def test_trusted_proxy_gives_each_forwarded_client_its_own_bucket(
        self, monkeypatch
    ):
        """The fix: exhausting one caller's budget must not block a different one."""
        client = _app(monkeypatch, [_PEER])

        assert _get(client, "10.0.0.1").status_code == 200
        assert _get(client, "10.0.0.1").status_code == 200
        assert _get(client, "10.0.0.1").status_code == 429, "first client not limited"

        # A different source address, with the first one's budget already spent.
        assert _get(client, "10.0.0.2").status_code == 200, (
            "a second client was locked out by the first client's traffic"
        )

    def test_trusted_proxy_rewrites_client_host_to_the_forwarded_address(
        self, monkeypatch
    ):
        client = _app(monkeypatch, [_PEER])
        assert _get(client, "203.0.113.7").json()["client"] == "203.0.113.7"

    def test_untrusted_proxy_leaves_client_host_as_the_socket_peer(self, monkeypatch):
        client = _app(monkeypatch, [])
        assert _get(client, "203.0.113.7").json()["client"] == _PEER


class TestLimiterConfiguration:
    def test_limiter_uses_the_configured_storage_uri(self):
        """Without this the configured Redis is never touched and each worker
        keeps private counters."""
        assert limiter._storage_uri == config.RATELIMIT_STORAGE_URI

    def test_general_limit_is_the_configured_default(self):
        """RATELIMIT_GENERAL applied to routes carrying no explicit decorator."""
        flat = [str(limit.limit) for group in limiter._default_limits for limit in group]
        assert flat == [str(_parse(config.RATELIMIT_GENERAL))]

    def test_limiter_is_disabled_under_test_wiring(self, monkeypatch):
        monkeypatch.setattr(config, "RATELIMIT_ENABLED", True)
        app = FastAPI()
        _init_security(app, testing=True)
        assert limiter.enabled is False, (
            "limits enforced under test but no 429 handler is registered"
        )


def _parse(spec: str):
    from limits import parse

    return parse(spec)


class TestRoutesCarryTheirConfiguredLimit:
    """RATELIMIT_CHAT/UPLOAD/MODELS existed in config but decorated no route."""

    @pytest.mark.parametrize(
        "endpoint, expected",
        [
            ("src.routes_fastapi.api_routes.api_chat", config.RATELIMIT_CHAT),
            (
                "src.routes_fastapi.document_routes.api_upload_documents",
                config.RATELIMIT_UPLOAD,
            ),
            ("src.routes_fastapi.model_routes.pull_model", config.RATELIMIT_MODELS),
            ("src.routes_fastapi.model_routes.delete_model", config.RATELIMIT_MODELS),
            ("src.routes_fastapi.model_routes.unload_model", config.RATELIMIT_MODELS),
            ("src.routes_fastapi.model_routes.set_active_model", config.RATELIMIT_MODELS),
            ("src.routes_fastapi.auth_routes.login", config.RATELIMIT_LOGIN),
        ],
    )
    def test_route_is_limited_at_its_configured_rate(self, endpoint, expected):
        limits = limiter._route_limits.get(endpoint)
        assert limits, f"{endpoint} carries no rate limit"
        assert [str(limit.limit) for limit in limits] == [str(_parse(expected))]
