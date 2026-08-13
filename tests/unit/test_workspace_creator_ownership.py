"""RBAC-1 prerequisite — a workspace's creator becomes its owner.

``create_workspace`` previously inserted only into ``workspaces``. Nothing wrote a
``workspace_members`` row on the creation path, so every workspace began with no
members. Harmless while membership was unenforced; once RBAC-1 enforces it, a
creator cannot reach the workspace they just made.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.db.workspaces import WorkspacesMixin
from src.routes_fastapi.workspace_routes import router
from src.security_fastapi import create_access_token

OWNER = "44444444-4444-4444-4444-444444444444"


class _Db(WorkspacesMixin):
    """WorkspacesMixin over a recording cursor, so SQL is asserted not mocked away."""

    def __init__(self) -> None:
        self.is_connected = True
        self.cursor = MagicMock()
        self.cursor.fetchone.return_value = ("99999999-9999-9999-9999-999999999999",)
        self.executed: list[tuple[str, tuple]] = []

        def _record(sql, params=None):
            self.executed.append((" ".join(sql.split()), params or ()))

        self.cursor.execute.side_effect = _record

    def get_connection(self):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.cursor.return_value.__enter__.return_value = self.cursor
        outer = MagicMock()
        outer.__enter__.return_value = conn
        outer.__exit__.return_value = None
        return outer

    def member_inserts(self) -> list[tuple[str, tuple]]:
        return [(s, p) for s, p in self.executed if "INSERT INTO workspace_members" in s]


@pytest.mark.unit
class TestCreateWorkspaceRecordsOwner:
    def test_owner_row_is_written(self):
        db = _Db()
        db.create_workspace("Acme", owner_id=OWNER)
        assert len(db.member_inserts()) == 1

    def test_owner_row_names_the_creator_as_owner(self):
        db = _Db()
        workspace_id = db.create_workspace("Acme", owner_id=OWNER)
        _, params = db.member_inserts()[0]
        assert params == (workspace_id, OWNER)

    def test_owner_insert_says_owner_not_the_default_viewer(self):
        """workspace_members.role defaults to 'viewer' — the insert must override it."""
        db = _Db()
        db.create_workspace("Acme", owner_id=OWNER)
        sql, _ = db.member_inserts()[0]
        assert "'owner'" in sql

    def test_owner_insert_shares_the_workspace_insert_cursor(self):
        """One cursor means one transaction: no committed workspace without its owner."""
        db = _Db()
        db.create_workspace("Acme", owner_id=OWNER)
        statements = [s for s, _ in db.executed]
        assert len(statements) == 2 and "INSERT INTO workspaces" in statements[0]

    def test_no_owner_id_writes_no_member_row(self):
        """Unauthenticated/demo creation still works; it simply records no owner."""
        db = _Db()
        db.create_workspace("Acme", owner_id=None)
        assert db.member_inserts() == []

    def test_workspace_is_still_created_without_an_owner(self):
        db = _Db()
        assert db.create_workspace("Acme", owner_id=None)


def _client():
    state = MagicMock()
    state.db.is_connected = True
    state.db.create_workspace.return_value = "ws-new"
    state.db.get_workspace.return_value = {"id": "ws-new", "name": "Acme"}
    state.db.is_token_revoked.return_value = False  # require_auth now runs on this route
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state = state
    return TestClient(app, raise_server_exceptions=True)


@pytest.mark.unit
class TestCreateWorkspaceRoutePassesCaller:
    def test_route_forwards_the_authenticated_caller_as_owner(self):
        client = _client()
        token = create_access_token(OWNER, {"role": "user"})
        with patch("src.security_fastapi._ADMIN_PASSWORD_RAW", "set-so-rbac-is-live"):
            resp = client.post(
                "/api/workspaces",
                json={"name": "Acme"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 201
        assert client.app.state.db.create_workspace.call_args.kwargs["owner_id"] == OWNER

    def test_an_unauthenticated_caller_creates_nothing(self):
        """Replaces a case that asserted owner_id=None under the RBAC bypass. Without
        a bypass there is no callerless create: the request is refused instead."""
        client = _client()
        resp = client.post("/api/workspaces", json={"name": "Acme"})
        assert resp.status_code == 401
        client.app.state.db.create_workspace.assert_not_called()
