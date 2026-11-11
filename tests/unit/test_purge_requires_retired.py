"""R-9 (QP-9 review) — a purge destroys only what was retired first.

``require_retired`` locks the row and refuses a live or missing one inside the purge's
transaction; ``purge_refusals`` turns that into a 409 or a 404; each purge route sends
it. Against Postgres, for all five purges: ``tests/integration/test_purge_requires_retired.py``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.db.connection import NotRetiredError, require_retired
from src.services.errors import ServiceError, purge_refusals
from tests.utils.auth import admin_headers, authenticated_state

pytestmark = pytest.mark.unit

ROW = "77777777-7777-7777-7777-777777777777"


def _cursor(answer: tuple[bool] | None) -> MagicMock:
    cur = MagicMock()
    cur.fetchone.return_value = answer
    return cur


class TestTheCheck:
    @pytest.mark.parametrize(("answer", "missing"), [(None, True), ((False,), False)], ids=["missing", "live"])
    def test_a_missing_or_live_row_is_refused(self, answer, missing):
        with pytest.raises(NotRetiredError) as refused:
            require_retired(_cursor(answer), "users", ROW)
        assert refused.value.missing is missing

    def test_a_retired_row_passes(self):
        assert require_retired(_cursor((True,)), "users", ROW) is None

    def test_the_row_is_locked_until_the_purge_commits(self):
        """Without the lock a restore could land between the check and the DELETE."""
        cur = _cursor((True,))
        require_retired(cur, "users", ROW)
        statement = cur.execute.call_args.args[0].as_string(None)
        assert statement == 'SELECT deleted_at IS NOT NULL FROM "users" WHERE id = %s FOR UPDATE'


class TestTheRefusal:
    @pytest.mark.parametrize(("missing", "status", "message"), [
        (True, 404, "User not found"),
        (False, 409, "User must be retired before it is purged"),
    ])
    def test_it_becomes_a_404_or_a_409(self, missing, status, message):
        with pytest.raises(ServiceError) as refused, purge_refusals("User"):
            raise NotRetiredError("users", missing=missing)
        assert (refused.value.status_code, refused.value.message) == (status, message)


def _client(router_module: str, prefix: str = "/api") -> tuple[TestClient, MagicMock]:
    import importlib

    router = importlib.import_module(router_module).router
    state = authenticated_state(role="admin")
    app = FastAPI()
    app.include_router(router, prefix=prefix)
    app.state = state
    client = TestClient(app, raise_server_exceptions=True)
    client.headers.update(admin_headers())
    return client, state.db


ROUTES = {
    "user": ("src.routes_fastapi.auth_routes", "/api", f"/api/users/{ROW}/purge", "users"),
    "conversation": ("src.routes_fastapi.memory_routes", "/api", f"/api/conversations/{ROW}/purge", "conversations"),
    "workspace": ("src.routes_fastapi.workspace_routes", "/api", f"/api/workspaces/{ROW}/purge", "workspaces"),
    "connector": ("src.routes_fastapi.connector_routes", "/api", f"/api/connectors/{ROW}/purge", "connectors"),
    "document": ("src.routes_fastapi.document_routes", "/api/documents", "/api/documents/5/purge", "documents"),
}


class TestEveryPurgeRouteSendsIt:
    @pytest.mark.parametrize("kind", ROUTES)
    def test_a_live_row_is_a_409(self, kind):
        module, prefix, path, repo = ROUTES[kind]
        client, db = _client(module, prefix)
        getattr(db, repo).purge.side_effect = NotRetiredError(repo, missing=False)
        resp = client.delete(path)
        assert (resp.status_code, resp.json()["message"]) == (
            409, f"{kind.capitalize()} must be retired before it is purged")

    @pytest.mark.parametrize("kind", ROUTES)
    def test_a_missing_row_is_a_404(self, kind):
        module, prefix, path, repo = ROUTES[kind]
        client, db = _client(module, prefix)
        getattr(db, repo).purge.side_effect = NotRetiredError(repo, missing=True)
        resp = client.delete(path)
        assert (resp.status_code, resp.json()["message"]) == (404, f"{kind.capitalize()} not found")
