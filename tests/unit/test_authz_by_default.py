"""TQ-1 — every route is guarded unless it is on the allowlist, checked by introspection.

RBAC-2 counted 102 routes by hand and found 49 with no authorisation. That was a
snapshot. This is the ratchet: it walks the *actual* route table of the *actual*
application and asserts each route refuses an unauthenticated caller. A new route
added without a guard fails here by default — no one has to remember.

Two things this had to get right, because getting either wrong produces a check that
passes while testing nothing:

* ``app.routes`` is **not** the route table. This FastAPI version stores includes as
  ``_IncludedRouter`` wrappers, so a naive walk finds four routes — the built-in docs
  pages — and declares the application clean. The paths come from ``app.openapi()``.
* ``openapi()`` omits ``include_in_schema=False`` routes. Those are the SPA shells,
  and they are enumerated separately and pinned by count, so a new hidden route
  cannot slip past the part of the check that cannot see it.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

_VERBS = ("get", "post", "put", "delete", "patch")

#: Routes that must answer without credentials, each for a stated reason.
#: Adding to this list is a decision; the test exists to make it a visible one.
PUBLIC_ALLOWLIST: dict[str, str] = {
    "/api/health": "container healthcheck calls it with no credentials",
    "/api/metrics": "Prometheus scrapes it; gated separately by METRICS_TOKEN",
    "/api/metrics.json": "same as /api/metrics",
    "/api/auth/login": "the route that establishes a session cannot require one",
    "/api/logout": "self-service; resolves and verifies the caller internally",
    "/api/users/me/password": "self-service; verifies the current password itself",
    "/api/oauth/microsoft/callback": "the identity provider redirects here with no token",
    "/api/oauth/google/callback": "same as the Microsoft callback",
    "/api/connectors/{connector_id}/webhook": "external systems post here; authenticity is the webhook's own concern",
    "/api/users/me": "how the frontend discovers whether it is logged in; returns all-null and can_write=false to an anonymous caller, so it reveals nothing",
    "/api/repo-docs": "serves the same markdown that is public in the repository",
    "/api/repo-docs/{slug}": "same as /api/repo-docs",
    "/api/repo-docs/{slug}/fragments/{fragment_slug}": "same as /api/repo-docs",
}

#: SPA shells — `include_in_schema=False`, so openapi() cannot see them. They carry no
#: data; every API call they make is itself guarded. Pinned so a new hidden route fails.
EXPECTED_HIDDEN_ROUTES = {
    "/", "/chat", "/docs", "/documents", "/favicon.ico", "/login", "/models", "/settings",
}


def _app():
    """The real application, wired as production would wire it."""
    from src.app_fastapi import create_app

    app = create_app()
    # A DB that answers but knows nothing: an unauthenticated caller must be refused
    # before any lookup, so the guard cannot be passing for want of data.
    state_db = MagicMock()
    state_db.is_connected = True
    state_db.get_workspace_member_role.return_value = None
    state_db.get_default_workspace_id.return_value = "ws-1"
    state_db.resolve_workspace_api_key.return_value = None
    app.state.db = state_db
    return app


def _api_routes(app) -> list[tuple[str, str]]:
    spec = app.openapi()
    return [
        (verb.upper(), path)
        for path, ops in spec["paths"].items()
        for verb in ops
        if verb in _VERBS
    ]


#: Path parameters typed as int; a UUID there yields 422 from validation, which is
#: neither a pass nor a refusal and would hide whether the route is guarded at all.
_INT_PARAMS = {"chunk_id", "doc_id"}
_UUID = "00000000-0000-0000-0000-000000000000"


def _fill_placeholders(path: str) -> str:
    """Substitute path parameters with values that parse but match nothing.

    Values must be *type-valid*, or FastAPI answers 422 before the guard runs and the
    route looks neither guarded nor open.
    """
    out = path
    for name in _INT_PARAMS:
        out = out.replace("{" + name + "}", "999999999")
    while "{" in out:
        start = out.index("{")
        end = out.index("}", start)
        out = out[:start] + _UUID + out[end + 1:]
    return out


def _hidden_routes(app) -> set[str]:
    paths = set()
    for inc in (r for r in app.routes if type(r).__name__ == "_IncludedRouter"):
        for route in inc.original_router.routes:
            if not getattr(route, "include_in_schema", True):
                paths.add(route.path)
    return paths


@pytest.fixture(scope="module")
def app():
    with patch("src.security_fastapi._ADMIN_PASSWORD_RAW", "set-so-rbac-is-live"):
        yield _app()


@pytest.mark.unit
class TestIntrospectionSeesTheRealTable:
    """Guards the check itself. A route walk that finds nothing passes vacuously."""

    def test_finds_the_whole_api_surface(self, app):
        assert len(_api_routes(app)) > 90, "introspection lost the route table"

    def test_hidden_routes_are_exactly_the_known_spa_shells(self, app):
        assert _hidden_routes(app) == EXPECTED_HIDDEN_ROUTES

    def test_allowlist_names_only_real_routes(self, app):
        """A stale allowlist entry would silently excuse a route that no longer exists."""
        known = {path for _, path in _api_routes(app)}
        assert set(PUBLIC_ALLOWLIST) <= known


@pytest.mark.unit
class TestEveryApiRouteRefusesAnonymous:
    def test_no_route_is_unguarded(self, app):
        client = TestClient(app, raise_server_exceptions=False)
        unguarded = []

        with patch("src.security_fastapi._ADMIN_PASSWORD_RAW", "set-so-rbac-is-live"):
            for method, path in _api_routes(app):
                if path in PUBLIC_ALLOWLIST:
                    continue
                url = _fill_placeholders(path)
                resp = client.request(method, url, json={})
                if resp.status_code not in (401, 403):
                    unguarded.append(f"{method} {path} -> {resp.status_code}")

        assert not unguarded, (
            "Routes answered an unauthenticated caller. Guard them, or add them to "
            "PUBLIC_ALLOWLIST with a reason:\n  " + "\n  ".join(unguarded)
        )
