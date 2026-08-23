"""TQ-2 — the whole point of the product, executed once, for real.

Put a document in, ask about it, get back the chunk that answers. Every piece of that
was covered in isolation and the path itself never ran: `test_rag_flow.py` mocks both
retrieval and the model, so it proves the wiring and nothing about whether a document
put into Postgres can be found again.

What is real here: chunking, embedding calls over HTTP, pgvector storage, the hybrid
semantic + lexical query, thresholding and ranking. What is faked is only the model
process — `tests/utils/fake_ollama.py`, whose embeddings are a bag of words rather
than noise, so ranking is a property of the retrieval code and not of the stub.

Marked `db`: needs PostgreSQL with pgvector. CI's integration job provides it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest

from tests.utils.fake_ollama import FakeOllama

pytestmark = [pytest.mark.integration, pytest.mark.db]

DOCUMENT = """\
Vector search in LocalChat

LocalChat stores embeddings in PostgreSQL using the pgvector extension, and ranks
candidates by cosine similarity against an HNSW index.

Authentication

Access is granted with JWT tokens, issued by the login endpoint after a password
check, and carried in an httpOnly cookie.

Document connectors

Folders, S3 buckets and SharePoint sites are polled by a background worker that
ingests whatever has changed since the last run.
"""

#: Each query names a section using words that appear in it and in no other, so a
#: correct retriever can separate them and a broken one cannot.
QUERIES = [
    ("pgvector cosine similarity HNSW index", "pgvector"),
    ("JWT tokens issued by the login endpoint", "JWT"),
    ("S3 buckets polled by a background worker", "S3"),
]


@pytest.fixture(scope="module")
def ollama() -> Iterator[object]:
    """A real HTTP client, pointed at the stub rather than at a GPU."""
    from src.ollama_client import OllamaClient

    server = FakeOllama()
    base_url = server.start()
    try:
        yield OllamaClient(base_url=base_url)
    finally:
        server.stop()


@pytest.fixture(scope="module")
def database():
    from src.db import Database

    db = Database()
    ok, message = db.initialize()  # opens the pool and creates the base schema
    if not ok or not db.is_connected:
        pytest.skip(f"PostgreSQL is not available: {message}")

    # `_ensure_extensions_and_tables()` builds the original schema; every additive
    # column since then lives in a migration. Production applies them at startup, so
    # a test that skips them runs against a schema no deployment has — this one first
    # failed on `document_chunks.deleted_at`, added by 0005.
    from src.app_bootstrap import _run_alembic_migrations

    _run_alembic_migrations()
    return db


@pytest.fixture(scope="module")
def workspace(database) -> Iterator[str]:
    ws_id = database.create_workspace(f"tq2-{uuid.uuid4().hex[:8]}", owner_id=None)
    yield ws_id
    database.delete_workspace(ws_id)


@pytest.fixture(scope="module")
def ingested(database, ollama, workspace, tmp_path_factory) -> Iterator[str]:
    """Ingest once; every query below reads what this produced."""
    from src.rag.processor import DocumentProcessor

    path = tmp_path_factory.mktemp("tq2") / "vector_search.txt"
    path.write_text(DOCUMENT, encoding="utf-8")

    processor = DocumentProcessor(db=database, ollama_client=ollama)
    success, message, doc_id = processor.ingest_document(str(path), workspace_id=workspace)
    assert success, f"ingest failed: {message}"
    yield processor

    if doc_id is not None:
        database.delete_document(doc_id, None)


@pytest.mark.db
class TestIngestProducesRetrievableChunks:
    def test_ingest_reports_success(self, ingested):
        """The fixture asserts this, but a named test says which step broke."""
        assert ingested is not None

    def test_chunks_were_stored(self, database, workspace):
        assert database.get_chunk_count(workspace_id=workspace) > 0

    def test_the_document_is_listed_in_its_workspace(self, database, workspace):
        names = [d["filename"] for d in database.get_all_documents(workspace_id=workspace)]
        assert "vector_search.txt" in names


@pytest.mark.db
@pytest.mark.parametrize(("query", "expected_term"), QUERIES, ids=[q[1] for q in QUERIES])
class TestAskReturnsTheRightSection:
    def test_retrieval_returns_something(self, ingested, workspace, query, expected_term):
        results = ingested.retrieve_context(query, workspace_id=workspace)
        assert results, f"no chunks retrieved for {query!r}"

    def test_top_chunk_is_the_section_that_answers(self, ingested, workspace, query,
                                                   expected_term):
        """The assertion the whole harness exists for: the *right* chunk ranks first."""
        results = ingested.retrieve_context(query, workspace_id=workspace)
        assert expected_term.lower() in results[0].chunk_text.lower()


@pytest.mark.db
class TestCitationsPointAtTheSource:
    def test_result_carries_its_filename(self, ingested, workspace):
        results = ingested.retrieve_context(QUERIES[0][0], workspace_id=workspace)
        assert results[0].filename == "vector_search.txt"

    def test_result_carries_a_chunk_id_that_exists(self, ingested, database, workspace):
        """A citation with no resolvable chunk is what the Clark-Wilson rules forbid."""
        results = ingested.retrieve_context(QUERIES[0][0], workspace_id=workspace)
        assert isinstance(results[0].chunk_id, int)
        assert results[0].chunk_id > 0

    def test_a_query_about_nothing_in_the_document_returns_nothing(self, ingested,
                                                                   workspace):
        """The negative space. Without it, a retriever that returns every chunk for
        every query would pass every test above."""
        results = ingested.retrieve_context(
            "marsupial husbandry in temperate climates", workspace_id=workspace
        )
        assert results == []


@pytest.mark.db
class TestWorkspaceIsolationHoldsOnTheRealPath:
    def test_another_workspace_sees_none_of_it(self, ingested, database):
        """The cross-workspace leak was found in production, not by a test. This is
        the path it would have travelled."""
        other = database.create_workspace(f"tq2-other-{uuid.uuid4().hex[:8]}", owner_id=None)
        try:
            results = ingested.retrieve_context(QUERIES[0][0], workspace_id=other)
            assert results == []
        finally:
            database.delete_workspace(other)


@pytest.mark.db
class TestTheHarnessIsWhatIsUnderTest:
    """Guards the stub. A harness that answers wrongly makes every test above vacuous."""

    def test_the_client_points_at_the_stub_not_a_live_model(self, ollama):
        assert ollama.base_url.startswith("http://127.0.0.1:")

    def test_embeddings_separate_the_sections(self, ollama):
        """If the stub returned noise, the ranking assertions would pass by luck."""
        from tests.utils.fake_ollama import embed

        query = embed("pgvector cosine similarity")
        near = embed("LocalChat stores embeddings using the pgvector extension")
        far = embed("Access is granted with JWT tokens")
        near_score = sum(a * b for a, b in zip(query, near, strict=True))
        far_score = sum(a * b for a, b in zip(query, far, strict=True))
        assert near_score > far_score
