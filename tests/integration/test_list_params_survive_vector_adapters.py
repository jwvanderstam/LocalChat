"""A `list[str]` query parameter reaches PostgreSQL intact.

`register_vector_types()` used to register a pgvector dumper for the Python type
`list`. psycopg selects a dumper by the parameter's Python type, so that dumper was
applied to *every* list parameter, and its `float(v)` conversion raised

    ValueError: could not convert string to float: 'PERMISSIONS.md'

on any `list[str]`. Every `= ANY(%s)` in the codebase was therefore dead:

* `search_similar_chunks(filename_filter=...)` and `source_ids=...` — the "chat with
  only these documents" feature, which raised up through `retrieve_context()`.
* `get_related_entity_names()` — GraphRAG's 1-hop expansion, whose caller catches
  `Exception`, logs at **debug** and returns `[]`. The feature never once ran, and
  DEL-2's recorded "expansion fires on 0/20 questions" was measuring that crash
  rather than a semantic mismatch.

The dumper was vestigial: every embedding is serialised by `_embedding_to_pg_array()`
and passed to an explicit `%s::vector` cast, so no raw list ever needed adapting. Only
the *loader* is registered now.

These tests take the two shapes that matter — a bare `= ANY(%s)` and the retrieval
path — and assert on returned values rather than on absence of an exception, so a
future dumper that silently returns nothing fails here too.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator

import psycopg
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.db]

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _admin_dsn() -> dict[str, object]:
    from src import config

    return {
        "host": config.PG_HOST,
        "port": config.PG_PORT,
        "user": config.PG_USER,
        "password": config.PG_PASSWORD,
        "dbname": "postgres",
        "connect_timeout": 5,
    }


@pytest.fixture(scope="module")
def database() -> Iterator[str]:
    """A database of its own, with the base schema the application creates."""
    dbname = f"listparam_{uuid.uuid4().hex[:10]}"
    try:
        with psycopg.connect(**_admin_dsn()) as conn:  # type: ignore[arg-type]
            conn.autocommit = True
            conn.execute(f'CREATE DATABASE "{dbname}"')
    except psycopg.Error as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")

    try:
        create = subprocess.run(
            [sys.executable, "-c",
             "from src.db import Database; ok, msg = Database().initialize();"
             " raise SystemExit(0 if ok else msg)"],
            cwd=REPO_ROOT, env={**os.environ, "PG_DB": dbname},
            capture_output=True, text=True, timeout=300,
        )
        assert create.returncode == 0, f"base schema failed: {create.stdout}{create.stderr}"

        # The base schema is only half of it: documents.content_hash and every other
        # additive column live in Alembic, exactly as bootstrap_app() applies them.
        migrate = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=REPO_ROOT, env={**os.environ, "PG_DB": dbname},
            capture_output=True, text=True, timeout=300,
        )
        assert migrate.returncode == 0, f"migrations failed: {migrate.stdout}{migrate.stderr}"
        yield dbname
    finally:
        with psycopg.connect(**_admin_dsn()) as conn:  # type: ignore[arg-type]
            conn.autocommit = True
            conn.execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')


def _run(dbname: str, body: str) -> subprocess.CompletedProcess[str]:
    """Run a snippet against `dbname` in its own process, so adapters register fresh.

    Each snippet ends with `db.close()`. Without it the pool's finaliser runs at
    interpreter shutdown and can raise PythonFinalizationError, which would fail these
    tests on their exit-status assertion for a reason unrelated to what they check.
    """
    return subprocess.run(
        [sys.executable, "-c", body],
        cwd=REPO_ROOT, env={**os.environ, "PG_DB": dbname},
        capture_output=True, text=True, timeout=300,
    )


@pytest.mark.db
class TestListOfStringsIsAcceptedAsAParameter:
    def test_entity_lookup_returns_the_co_occurring_name(self, database):
        """`= ANY(%s)` with a list[str]. Asserts the value, not merely no exception."""
        result = _run(database, """
from src.db import Database
db = Database(); db.initialize()
# entity_relations.doc_id/chunk_id are foreign keys, so a relation needs real rows.
doc = db.insert_document('entities.md', 'Ollama and Postgres', {}, 'hash-ent')
chunk_ids = db.insert_chunks_batch([(doc, 'Ollama and Postgres', 0, [0.02] * 768)])
a = db.upsert_entity('Ollama', 'PRODUCT')
b = db.upsert_entity('Postgres', 'ORG')
db.insert_entity_relation(a, b, doc, chunk_ids[0])
names = db.get_related_entity_names(['Ollama'], max_results=5)
assert names == ['Postgres'], names
db.close()
print('OK')
""")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "OK" in result.stdout

    def test_a_name_with_no_relations_returns_empty_not_an_error(self, database):
        """The negative case: empty is a real answer here, and must not be an exception."""
        result = _run(database, """
from src.db import Database
db = Database(); db.initialize()
db.upsert_entity('Solitary', 'ORG')
assert db.get_related_entity_names(['Solitary'], max_results=5) == []
db.close()
print('OK')
""")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "OK" in result.stdout


@pytest.mark.db
class TestTheDocumentFilterNarrowsRetrieval:
    def test_filename_filter_restricts_results_to_the_named_file(self, database):
        """The user-facing half: two documents in, one named, only that one comes back.

        Driven with two documents deliberately — with one, a filter that was ignored
        entirely would return the same rows and the test could not tell.
        """
        result = _run(database, """
from src.db import Database
db = Database(); db.initialize()
keep = db.insert_document('keep.md', 'alpha beta', {}, 'hash-keep')
drop = db.insert_document('drop.md', 'alpha beta', {}, 'hash-drop')
emb = [0.01] * 768
db.insert_chunks_batch([(keep, 'alpha beta gamma', 0, emb),
                        (drop, 'alpha beta gamma', 0, emb)])

# search_similar_chunks returns tuples:
# (chunk_text, filename, chunk_index, similarity, metadata, chunk_id)
FILENAME = 1
# Subset, not equality: the fixture database is module-scoped and earlier tests
# have left their own documents in it.
unfiltered = db.search_similar_chunks(emb, top_k=10, min_similarity=-1.0)
files = {r[FILENAME] for r in unfiltered}
assert {'keep.md', 'drop.md'} <= files, files

filtered = db.search_similar_chunks(emb, top_k=10, min_similarity=-1.0,
                                    filename_filter=['keep.md'])
assert filtered, 'filter returned nothing at all'
assert {r[FILENAME] for r in filtered} == {'keep.md'}, {r[FILENAME] for r in filtered}
db.close()
print('OK')
""")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "OK" in result.stdout


@pytest.mark.db
class TestEmbeddingsStillRoundTrip:
    def test_a_stored_vector_is_read_back_as_floats(self, database):
        """What the removed dumper was believed to be for. The loader still does it."""
        result = _run(database, """
from src.db import Database
db = Database(); db.initialize()
doc = db.insert_document('vec.md', 'body', {}, 'hash-vec')
emb = [0.125] * 768
db.insert_chunks_batch([(doc, 'body', 0, emb)])
hits = db.search_similar_chunks(emb, top_k=1, min_similarity=-1.0)
assert hits, 'vector search returned nothing'
assert hits[0][1] == 'vec.md', hits[0][1]       # filename
assert abs(hits[0][3] - 1.0) < 1e-6, hits[0][3]  # similarity to itself is 1.0
db.close()
print('OK')
""")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "OK" in result.stdout
