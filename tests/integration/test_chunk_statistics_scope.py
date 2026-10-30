"""R-1 (QP-9 review) — `GET /api/documents/stats` reads only the caller's workspace.

`chunk_statistics()` opened an all-workspaces transaction and returned three random chunk
previews from every workspace, so any viewer could collect other workspaces' text by
polling it. The unit tests mocked the method and only checked that its siblings got the
scope. This runs it against Postgres with a second workspace and a retired document next to
the caller's own.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.db]

DIM = 768


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


def _document(db, workspace: str, filename: str, text: str) -> int:
    doc_id = db.documents.insert(filename, text, workspace_id=workspace, scope=workspace)
    db.documents.insert_chunks([(doc_id, text, 0, [0.1] * DIM)], scope=workspace)
    return doc_id


@pytest.fixture(scope="module")
def workspaces(database) -> Iterator[tuple[str, str]]:
    """A holds one live and one retired document; B holds one live document."""
    tag = uuid.uuid4().hex[:8]
    a = database.workspaces.create(f"r1-a-{tag}", owner_id=None)
    b = database.workspaces.create(f"r1-b-{tag}", owner_id=None)
    _document(database, a, f"a-live-{tag}.txt", "workspace A's own text")
    retired = _document(database, a, f"a-retired-{tag}.txt", "retired text in A")
    database.documents.retire(retired, None, scope=a)
    _document(database, b, f"b-secret-{tag}.txt", "workspace B's private text")
    yield a, b
    database.workspaces.retire(a)
    database.workspaces.retire(b)


def test_chunk_statistics_counts_only_the_live_chunks_of_its_workspace(database, workspaces):
    a, _ = workspaces
    assert database.documents.chunk_statistics(scope=a)["total_chunks"] == 1


def test_chunk_statistics_counts_the_other_workspace_on_its_own(database, workspaces):
    # The counterpart: B's chunk exists and is counted for B, so A's 1 is not an empty read.
    _, b = workspaces
    assert database.documents.chunk_statistics(scope=b)["total_chunks"] == 1


def test_chunk_statistics_samples_name_no_document_outside_the_workspace(database, workspaces):
    a, _ = workspaces
    samples = database.documents.chunk_statistics(scope=a)["sample_chunks"]
    assert all(s["filename"].startswith("a-live-") for s in samples)
