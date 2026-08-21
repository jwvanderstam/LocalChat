"""QA-3..QA-6 — four places where the interface reported something untrue.

Each of these renders a number or a control that contradicts the state behind it,
which is worse than showing nothing: it is confidently wrong.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.utils.auth import admin_headers, authenticated_state

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------
# QA-4 — a loaded model was reported as not fitting, which disabled its button
# --------------------------------------------------------------------------

class TestLoadedModelAlwaysFits:
    """budget_mb is *free* memory, which excludes what a running model occupies.

    Comparing a resident model's footprint against the remainder declares it too
    large for the machine it is running on; the page then disables its activate
    button, which reads as a dead control rather than a memory verdict.
    """

    def _models(self, *, loaded: list[str], footprint: int, free: int):
        from src.routes_fastapi.model_routes import router

        state = authenticated_state(role="admin")
        client = state.ollama_client
        client.list_models.return_value = (True, [{"name": "big:latest", "size": 1}])
        client.get_running_models.return_value = [{"name": n} for n in loaded]
        client.estimate_model_footprint.return_value = footprint

        backend = MagicMock()
        backend.memory_model = "dedicated"
        backend.free_mb = free
        backend.backend_name = "test-gpu"

        app = FastAPI()
        app.include_router(router, prefix="/api/models")
        app.state = state
        c = TestClient(app, raise_server_exceptions=False)
        c.headers.update(admin_headers())

        import src.gpu.backends as backends
        original = backends.detect
        backends.detect = lambda force=None: backend
        try:
            return c.get("/api/models").json()
        finally:
            backends.detect = original

    def test_a_running_model_fits_even_when_free_memory_is_smaller(self):
        """The regression: it is resident, so it demonstrably fits."""
        body = self._models(loaded=["big:latest"], footprint=8000, free=500)
        assert body["models"][0]["fits"] is True

    def test_a_running_model_carries_no_blocking_reason(self):
        """The reason string is what the UI puts in the disabled button's tooltip."""
        body = self._models(loaded=["big:latest"], footprint=8000, free=500)
        assert body["models"][0]["reason"] is None

    def test_a_model_that_is_not_loaded_and_too_large_still_does_not_fit(self):
        """Guard against over-correction — the budget check must still work."""
        body = self._models(loaded=[], footprint=8000, free=500)
        assert body["models"][0]["fits"] is False
        assert "requires" in body["models"][0]["reason"]

    def test_a_model_that_is_not_loaded_but_small_enough_fits(self):
        body = self._models(loaded=[], footprint=100, free=500)
        assert body["models"][0]["fits"] is True


# --------------------------------------------------------------------------
# QA-6 — a page of 50 with no way to know more existed
# --------------------------------------------------------------------------

class TestConversationPagingIsDiscoverable:
    """Paging existed; the fact that there was more to page through did not."""

    def _client(self, *, returned: int, total: int):
        from src.routes_fastapi.memory_routes import router

        state = authenticated_state(role="admin", member_role="viewer")
        state.db.list_conversations.return_value = [
            {"id": i, "title": f"c{i}"} for i in range(returned)
        ]
        state.db.count_conversations.return_value = total

        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.state = state
        c = TestClient(app, raise_server_exceptions=False)
        c.headers.update(admin_headers())
        return c

    def test_a_full_page_with_more_behind_it_says_so(self):
        """57 conversations, a page of 50 — the last 7 used to be invisible."""
        body = self._client(returned=50, total=57).get("/api/conversations").json()
        assert body["total"] == 57
        assert body["has_more"] is True

    def test_the_last_page_does_not_claim_more(self):
        body = self._client(returned=7, total=57).get("/api/conversations?offset=50").json()
        assert body["has_more"] is False

    def test_a_short_first_page_is_the_whole_list(self):
        body = self._client(returned=3, total=3).get("/api/conversations").json()
        assert body["total"] == 3
        assert body["has_more"] is False

    def test_an_empty_list_is_not_more(self):
        body = self._client(returned=0, total=0).get("/api/conversations").json()
        assert body["has_more"] is False


class TestConversationCountQuery:
    """The count is scoped like the listing, or the badge and the list disagree."""

    def _db(self):
        from src.db.conversations import ConversationsMixin

        class _Db(ConversationsMixin):
            is_connected = True

            def __init__(self):
                self.cursor = MagicMock()
                self.cursor.fetchone.return_value = (42,)

            def get_connection(self):
                cur, conn = self.cursor, MagicMock()
                conn.cursor.return_value.__enter__.return_value = cur
                outer = MagicMock()
                outer.__enter__.return_value = conn
                return outer

        return _Db()

    def test_a_workspace_scoped_count_filters_by_workspace(self):
        db = self._db()
        assert db.count_conversations(workspace_id="ws-1") == 42
        sql, params = db.cursor.execute.call_args[0]
        assert "workspace_id = %s" in sql
        assert params == ("ws-1",)

    def test_an_unscoped_count_does_not_filter_by_workspace(self):
        db = self._db()
        assert db.count_conversations() == 42
        assert "workspace_id" not in db.cursor.execute.call_args[0][0]

    def test_soft_deleted_conversations_are_not_counted(self):
        """Clark-Wilson: a retired conversation is not a missing one, but it is
        not a listed one either — the count must match what the listing returns."""
        db = self._db()
        db.count_conversations(workspace_id="ws-1")
        assert "deleted_at IS NULL" in db.cursor.execute.call_args[0][0]


# --------------------------------------------------------------------------
# QA-3 — the header badge counted documents across every workspace
# --------------------------------------------------------------------------

class TestStatusIsWorkspaceScoped:
    """/api/status already scoped the count; the header just never sent the header.

    A global number beside a workspace switcher reads as belonging to the selected
    workspace: the badge said 26 while Document Management, one nav item away, said 5.
    """

    def _status(self, headers: dict[str, str] | None = None):
        from src.routes_fastapi.api_routes import router

        state = authenticated_state(role="admin", member_role="viewer")
        state.startup_status = {"database": True, "ollama": True}
        state.db.get_document_count.return_value = 5

        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.state = state
        c = TestClient(app, raise_server_exceptions=False)
        c.headers.update(admin_headers())
        return state, c.get("/api/status", headers=headers or {})

    def test_the_workspace_header_reaches_the_document_count(self):
        from tests.utils.auth import WORKSPACE_ID

        state, resp = self._status({"X-Workspace-ID": WORKSPACE_ID})
        assert resp.status_code == 200
        # The count is cached through chat.get_doc_count_cached; what matters here is
        # that the request's workspace reached it rather than being dropped.
        assert WORKSPACE_ID in str(state.db.get_document_count.call_args)
