"""
BUG-1 regression suite — long-term memory must be scoped to a workspace.

Before the fix, `memories.workspace_id` existed (migration 0003) but was never
written and never filtered on, so a memory formed in one workspace could surface
in another workspace's answer. Every test here fails against that code.

Covers both directions, since a read-side filter alone would have "fixed" the
leak by returning nothing at all:
  - write: insert_memory records the workspace; dedup is scoped to it
  - read:  search_memories / get_all_memories filter on it
  - wiring: retriever and chat service pass the workspace down
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.utils.scope import ALL_WORKSPACES

WS_A = "11111111-1111-1111-1111-111111111111"
WS_B = "22222222-2222-2222-2222-222222222222"


def _memories_mixin(connected=True, fetchone_return=None, fetchall_return=None):
    from src.db.memories import MemoriesMixin

    cur = MagicMock()
    cur.fetchone.return_value = fetchone_return
    cur.fetchall.return_value = fetchall_return or []
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)

    conn = MagicMock()
    conn.cursor.return_value = cur
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)

    m = MemoriesMixin()
    m.is_connected = connected
    m.get_connection = MagicMock(return_value=conn)
    m._embedding_to_pg_array = MagicMock(return_value="[0.1,0.2]")
    return m, cur


def _sql_and_params(cur):
    sql, params = cur.execute.call_args[0]
    return " ".join(sql.split()), params


# ---------------------------------------------------------------------------
# _allowed_workspace_ids
# ---------------------------------------------------------------------------

class TestAllowedWorkspaceIds:
    def test_returns_empty_for_all_workspaces(self):
        from src.db.memories import MemoriesMixin

        assert MemoriesMixin._allowed_workspace_ids(ALL_WORKSPACES) == []

    def test_an_absent_scope_is_refused_rather_than_read_as_every_workspace(self):
        """None used to mean unscoped; P2-1b-ii makes that the explicit ALL_WORKSPACES."""
        from src.db.memories import MemoriesMixin

        with pytest.raises(ValueError, match="workspace scope is required"):
            MemoriesMixin._allowed_workspace_ids(None)  # type: ignore[arg-type]

    def test_returns_single_workspace(self):
        from src.db.memories import MemoriesMixin

        assert MemoriesMixin._allowed_workspace_ids(WS_A) == [WS_A]

    def test_appends_additional_workspaces_in_order(self):
        from src.db.memories import MemoriesMixin

        assert MemoriesMixin._allowed_workspace_ids(WS_A, [WS_B]) == [WS_A, WS_B]

    def test_additional_ids_ignored_without_a_primary_workspace(self):
        from src.db.memories import MemoriesMixin

        # ALL_WORKSPACES is already unscoped; extras must not silently narrow it.
        assert MemoriesMixin._allowed_workspace_ids(ALL_WORKSPACES, [WS_B]) == []


# ---------------------------------------------------------------------------
# Write path
# ---------------------------------------------------------------------------

class TestInsertMemoryRecordsWorkspace:
    def test_workspace_id_is_written(self):
        m, cur = _memories_mixin()
        m.insert_memory("fact", [0.1] * 8, workspace_id=WS_A)
        sql, params = _sql_and_params(cur)
        assert "workspace_id" in sql
        assert WS_A in params

    def test_workspace_column_count_matches_values(self):
        m, cur = _memories_mixin()
        m.insert_memory("fact", [0.1] * 8, workspace_id=WS_A)
        sql, params = _sql_and_params(cur)
        assert sql.count("%s") == len(params)

    def test_workspace_is_none_when_not_supplied(self):
        m, cur = _memories_mixin()
        m.insert_memory("fact", [0.1] * 8)
        _, params = _sql_and_params(cur)
        assert params[-1] is None


class TestDedupIsScopedToWorkspace:
    def test_scoped_dedup_filters_on_workspace(self):
        m, cur = _memories_mixin(fetchone_return=None)
        m.is_duplicate_memory([0.1] * 8, scope=WS_A)
        sql, params = _sql_and_params(cur)
        assert "workspace_id = %s" in sql
        assert params[-1] == WS_A

    def test_unscoped_dedup_has_no_workspace_clause(self):
        m, cur = _memories_mixin(fetchone_return=None)
        m.is_duplicate_memory([0.1] * 8, scope=ALL_WORKSPACES)
        sql, params = _sql_and_params(cur)
        assert "workspace_id" not in sql
        assert len(params) == 2


# ---------------------------------------------------------------------------
# Read path
# ---------------------------------------------------------------------------

class TestSearchMemoriesIsScoped:
    def test_filters_on_the_requested_workspace(self):
        m, cur = _memories_mixin()
        m.search_memories([0.1] * 8, scope=WS_A)
        sql, params = _sql_and_params(cur)
        assert "workspace_id = %s" in sql
        assert WS_A in params

    def test_each_workspace_is_searched_in_its_own_scoped_transaction(self):
        """Under row-level security a transaction sees one workspace, so a single query
        over [A, B] would silently return A's memories only (P2-1b-iii)."""
        m, _ = _memories_mixin()
        m.search_memories([0.1] * 8, scope=WS_A, additional_workspace_ids=[WS_B])
        scopes = [c.kwargs["scope"] for c in m.get_connection.call_args_list]
        assert scopes == [WS_A, WS_B]

    def test_other_workspace_is_never_queried(self):
        m, cur = _memories_mixin()
        m.search_memories([0.1] * 8, scope=WS_A)
        scopes = [c.kwargs["scope"] for c in m.get_connection.call_args_list]
        assert scopes == [WS_A]
        assert all(WS_B not in c.args[1] for c in cur.execute.call_args_list)

    def test_results_from_every_workspace_merge_by_similarity_and_cut_to_top_k(self):
        m, cur = _memories_mixin()

        def _row(mid, sim):
            return (mid, "enc", "fact", 1.0, None, 0, sim)

        # First scoped query (A) then the second (B); similarities interleave.
        cur.fetchall.side_effect = [
            [_row("a1", 0.9), _row("a2", 0.6)],
            [_row("b1", 0.8), _row("b2", 0.7)],
        ]
        with patch("src.db.memories._decrypt", side_effect=lambda v: v):
            result = m.search_memories(
                [0.1] * 8, top_k=3, scope=WS_A, additional_workspace_ids=[WS_B]
            )
        assert [r["id"] for r in result] == ["a1", "b1", "b2"]

    def test_unscoped_search_has_no_workspace_clause(self):
        m, cur = _memories_mixin()
        m.search_memories([0.1] * 8, scope=ALL_WORKSPACES)
        sql, _ = _sql_and_params(cur)
        assert "workspace_id" not in sql

    def test_placeholder_count_matches_params_when_scoped(self):
        m, cur = _memories_mixin()
        m.search_memories([0.1] * 8, scope=WS_A)
        sql, params = _sql_and_params(cur)
        assert sql.count("%s") == len(params)

    def test_placeholder_count_matches_params_when_unscoped(self):
        m, cur = _memories_mixin()
        m.search_memories([0.1] * 8, scope=ALL_WORKSPACES)
        sql, params = _sql_and_params(cur)
        assert sql.count("%s") == len(params)


