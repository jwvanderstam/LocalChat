"""GKB-1 — `retrieve_context(knowledge_scope=...)` reads the workspace, the global tier, or both.

The fake database answers by tier, so each mode is told apart by which chunk ids come
back. The workspace and global chunks deliberately share a filename and chunk index:
results are keyed and deduplicated by filename, and without the tier in that key one
would silently replace the other.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("PG_PASSWORD", "test-sentinel")

from src import config
from src.rag.retrieval import RetrievalMixin

pytestmark = pytest.mark.unit

WORKSPACE = "11111111-1111-1111-1111-111111111111"
LOCAL_ROW = ("Our own retrospective on the migration project.", "retro.md", 0, 0.92, {}, 1)
GLOBAL_ROW = ("A contributed lesson about database migrations.", "retro.md", 0, 0.88, {}, 2)


class FakeDb:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, bool]] = []

    def search_similar_chunks(self, _embedding, *, scope, global_tier=False, **_kw):
        self.calls.append(("semantic", scope, global_tier))
        return [GLOBAL_ROW] if global_tier else [LOCAL_ROW]

    def search_lexical_chunks(self, _query, *, scope, global_tier=False, **_kw):
        self.calls.append(("lexical", scope, global_tier))
        return []


class Retriever(RetrievalMixin):
    def __init__(self) -> None:
        self._db = FakeDb()
        self._ollama_client = MagicMock()
        self._ollama_client.get_embedding_model.return_value = "embedder"
        self._ollama_client.generate_embedding.return_value = (True, [0.1] * 8)


@pytest.fixture
def retriever():
    with (
        patch.object(config, "RERANKER_ENABLED", False),
        patch.object(config, "GRAPH_RAG_ENABLED", False),
    ):
        yield Retriever()


def _ids(results) -> set[int]:
    return {r.chunk_id for r in results}


def test_local_is_the_default_and_never_reads_the_global_tier(retriever):
    results = retriever.retrieve_context("migration lessons", scope=WORKSPACE)

    assert _ids(results) == {1}
    assert all(global_tier is False for _, _, global_tier in retriever._db.calls)


def test_global_reads_only_the_global_tier(retriever):
    results = retriever.retrieve_context(
        "migration lessons", scope=WORKSPACE, knowledge_scope="global"
    )

    assert _ids(results) == {2}
    assert all(global_tier is True for _, _, global_tier in retriever._db.calls)


def test_the_global_tier_is_read_through_the_callers_scope(retriever):
    """The connection stays scoped to the caller, so row-level security still applies."""
    retriever.retrieve_context("migration lessons", scope=WORKSPACE, knowledge_scope="global")

    assert {scope for _, scope, _ in retriever._db.calls} == {WORKSPACE}


def test_hybrid_returns_both_tiers_even_when_they_share_a_filename(retriever):
    results = retriever.retrieve_context(
        "migration lessons", scope=WORKSPACE, knowledge_scope="hybrid"
    )

    assert _ids(results) == {1, 2}


def test_only_global_results_are_marked_as_global(retriever):
    results = retriever.retrieve_context(
        "migration lessons", scope=WORKSPACE, knowledge_scope="hybrid"
    )

    tiers = {r.chunk_id: r.metadata.get("knowledge_tier") for r in results}
    assert tiers == {1: None, 2: "global"}


@pytest.mark.parametrize("filters", [
    {"filename_filter": ["retro.md"]},
    {"source_ids": ["22222222-2222-2222-2222-222222222222"]},
])
def test_a_document_filter_keeps_hybrid_to_the_workspace(retriever, filters):
    """A filter names the documents to answer from; global knowledge is not among them."""
    results = retriever.retrieve_context(
        "migration lessons", scope=WORKSPACE, knowledge_scope="hybrid", **filters
    )

    assert _ids(results) == {1}
    assert all(global_tier is False for _, _, global_tier in retriever._db.calls)


# ── the SQL each tier sends ───────────────────────────────────────────────────

def _connected_cursor():
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    return conn, cursor


def _search(method: str, global_tier: bool):
    from src import db as db_module

    conn, cursor = _connected_cursor()
    with (
        patch.object(db_module.db, "is_connected", True),
        patch.object(db_module.db, "get_connection") as get_conn,
    ):
        get_conn.return_value.__enter__.return_value = conn
        if method == "semantic":
            db_module.db.search_similar_chunks(
                [0.1] * 8, scope=WORKSPACE, global_tier=global_tier
            )
        else:
            db_module.db.search_lexical_chunks(
                "migration lessons", scope=WORKSPACE, global_tier=global_tier
            )
    sql, params = cursor.execute.call_args.args
    return get_conn.call_args.kwargs, sql, params


GLOBAL_MARKER = (
    "d.workspace_id IS NULL AND d.contributed_at IS NOT NULL AND d.archived_at IS NULL"
)


@pytest.mark.parametrize("method", ["semantic", "lexical"])
def test_the_global_tier_selects_contributed_unarchived_documents(method):
    conn_kwargs, sql, params = _search(method, global_tier=True)

    assert GLOBAL_MARKER in sql
    assert "d.workspace_id = %s" not in sql
    assert WORKSPACE not in params
    assert conn_kwargs == {"scope": WORKSPACE}


@pytest.mark.parametrize("method", ["semantic", "lexical"])
def test_the_workspace_tier_is_unchanged(method):
    _, sql, params = _search(method, global_tier=False)

    assert "d.workspace_id = %s" in sql
    assert GLOBAL_MARKER not in sql
    assert WORKSPACE in params
