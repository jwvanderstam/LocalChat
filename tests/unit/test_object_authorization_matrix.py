"""P0-1 — every route that addresses an object by id is scoped to a workspace.

The audit found a class of defect rather than a list of bugs (C1, C2): the workspace
guard authorised the caller against *their* workspace, and the database call then
acted on an object in *any* workspace. Fixing the routes one by one leaves the next
route free to repeat it, so this module tests the property, not the instances:

* :class:`TestEveryScopedCallNamesItsScope` walks the AST of ``src/`` and fails when
  any call to a workspace-scoped database method omits ``scope=``. That is the
  productised form of the audit's own scan, and it is what catches a *new* route.
* The behavioural tests prove the scope that arrives is the one the guard authorised
  — the caller's own workspace, never a foreign one, never absent.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.security_fastapi import create_access_token
from src.utils.scope import ALL_WORKSPACES, scope_predicate

_SRC = Path(__file__).resolve().parents[2] / "src"

# Every database method that reaches a workspace-owned object. A method listed here
# without a keyword-only `scope` fails TestScopedMethodsRequireTheArgument, so the
# list and the signatures cannot drift apart.
SCOPED_METHODS = {
    "delete_document",
    "get_chunk_by_id",
    "get_adjacent_chunks",
    "search_chunks_by_text",
    "retire_all_documents",
    "delete_memory",
    "delete_all_memories",
    "get_unextracted_conversations",
    "get_annotations_for_chunk",
    "delete_annotation",
    "get_conversation_messages",
    "get_conversation_document_filter",
    "set_conversation_document_filter",
    "update_conversation_title",
    "delete_conversation",
    "get_connector",
    "update_connector",
    "delete_connector",
}

WS = "11111111-1111-1111-1111-111111111111"
OTHER_WS = "22222222-2222-2222-2222-222222222222"
USER = "33333333-3333-3333-3333-333333333333"


def _auth(role: str = "user") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(USER, {'role': role})}"}


def _client(router, prefix: str, member_role: str = "owner") -> TestClient:
    """A caller who is *member_role* of WS and a member of nothing else."""
    state = MagicMock()
    state.db.is_connected = True
    state.db.get_workspace_member_role.return_value = member_role
    state.db.get_user_workspaces.return_value = [{"id": WS}]
    state.db.get_default_workspace_id.return_value = WS
    state.db.list_conversations.return_value = []
    state.db.count_conversations.return_value = 0
    app = FastAPI()
    app.include_router(router, prefix=prefix)
    app.state = state
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.unit
class TestEveryScopedCallNamesItsScope:
    """The IVP: a workspace-scoped query cannot be reached without naming a scope."""

    def _offenders(self) -> list[str]:
        offenders = []
        for path in sorted(_SRC.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not isinstance(func, ast.Attribute) or func.attr not in SCOPED_METHODS:
                    continue
                if any(kw.arg == "scope" for kw in node.keywords):
                    continue
                offenders.append(f"{path.relative_to(_SRC.parent)}:{node.lineno} {func.attr}()")
        return offenders

    def test_no_call_omits_the_scope(self):
        offenders = self._offenders()
        assert not offenders, (
            "These calls reach a workspace-scoped object without naming a scope, "
            "which is how C1/C2 happened. Pass scope=get_scope(request), or "
            "scope=ALL_WORKSPACES when the path is deliberately installation-wide:\n  "
            + "\n  ".join(offenders)
        )

    def test_the_scan_recognises_an_unscoped_call(self):
        """The scan is only worth having if it matches the shape it hunts for."""
        call = next(
            n
            for n in ast.walk(ast.parse("db.delete_document(42, 'user')"))
            if isinstance(n, ast.Call)
        )
        assert isinstance(call.func, ast.Attribute)
        assert call.func.attr in SCOPED_METHODS
        assert not any(kw.arg == "scope" for kw in call.keywords)


@pytest.mark.unit
class TestScopedMethodsRequireTheArgument:
    """Every scoped method takes `scope` keyword-only, with no default to fall back to."""

    def test_scope_is_keyword_only_and_mandatory(self):
        from src.db import Database

        problems = []
        for name in sorted(SCOPED_METHODS):
            method = getattr(Database, name, None)
            if method is None:
                problems.append(f"{name}: no such method on Database")
                continue
            scope = inspect.signature(method).parameters.get("scope")
            if scope is None:
                problems.append(f"{name}: takes no scope")
            elif scope.kind is not inspect.Parameter.KEYWORD_ONLY:
                problems.append(f"{name}: scope is not keyword-only")
            elif scope.default is not inspect.Parameter.empty:
                problems.append(f"{name}: scope has a default, so it can be omitted")
        assert not problems, problems


@pytest.mark.unit
class TestScopePredicateRefusesAnAbsentScope:
    """`None` used to mean "every workspace". It now means "you forgot"."""

    def test_none_raises(self):
        with pytest.raises(ValueError, match="workspace scope is required"):
            scope_predicate(None, "workspace_id")  # type: ignore[arg-type]

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="workspace scope is required"):
            scope_predicate("", "workspace_id")

    def test_all_workspaces_adds_no_predicate(self):
        assert scope_predicate(ALL_WORKSPACES, "workspace_id") == ("", [])

    def test_a_workspace_id_is_parameterised_not_interpolated(self):
        sql, params = scope_predicate(WS, "d.workspace_id")
        assert sql == " AND d.workspace_id = %s"
        assert params == [WS]
        assert WS not in sql


@pytest.mark.unit
class TestTheScopeReachingTheQueryIsTheAuthorisedOne:
    """A member's scope is their own workspace — never a foreign one, never absent."""

    def test_document_delete_is_scoped_to_the_callers_workspace(self):
        from src.routes_fastapi.document_routes import router

        client = _client(router, "/api/documents", "editor")
        client.app.state.db.delete_document.return_value = True
        client.delete("/api/documents/42", headers=_auth())
        assert client.app.state.db.delete_document.call_args.kwargs["scope"] == WS

    def test_naming_another_workspace_moves_the_scope_it_does_not_widen_it(self):
        from src.routes_fastapi.document_routes import router

        client = _client(router, "/api/documents", "editor")
        client.app.state.db.delete_document.return_value = True
        client.delete("/api/documents/42", headers={**_auth(), "X-Workspace-ID": OTHER_WS})
        scope = client.app.state.db.delete_document.call_args.kwargs["scope"]
        assert scope == OTHER_WS
        assert scope is not ALL_WORKSPACES

    def test_chunk_context_is_scoped(self):
        from src.routes_fastapi.document_routes import router

        client = _client(router, "/api/documents", "viewer")
        client.app.state.db.get_chunk_by_id.return_value = None
        client.get("/api/documents/chunks/7/context", headers=_auth())
        assert client.app.state.db.get_chunk_by_id.call_args.kwargs["scope"] == WS

    def test_a_chunk_outside_the_scope_reads_as_not_found(self):
        from src.routes_fastapi.document_routes import router

        client = _client(router, "/api/documents", "viewer")
        client.app.state.db.get_chunk_by_id.return_value = None
        resp = client.get("/api/documents/chunks/7/context", headers=_auth())
        assert resp.status_code == 404

    def test_text_search_is_scoped(self):
        from src.routes_fastapi.document_routes import router

        client = _client(router, "/api/documents", "viewer")
        client.app.state.db.search_chunks_by_text.return_value = []
        client.post("/api/documents/search-text", json={"search_text": "x"}, headers=_auth())
        assert client.app.state.db.search_chunks_by_text.call_args.kwargs["scope"] == WS

    def test_conversation_delete_is_scoped(self):
        from src.routes_fastapi.memory_routes import router

        client = _client(router, "/api", "editor")
        client.app.state.db.delete_conversation.return_value = True
        client.delete(f"/api/conversations/{OTHER_WS}", headers=_auth())
        assert client.app.state.db.delete_conversation.call_args.kwargs["scope"] == WS

    def test_memory_delete_is_scoped(self):
        from src.routes_fastapi.longterm_memory_routes import router

        client = _client(router, "/api/memory", "editor")
        client.app.state.db.delete_memory.return_value = True
        client.delete("/api/memory/abc-123", headers=_auth())
        assert client.app.state.db.delete_memory.call_args.kwargs["scope"] == WS

    def test_annotation_delete_is_scoped(self):
        from src.routes_fastapi.annotation_routes import router

        client = _client(router, "/api", "editor")
        client.app.state.db.delete_annotation.return_value = True
        client.delete("/api/annotations/abc-123", headers=_auth())
        assert client.app.state.db.delete_annotation.call_args.kwargs["scope"] == WS

    def test_connector_read_is_scoped(self):
        from src.routes_fastapi.connector_routes import router

        client = _client(router, "/api", "owner")
        client.app.state.db.get_connector.return_value = None
        client.get("/api/connectors/abc-123", headers=_auth())
        assert client.app.state.db.get_connector.call_args.kwargs["scope"] == WS


@pytest.mark.unit
class TestClearRetiresWithinOneWorkspace:
    """D2 — /clear is a workspace-scoped retire; destroy is a separate, admin-only TP."""

    def test_clear_requires_owner_not_editor(self):
        from src.routes_fastapi.document_routes import router

        client = _client(router, "/api/documents", "editor")
        resp = client.delete("/api/documents/clear", headers=_auth())
        assert resp.status_code == 403

    def test_clear_retires_only_the_callers_workspace(self):
        from src.routes_fastapi.document_routes import router

        client = _client(router, "/api/documents", "owner")
        client.app.state.db.retire_all_documents.return_value = 3
        resp = client.delete("/api/documents/clear", headers=_auth())
        assert resp.status_code == 200
        assert client.app.state.db.retire_all_documents.call_args.kwargs["scope"] == WS

    def test_purge_all_is_not_reachable_by_a_workspace_owner(self):
        from src.routes_fastapi.document_routes import router

        client = _client(router, "/api/documents", "owner")
        resp = client.delete("/api/documents/purge-all", headers=_auth())
        assert resp.status_code in (401, 403)
        assert not client.app.state.db.purge_all_documents.called
