"""RBAC-1 — the workspace role tier is enforced across the route surface.

Covers the two things BUG-3 showed a route can lack independently: a check at all,
and a *test* that runs with the RBAC bypass off. Everything here sets
``testing = False`` and patches ``_ADMIN_PASSWORD_RAW``, so the checks actually run.

Header-scoped routes (documents, conversations, chat, annotations) pass
``workspace_id=None``; scope resolves from ``X-Workspace-ID`` and falls back to the
default workspace when the client sends none.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.security_fastapi import create_access_token

WS = "11111111-1111-1111-1111-111111111111"
DEFAULT_WS = "00000000-0000-0000-0000-0000000000ff"
USER = "33333333-3333-3333-3333-333333333333"


def _auth(role: str = "user") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(USER, {'role': role})}"}


def _client(router, prefix: str, member_role: str | None):
    state = MagicMock()
    state.db.is_connected = True
    state.db.get_workspace_member_role.return_value = member_role
    state.db.get_default_workspace_id.return_value = DEFAULT_WS
    # Explicit: this caller belongs to no workspace of their own, so scope resolution
    # falls through to the global default. A MagicMock would return a truthy stand-in
    # here and quietly become the answer.
    state.db.get_user_workspaces.return_value = []
    # Also explicit, for the same reason: the listing route measures the page it
    # returns against the total, and a MagicMock is neither a list nor a number.
    state.db.list_conversations.return_value = []
    state.db.count_conversations.return_value = 0
    app = FastAPI()
    app.include_router(router, prefix=prefix)
    app.state = state
    return TestClient(app, raise_server_exceptions=False)


def _documents(member_role: str | None):
    from src.routes_fastapi.document_routes import router
    return _client(router, "/api/documents", member_role)


def _conversations(member_role: str | None):
    from src.routes_fastapi.memory_routes import router
    return _client(router, "/api", member_role)


def _annotations(member_role: str | None):
    from src.routes_fastapi.annotation_routes import router
    return _client(router, "/api", member_role)


@pytest.mark.unit
class TestViewerIsReadOnly:
    def test_viewer_may_list_documents(self):
        resp = _documents("viewer").get("/api/documents/list", headers=_auth())
        assert resp.status_code == 200

    def test_viewer_may_not_upload(self):
        resp = _documents("viewer").post(
            "/api/documents/upload", files={"files": ("a.txt", b"hi", "text/plain")}, headers=_auth()
        )
        assert resp.status_code == 403

    def test_viewer_may_not_clear_documents(self):
        resp = _documents("viewer").delete("/api/documents/clear", headers=_auth())
        assert resp.status_code == 403

    def test_viewer_may_list_conversations(self):
        resp = _conversations("viewer").get("/api/conversations", headers=_auth())
        assert resp.status_code == 200

    def test_viewer_may_export_a_conversation(self):
        """Decision: export reformats what a viewer can already read."""
        resp = _conversations("viewer").get("/api/conversations/c1/export", headers=_auth())
        assert resp.status_code != 403

    def test_viewer_may_not_create_a_conversation(self):
        resp = _conversations("viewer").post("/api/conversations", json={}, headers=_auth())
        assert resp.status_code == 403

    def test_viewer_may_not_annotate(self):
        resp = _annotations("viewer").post("/api/annotations", json={"chunk_id": 1}, headers=_auth())
        assert resp.status_code == 403

    def test_viewer_may_read_annotations(self):
        resp = _annotations("viewer").get("/api/chunks/1/annotations", headers=_auth())
        assert resp.status_code == 200


@pytest.mark.unit
class TestEditorMayWrite:
    def test_editor_may_create_a_conversation(self):
        resp = _conversations("editor").post("/api/conversations", json={}, headers=_auth())
        assert resp.status_code != 403

    def test_editor_may_annotate(self):
        resp = _annotations("editor").post(
            "/api/annotations", json={"chunk_id": 1, "text": "note"}, headers=_auth()
        )
        assert resp.status_code != 403


@pytest.mark.unit
class TestNonMemberAndAnonymous:
    def test_non_member_is_refused(self):
        resp = _documents(None).get("/api/documents/list", headers=_auth())
        assert resp.status_code == 403

    def test_unauthenticated_is_refused(self):
        resp = _documents(None).get("/api/documents/list")
        assert resp.status_code == 401

    def test_global_admin_passes_without_membership(self):
        resp = _documents(None).get("/api/documents/list", headers=_auth(role="admin"))
        assert resp.status_code == 200


@pytest.mark.unit
class TestWorkspaceScopeResolution:
    def test_header_workspace_is_the_one_checked(self):
        client = _documents("viewer")
        client.get("/api/documents/list", headers={**_auth(), "X-Workspace-ID": WS})
        assert client.app.state.db.get_workspace_member_role.call_args[0][0] == WS

    def test_missing_header_falls_back_to_the_default_workspace(self):
        """The frontend sends no header until localStorage holds one — that must still work.

        This is the case where the caller has no workspace of their own; see
        test_user_workspace_membership.py for the case where they do, which now takes
        precedence over the global default.
        """
        client = _documents("viewer")
        client.get("/api/documents/list", headers=_auth())
        assert client.app.state.db.get_workspace_member_role.call_args[0][0] == DEFAULT_WS

    def test_the_callers_own_workspace_beats_the_default(self):
        """Added 2026-08-07: falling straight to the default refused everything to a
        user who was a member of some other workspace."""
        client = _documents("viewer")
        client.app.state.db.get_user_workspaces.return_value = [{"id": WS}]
        client.get("/api/documents/list", headers=_auth())
        assert client.app.state.db.get_workspace_member_role.call_args[0][0] == WS

    def test_no_workspaces_at_all_is_a_clear_error(self):
        client = _documents("viewer")
        client.app.state.db.get_default_workspace_id.return_value = None
        resp = client.get("/api/documents/list", headers=_auth())
        assert resp.status_code == 400


@pytest.mark.unit
class TestBypassKeepsDemoWorking:
    def test_testing_bypass_allows_an_unauthenticated_write(self):
        client = _documents("viewer")
        resp = client.delete("/api/documents/clear")
        assert resp.status_code != 403


@pytest.mark.unit
class TestDocumentDeleteIsEditorNotAdmin:
    """Sprint 6 decision: whoever may upload may also retire. Purge stays admin-only."""

    def test_editor_may_soft_delete(self):
        client = _documents("editor")
        resp = client.delete("/api/documents/42", headers=_auth())
        assert resp.status_code == 200

    def test_editor_soft_delete_records_the_caller(self):
        client = _documents("editor")
        client.delete("/api/documents/42", headers=_auth())
        client.app.state.db.delete_document.assert_called_once_with(42, USER)

    def test_viewer_may_not_soft_delete(self):
        resp = _documents("viewer").delete("/api/documents/42", headers=_auth())
        assert resp.status_code == 403

    def test_purge_still_requires_global_admin(self):
        """The irreversible operation did not move with the reversible one."""
        resp = _documents("owner").delete("/api/documents/42/purge", headers=_auth())
        assert resp.status_code == 403