class TestGetAllMemoriesIsScoped:
    def test_filters_on_workspace(self):
        m, cur = _memories_mixin()
        m.get_all_memories(scope=WS_A)
        sql, params = _sql_and_params(cur)
        assert "workspace_id = %s" in sql
        assert params[0] == WS_A

    def test_unscoped_listing_has_no_workspace_clause(self):
        m, cur = _memories_mixin()
        m.get_all_memories(scope=ALL_WORKSPACES)
        sql, params = _sql_and_params(cur)
        assert "workspace_id" not in sql
        assert params == (200, 0)


class TestUnextractedConversationsCarryWorkspace:
    def test_workspace_id_is_returned_for_inheritance(self):
        from datetime import datetime

        conv_id = str(uuid.uuid4())
        m, _ = _memories_mixin(
            fetchall_return=[(conv_id, "Title", datetime(2026, 1, 1), WS_A)]
        )
        rows = m.get_unextracted_conversations(scope="ws-1")
        assert rows[0]["workspace_id"] == WS_A


# ---------------------------------------------------------------------------
# Wiring — the parameter has to survive the whole call chain
# ---------------------------------------------------------------------------

class TestRetrieverPassesWorkspaceDown:
    def test_workspace_reaches_search_memories(self):
        from src.memory.retriever import MemoryRetriever

        db = MagicMock()
        db.is_connected = True
        db.search_memories.return_value = []
        ollama = MagicMock()
        ollama.get_embedding_model.return_value = "embed-model"
        ollama.generate_embedding.return_value = (True, [0.1] * 8)

        MemoryRetriever().retrieve(
            "query", ollama, db, scope=WS_A, additional_workspace_ids=[WS_B]
        )

        kwargs = db.search_memories.call_args.kwargs
        assert kwargs["scope"] == WS_A
        assert kwargs["additional_workspace_ids"] == [WS_B]


class TestChatServicePassesWorkspaceDown:
    async def test_workspace_reaches_the_retriever(self, monkeypatch):
        from src.services import chat

        monkeypatch.setattr(chat.config, "LONG_TERM_MEMORY_ENABLED", True)
        monkeypatch.setattr(chat.config, "QUERY_PLANNER_ENABLED", False)

        captured: dict = {}

        class _FakeRetriever:
            def retrieve(self, *args, **kwargs):
                captured.update(kwargs)
                return []

            @staticmethod
            def format_for_prompt(memories):
                return ""

        import src.memory.retriever as retriever_mod

        monkeypatch.setattr(retriever_mod, "MemoryRetriever", _FakeRetriever)

        fields = {"message": "hi", "use_rag": False, "additional_workspace_ids": [WS_B]}
        await chat.retrieve_plan_and_memory(
            fields, "model", AsyncMock(), MagicMock(), scope=WS_A
        )

        assert captured["scope"] == WS_A
        assert captured["additional_workspace_ids"] == [WS_B]


@pytest.mark.parametrize("scoped", [True, False])
def test_orphan_memories_never_leak_into_a_scoped_query(scoped):
    """A NULL-workspace memory is invisible to a scoped query, visible to an unscoped one."""
    m, cur = _memories_mixin()
    m.search_memories([0.1] * 8, scope=WS_A if scoped else ALL_WORKSPACES)
    sql, _ = _sql_and_params(cur)
    # "= %s" never matches NULL, so scoped queries exclude orphans by construction.
    assert ("workspace_id = %s" in sql) is scoped
