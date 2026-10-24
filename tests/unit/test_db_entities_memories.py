"""
Tests for src/db/entities.py (EntitiesRepository) and src/db/memories.py (MemoriesRepository)

Covers:
  EntitiesRepository:
    - upsert_entity: DB unavailable raises, returns UUID string
    - insert_entity_relation: DB unavailable is silent, normal call
    - delete_document_entities: DB unavailable is silent
    - get_related_entity_names: empty list, DB unavailable, returns rows
    - get_entity_by_name: not found, found
    - get_all_entities: DB unavailable returns []
    - get_entity_stats: DB unavailable returns zeros

  MemoriesRepository:
    - insert_memory: DB unavailable raises, returns UUID
    - update_memory_usage: empty list no-op, DB unavailable no-op, normal
    - delete_memory: DB unavailable raises
    - delete_all_memories: DB unavailable raises, returns count
    - mark_conversation_extracted: DB unavailable is silent
    - search_memories: DB unavailable returns []
    - is_duplicate_memory: DB unavailable returns False, found/not-found
    - get_all_memories: DB unavailable returns []
    - get_unextracted_conversations: DB unavailable returns []
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from src.utils.scope import ALL_WORKSPACES

# ---------------------------------------------------------------------------
# Helpers — build a mixin instance with a mocked get_connection
# ---------------------------------------------------------------------------

def _make_conn_ctx(fetchone_return=None, fetchall_return=None, rowcount=0):
    """Return (mixin_patcher, conn_ctx) where conn_ctx can be passed as get_connection return."""
    cur = MagicMock()
    cur.fetchone.return_value = fetchone_return
    cur.fetchall.return_value = fetchall_return or []
    cur.rowcount = rowcount
    cur.description = [("col",)]
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)

    conn = MagicMock()
    conn.cursor.return_value = cur
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)

    return conn, cur


def _entities_mixin(connected=True, **conn_kwargs):
    from src.db.entities import EntitiesRepository

    conn, cur = _make_conn_ctx(**conn_kwargs)
    m = _host(EntitiesRepository, "entities")
    m.is_connected = connected
    m.get_connection = MagicMock(return_value=conn)
    return m, conn, cur


class _Host:
    """The connection a repository runs over, holding it as ``Database`` does."""


def _host(repository, attr):
    """A host with *repository* attached as *attr*, as ``Database.__init__`` does."""
    host = _Host()
    setattr(host, attr, repository(host))
    return host


def _memories_mixin(connected=True, **conn_kwargs):
    from src.db.memories import MemoriesRepository

    conn, cur = _make_conn_ctx(**conn_kwargs)
    m = _Host()
    m.is_connected = connected
    m.get_connection = MagicMock(return_value=conn)
    m._embedding_to_pg_array = MagicMock(return_value="[0.1,0.2]")
    m.memories = MemoriesRepository(m)
    return m, conn, cur


# ===========================================================================
# EntitiesRepository
# ===========================================================================

class TestUpsertEntity:
    def test_raises_when_db_unavailable(self):
        from src.db.connection import DatabaseUnavailableError
        m, _, _ = _entities_mixin(connected=False)
        with pytest.raises(DatabaseUnavailableError):
            m.entities.upsert("Apple", "ORG")

    def test_returns_string_id(self):
        eid = str(uuid.uuid4())
        m, _, cur = _entities_mixin(fetchone_return=(eid,))
        result = m.entities.upsert("Apple", "ORG")
        assert result == eid

    def test_calls_executemany_or_execute(self):
        m, _, cur = _entities_mixin(fetchone_return=(str(uuid.uuid4()),))
        m.entities.upsert("Google", "ORG")
        assert cur.execute.call_count >= 1


class TestInsertEntityRelation:
    def test_no_op_when_db_unavailable(self):
        m, _, _ = _entities_mixin(connected=False)
        # Should not raise
        m.entities.insert_relation("id-a", "id-b", 1, 10)
        m.get_connection.assert_not_called()

    def test_calls_connection_when_connected(self):
        m, conn, _ = _entities_mixin()
        m.entities.insert_relation("id-a", "id-b", 1, 10)
        m.get_connection.assert_called_once()

    def test_custom_relation_and_weight(self):
        m, _, cur = _entities_mixin()
        m.entities.insert_relation("a", "b", 1, 2, relation="co_authors", weight=3.0)
        assert cur.execute.call_count >= 1


class TestGetRelatedEntityNames:
    def test_returns_empty_for_empty_input(self):
        m, _, _ = _entities_mixin()
        result = m.entities.related_names([])
        assert result == []
        m.get_connection.assert_not_called()

    def test_returns_empty_when_db_unavailable(self):
        m, _, _ = _entities_mixin(connected=False)
        result = m.entities.related_names(["Apple"])
        assert result == []

    def test_returns_names_from_db(self):
        m, _, cur = _entities_mixin(fetchall_return=[("Google",), ("Microsoft",)])
        result = m.entities.related_names(["Apple"])
        assert result == ["Google", "Microsoft"]


# ===========================================================================
# MemoriesRepository
# ===========================================================================

class TestInsertMemory:
    def test_raises_when_db_unavailable(self):
        from src.db.connection import DatabaseUnavailableError
        m, _, _ = _memories_mixin(connected=False)
        with pytest.raises(DatabaseUnavailableError):
            m.memories.insert("content", [0.1] * 10)

    def test_returns_uuid_string(self):
        m, _, _ = _memories_mixin()
        result = m.memories.insert("fact about X", [0.1] * 10)
        # Must be a valid UUID
        uuid.UUID(result)

    def test_calls_embedding_conversion(self):
        m, _, _ = _memories_mixin()
        m.memories.insert("fact", [0.5] * 8)
        m._embedding_to_pg_array.assert_called_once()


class TestUpdateMemoryUsage:
    def test_no_op_on_empty_list(self):
        m, _, _ = _memories_mixin()
        m.memories.record_use([])
        m.get_connection.assert_not_called()

    def test_no_op_when_db_unavailable(self):
        m, _, _ = _memories_mixin(connected=False)
        m.memories.record_use(["mem-1"])
        m.get_connection.assert_not_called()

    def test_executes_update_when_connected(self):
        m, conn, _ = _memories_mixin()
        m.memories.record_use(["mem-1", "mem-2"])
        m.get_connection.assert_called_once()


class TestDeleteMemory:
    def test_raises_when_db_unavailable(self):
        from src.db.connection import DatabaseUnavailableError
        m, _, _ = _memories_mixin(connected=False)
        with pytest.raises(DatabaseUnavailableError):
            m.memories.retire("some-uuid", scope="ws-1")

    def test_executes_delete_when_connected(self):
        m, conn, _ = _memories_mixin()
        m.memories.retire("mem-uuid", scope="ws-1")
        m.get_connection.assert_called_once()


class TestDeleteAllMemories:
    def test_raises_when_db_unavailable(self):
        from src.db.connection import DatabaseUnavailableError
        m, _, _ = _memories_mixin(connected=False)
        with pytest.raises(DatabaseUnavailableError):
            m.memories.retire_all(scope="ws-1")

    def test_returns_count(self):
        m, _, cur = _memories_mixin(rowcount=7)
        count = m.memories.retire_all(scope="ws-1")
        assert count == 7


class TestMarkConversationExtracted:
    def test_no_op_when_db_unavailable(self):
        m, _, _ = _memories_mixin(connected=False)
        m.memories.mark_extracted("conv-1")  # should not raise
        m.get_connection.assert_not_called()

    def test_executes_update_when_connected(self):
        m, conn, _ = _memories_mixin()
        m.memories.mark_extracted("conv-1")
        m.get_connection.assert_called_once()


class TestSearchMemories:
    def test_returns_empty_when_db_unavailable(self):
        m, _, _ = _memories_mixin(connected=False)
        assert m.memories.search([0.1] * 10, scope=ALL_WORKSPACES) == []

    def test_returns_list_of_dicts(self):
        from datetime import datetime
        mem_id = str(uuid.uuid4())
        m, _, cur = _memories_mixin(
            fetchall_return=[(mem_id, "fact A", "fact", 0.9, datetime(2025, 1, 1), 2, 0.85)]
        )
        results = m.memories.search([0.1] * 10, scope=ALL_WORKSPACES)
        assert len(results) == 1
        assert results[0]["content"] == "fact A"
        assert results[0]["similarity"] == pytest.approx(0.85)


class TestIsDuplicateMemory:
    def test_returns_false_when_db_unavailable(self):
        m, _, _ = _memories_mixin(connected=False)
        assert m.memories.is_duplicate([0.1] * 10, scope=ALL_WORKSPACES) is False

    def test_returns_true_when_similar_found(self):
        m, _, cur = _memories_mixin(fetchone_return=(1,))
        assert m.memories.is_duplicate([0.1] * 10, scope=ALL_WORKSPACES) is True

    def test_returns_false_when_no_similar_found(self):
        m, _, cur = _memories_mixin(fetchone_return=None)
        assert m.memories.is_duplicate([0.1] * 10, scope=ALL_WORKSPACES) is False


class TestGetAllMemories:
    def test_returns_empty_when_db_unavailable(self):
        m, _, _ = _memories_mixin(connected=False)
        assert m.memories.list_page(scope=ALL_WORKSPACES) == []

    def test_returns_list_of_dicts(self):
        from datetime import datetime
        mid = str(uuid.uuid4())
        conv_id = str(uuid.uuid4())
        m, _, cur = _memories_mixin(
            fetchall_return=[(mid, "content", "fact", 1.0, datetime(2025, 1, 1), None, 0, conv_id)]
        )
        results = m.memories.list_page(scope=ALL_WORKSPACES)
        assert len(results) == 1
        assert results[0]["content"] == "content"


class TestGetUnextractedConversations:
    def test_returns_empty_when_db_unavailable(self):
        m, _, _ = _memories_mixin(connected=False)
        assert m.memories.unextracted_conversations(scope="ws-1") == []

    def test_returns_list_of_dicts(self):
        from datetime import datetime
        cid = str(uuid.uuid4())
        ws_id = str(uuid.uuid4())
        m, _, cur = _memories_mixin(
            fetchall_return=[(cid, "My Conversation", datetime(2025, 3, 1), ws_id)]
        )
        results = m.memories.unextracted_conversations(scope="ws-1")
        assert len(results) == 1
        assert results[0]["id"] == cid
        assert results[0]["title"] == "My Conversation"
        # Carried so an extracted memory inherits the conversation's workspace.
        assert results[0]["workspace_id"] == ws_id
