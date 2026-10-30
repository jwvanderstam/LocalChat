"""R-6 (QP-9 review) — the Settings page renders admin stats for an administrator only.

`GET /settings` takes no credentials, because every user changes their own password
there. It also rendered `gather_admin_stats()` for every caller: the version, the active
model, health and installation-wide totals that `/api/settings/stats` refuses to anyone
but an admin. An unauthenticated request got them in the HTML. The page still renders for
everyone; only an administrator's copy carries the stats.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from src.routes_fastapi import web_routes
from src.services import admin_stats
from tests.utils.auth import admin_headers, auth_headers, authenticated_state

pytestmark = pytest.mark.unit

STATS = {"system": {"app_version": "9.9.9"}}


def _render(monkeypatch: pytest.MonkeyPatch, *, db_role: str, headers: dict[str, str]) -> Any:
    """GET /settings and return the stats the template was handed."""
    captured: dict[str, Any] = {}

    class _Templates:
        def TemplateResponse(self, _request: Any, _name: str, context: dict[str, Any]) -> HTMLResponse:
            captured.update(context)
            return HTMLResponse("rendered")

    monkeypatch.setattr(web_routes, "_templates", lambda _request: _Templates())
    monkeypatch.setattr(admin_stats, "gather_admin_stats", lambda _state: STATS)

    app = FastAPI()
    app.include_router(web_routes.router)
    app.state = authenticated_state(role=db_role)
    app.state.docs_service.get_fragment_body.return_value = ""
    response = TestClient(app).get("/settings", headers=headers)
    assert response.status_code == 200
    return captured["stats"]


def test_an_unauthenticated_caller_gets_the_page_without_stats(monkeypatch):
    assert _render(monkeypatch, db_role="admin", headers={}) == {}


def test_a_signed_in_user_gets_the_page_without_stats(monkeypatch):
    assert _render(monkeypatch, db_role="user", headers=auth_headers()) == {}


def test_a_token_claiming_admin_is_not_enough_when_the_database_says_user(monkeypatch):
    # The role comes from the database, as on /api/settings/stats (audit H2).
    assert _render(monkeypatch, db_role="user", headers=admin_headers()) == {}


def test_an_administrator_gets_the_stats(monkeypatch):
    # The permitted case: without it, the three refusals above would pass on a page
    # that never renders stats for anyone.
    assert _render(monkeypatch, db_role="admin", headers=admin_headers()) == STATS
