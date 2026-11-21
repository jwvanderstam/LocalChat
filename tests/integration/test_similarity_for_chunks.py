"""`similarity_for_chunks` scores the query against named chunks inside the caller's scope only.

Hybrid retrieval uses it to give a chunk only the lexical arm found its real similarity. The ids
come from the caller's own search, but the method is still a read by id, so it must not answer
for another workspace's chunk or a retired document's.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.db]

DIM = 768
X = [1.0] + [0.0] * (DIM - 1)
DIAGONAL = [0.6, 0.8] + [0.0] * (DIM - 2)  # cosine 0.6 against X


@pytest.fixture(scope="module")
def database():
    from src.db import Database

    db = Database()
    ok, message = db.initialize()
    if not ok or not db.is_connected:
        pytest.skip(f"PostgreSQL is not available: {message}")

    from src.app_bootstrap import _run_alembic_migrations

    _run_alembic_migrations()
    return db


def _document(db, workspace: str, filename: str, embedding: list[float]) -> tuple[int, int]:
    """(document id, chunk id)."""
    doc_id = db.documents.insert(filename, "text", workspace_id=workspace, scope=workspace)
    db.documents.insert_chunks([(doc_id, f"chunk of {filename}", 0, embedding)], scope=workspace)
    rows = db.documents.search_similar(embedding, top_k=50, filename_filter=[filename], scope=workspace)
    return doc_id, rows[0][5]


@pytest.fixture(scope="module")
def chunks(database) -> Iterator[dict[str, object]]:
    tag = uuid.uuid4().hex[:8]
    a = database.workspaces.create(f"sim-a-{tag}", owner_id=None)
    b = database.workspaces.create(f"sim-b-{tag}", owner_id=None)
    _, own = _document(database, a, f"a-{tag}.docx", DIAGONAL)
    retired_doc, retired = _document(database, a, f"a-retired-{tag}.docx", X)
    before_retirement = database.documents.similarity_for_chunks(X, [retired], scope=a)
    database.documents.retire(retired_doc, None, scope=a)
    _, foreign = _document(database, b, f"b-{tag}.docx", X)
    yield {"a": a, "b": b, "own": own, "retired": retired, "foreign": foreign,
           "before_retirement": before_retirement}
    database.workspaces.retire(a)
    database.workspaces.retire(b)


def test_a_chunk_in_scope_gets_its_cosine_similarity(database, chunks):
    scores = database.documents.similarity_for_chunks(X, [chunks["own"]], scope=chunks["a"])

    assert scores.keys() == {chunks["own"]}
    assert scores[chunks["own"]] == pytest.approx(0.6)


def test_another_workspaces_chunk_is_not_scored(database, chunks):
    ids = [chunks["own"], chunks["foreign"]]

    assert database.documents.similarity_for_chunks(X, ids, scope=chunks["a"]).keys() == {chunks["own"]}


def test_the_other_workspace_scores_its_own_chunk(database, chunks):
    # The counterpart: B's chunk exists and is scored for B, so A's miss is not an empty table.
    scores = database.documents.similarity_for_chunks(X, [chunks["foreign"]], scope=chunks["b"])

    assert scores == {chunks["foreign"]: pytest.approx(1.0)}


def test_a_retired_documents_chunk_is_not_scored(database, chunks):
    # Retiring a document leaves its chunks' own deleted_at empty; only the join excludes them.
    assert chunks["before_retirement"] == {chunks["retired"]: pytest.approx(1.0)}
    assert database.documents.similarity_for_chunks(X, [chunks["retired"]], scope=chunks["a"]) == {}


def test_no_ids_reads_nothing(database, chunks):
    assert database.documents.similarity_for_chunks(X, [], scope=chunks["a"]) == {}
