"""
Tests for src/db/entities.py (EntitiesMixin) and src/db/memories.py (MemoriesMixin)

Covers:
  EntitiesMixin:
    - upsert_entity: DB unavailable raises, returns UUID string
    - insert_entity_relation: DB unavailable is silent, normal call
    - delete_document_entities: DB unavailable is silent
    - get_related_entity_names: empty list, DB unavailable, returns rows
    - get_entity_by_name: not found, found
    - get_all_entities: DB unavailable returns []
    - get_entity_stats: DB unavailable returns zeros

  MemoriesMixin:
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
    from src.db.entities import EntitiesMixin

    conn, cur = _make_conn_ctx(**conn_kwargs)
    m = EntitiesMixin()
    m.is_connected = connected
    m.get_connection = MagicMock(return_value=conn)
    return m, conn, cur


def _memories_mixin(connected=True, **conn_kwargs):
    from src.db.memories import MemoriesMixin

    conn, cur = _make_conn_ctx(**conn_kwargs)
    m = MemoriesMixin()
    m.is_connected = connected
    m.get_connection = MagicMock(return_value=conn)
    m._embedding_to_pg_array = MagicMock(return_value="[0.1,0.2]")
    return m, conn, cur


# ===========================================================================
# EntitiesMixin
# ===========================================================================

class TestUpsertEntity:
    def test_raises_when_db_unavailable(self):
        from src.db.connection import DatabaseUnavailableError
        m, _, _ = _entities_mixin(connected=False)
        with pytest.raises(DatabaseUnavailableError):
            m.upsert_entity("Apple", "ORG")

    def test_returns_string_id(self):
        eid = str(uuid.uuid4())
        m, _, cur = _entities_mixin(fetchone_return=(eid,))
        result = m.upsert_entity("Apple", "ORG")
        assert result == eid

    def test_calls_executemany_or_execute(self):
        m, _, cur = _entities_mixin(fetchone_return=(str(uuid.uuid4()),))
        m.upsert_entity("Google", "ORG")
        assert cur.execute.call_count >= 1


class TestInsertEntityRelation:
    def test_no_op_when_db_unavailable(self):
        m, _, _ = _entities_mixin(connected=False)
        # Should not raise
        m.insert_entity_relation("id-a", "id-b", 1, 10)
        m.get_connection.assert_not_called()

    def test_calls_connection_when_connected(self):
        m, conn, _ = _entities_mixin()
        m.insert_entity_relation("id-a", "id-b", 1, 10)
        m.get_connection.assert_called_once()

    def test_custom_relation_and_weight(self):
        m, _, cur = _entities_mixin()
        m.insert_entity_relation("a", "b", 1, 2, relation="co_authors", weight=3.0)
        assert cur.execute.call_count >= 1


class TestDeleteDocumentEntities:
    def test_no_op_when_db_unavailable(self):
        m, _, _ = _entities_mixin(connected=False)
        m.delete_document_entities(99)
        m.get_connection.assert_not_called()

    def test_calls_delete_when_connected(self):
        m, conn, _ = _entities_mixin()
        m.delete_document_entities(5)
        m.get_connection.assert_called_once()


class TestGetRelatedEntityNames:
    def test_returns_empty_for_empty_input(self):
        m, _, _ = _entities_mixin()
        result = m.get_related_entity_names([])
        assert result == []
        m.get_connection.assert_not_called()

    def test_returns_empty_when_db_unavailable(self):
        m, _, _ = _entities_mixin(connected=False)
        result = m.get_related_entity_names(["Apple"])
        assert result == []

    def test_returns_names_from_db(self):
        m, _, cur = _entities_mixin(fetchall_return=[("Google",), ("Microsoft",)])
        result = m.get_related_entity_names(["Apple"])
        assert result == ["Google", "Microsoft"]


class TestGetEntityByName:
    def test_returns_none_when_not_found(self):
        m, _, cur = _entities_mixin(fetchone_return=None)
        result = m.get_entity_by_name("Unknown")
        assert result is None

    def test_returns_dict_when_found(self):
        eid = str(uuid.uuid4())
        m, _, cur = _entities_mixin(fetchone_return=(eid, "Apple", "ORG", 3))
        result = m.get_entity_by_name("Apple")
        assert result == {"id": eid, "name": "Apple", "type": "ORG", "doc_count": 3}

    def test_returns_none_when_db_unavailable(self):
        m, _, _ = _entities_mixin(connected=False)
        assert m.get_entity_by_name("X") is None


class TestGetAllEntities:
    def test_returns_empty_when_db_unavailable(self):
        m, _, _ = _entities_mixin(connected=False)
        assert m.get_all_entities() == []

    def test_returns_list_of_dicts(self):
        eid = str(uuid.uuid4())
        m, _, cur = _entities_mixin(fetchall_return=[(eid, "Apple", "ORG", 5)])
        result = m.get_all_entities()
        assert len(result) == 1
        assert result[0]["name"] == "Apple"


class TestGetEntityStats:
    def test_returns_zeros_when_db_unavailable(self):
        m, _, _ = _entities_mixin(connected=False)
        stats = m.get_entity_stats()
        assert stats == {"entity_count": 0, "relation_count": 0}

    def test_returns_counts_from_db(self):
        m, _, cur = _entities_mixin()
        cur.fetchone.side_effect = [(10,), (25,)]
        stats = m.get_entity_stats()
        assert stats["entity_count"] == 10
        assert stats["relation_count"] == 25


# ===========================================================================
# MemoriesMixin
# ===========================================================================

class TestInsertMemory:
    def test_raises_when_db_unavailable(self):
        from src.db.connection import DatabaseUnavailableError
        m, _, _ = _memories_mixin(connected=False)
        with pytest.raises(DatabaseUnavailableError):
            m.insert_memory("content", [0.1] * 10)

    def test_returns_uuid_string(self):
        m, _, _ = _memories_mixin()
        result = m.insert_memory("fact about X", [0.1] * 10)
        # Must be a valid UUID
        uuid.UUID(result)

    def test_calls_embedding_conversion(self):
        m, _, _ = _memories_mixin()
        m.insert_memory("fact", [0.5] * 8)
        m._embedding_to_pg_array.assert_called_once()


class TestUpdateMemoryUsage:
    def test_no_op_on_empty_list(self):
        m, _, _ = _memories_mixin()
        m.update_memory_usage([])
        m.get_connection.assert_not_called()

    def test_no_op_when_db_unavailable(self):
        m, _, _ = _memories_mixin(connected=False)
        m.update_memory_usage(["mem-1"])
        m.get_connection.assert_not_called()

    def test_executes_update_when_connected(self):
        m, conn, _ = _memories_mixin()
        m.update_memory_usage(["mem-1", "mem-2"])
        m.get_connection.assert_called_once()


class TestDeleteMemory:
    def test_raises_when_db_unavailable(self):
        from src.db.connection import DatabaseUnavailableError
        m, _, _ = _memories_mixin(connected=False)
        with pytest.raises(DatabaseUnavailableError):
            m.delete_memory("some-uuid")

    def test_executes_delete_when_connected(self):
        m, conn, _ = _memories_mixin()
        m.delete_memory("mem-uuid")
        m.get_connection.assert_called_once()


class TestDeleteAllMemories:
    def test_raises_when_db_unavailable(self):
        from src.db.connection import DatabaseUnavailableError
        m, _, _ = _memories_mixin(connected=False)
        with pytest.raises(DatabaseUnavailableError):
            m.delete_all_memories()

    def test_returns_count(self):
        m, _, cur = _memories_mixin(rowcount=7)
        count = m.delete_all_memories()
        assert count == 7


class TestMarkConversationExtracted:
    def test_no_op_when_db_unavailable(self):
        m, _, _ = _memories_mixin(connected=False)
        m.mark_conversation_extracted("conv-1")  # should not raise
        m.get_connection.assert_not_called()

    def test_executes_update_when_connected(self):
        m, conn, _ = _memories_mixin()
        m.mark_conversation_extracted("conv-1")
        m.get_connection.assert_called_once()


class TestSearchMemories:
    def test_returns_empty_when_db_unavailable(self):
        m, _, _ = _memories_mixin(connected=False)
        assert m.search_memories([0.1] * 10) == []

    def test_returns_list_of_dicts(self):
        from datetime import datetime
        mem_id = str(uuid.uuid4())
        m, _, cur = _memories_mixin(
            fetchall_return=[(mem_id, "fact A", "fact", 0.9, datetime(2025, 1, 1), 2, 0.85)]
        )
        results = m.search_memories([0.1] * 10)
        assert len(results) == 1
        assert results[0]["content"] == "fact A"
        assert results[0]["similarity"] == pytest.approx(0.85)


class TestIsDuplicateMemory:
    def test_returns_false_when_db_unavailable(self):
        m, _, _ = _memories_mixin(connected=False)
        assert m.is_duplicate_memory([0.1] * 10) is False

    def test_returns_true_when_similar_found(self):
        m, _, cur = _memories_mixin(fetchone_return=(1,))
        assert m.is_duplicate_memory([0.1] * 10) is True

    def test_returns_false_when_no_similar_found(self):
        m, _, cur = _memories_mixin(fetchone_return=None)
        assert m.is_duplicate_memory([0.1] * 10) is False


class TestGetAllMemories:
    def test_returns_empty_when_db_unavailable(self):
        m, _, _ = _memories_mixin(connected=False)
        assert m.get_all_memories() == []

    def test_returns_list_of_dicts(self):
        from datetime import datetime
        mid = str(uuid.uuid4())
        conv_id = str(uuid.uuid4())
        m, _, cur = _memories_mixin(
            fetchall_return=[(mid, "content", "fact", 1.0, datetime(2025, 1, 1), None, 0, conv_id)]
        )
        results = m.get_all_memories()
        assert len(results) == 1
        assert results[0]["content"] == "content"


class TestGetUnextractedConversations:
    def test_returns_empty_when_db_unavailable(self):
        m, _, _ = _memories_mixin(connected=False)
        assert m.get_unextracted_conversations() == []

    def test_returns_list_of_dicts(self):
        from datetime import datetime
        cid = str(uuid.uuid4())
        m, _, cur = _memories_mixin(
            fetchall_return=[(cid, "My Conversation", datetime(2025, 3, 1))]
        )
        results = m.get_unextracted_conversations()
        assert len(results) == 1
        assert results[0]["id"] == cid
        assert results[0]["title"] == "My Conversation"
