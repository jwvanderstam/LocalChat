"""R-12 (QP-9 review) against Postgres — GraphRAG's expansion reads only the caller's workspace.

Entities are shared across workspaces, keyed on name and type alone, so the 1-hop lookup
returned names that co-occurred in any workspace's documents, retired ones included. With
GraphRAG on, those names were appended to the caller's query. Now a co-occurrence counts
only through a live document of the scope.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.db]


@pytest.fixture(scope="module")
def database() -> Any:
    from src.db import Database

    db = Database()
    ok, message = db.initialize()
    if not ok or not db.is_connected:
        pytest.skip(f"PostgreSQL is not available: {message}")
    from src.app_bootstrap import _run_alembic_migrations

    _run_alembic_migrations()
    return db


@pytest.fixture()
def workspaces(database: Any) -> Iterator[tuple[str, str]]:
    a = database.workspaces.create(f"r12-a-{uuid.uuid4().hex[:8]}", owner_id=None)
    b = database.workspaces.create(f"r12-b-{uuid.uuid4().hex[:8]}", owner_id=None)
    yield a, b
    database.workspaces.retire(a)
    database.workspaces.retire(b)


def _relate(database: Any, ws: str, anchor: str, other: str) -> int:
    """A document in *ws* in which *anchor* and *other* co-occur; returns its id."""
    tag = uuid.uuid4().hex[:8]
    doc = database.documents.insert(f"r12-{tag}.txt", f"{anchor} {other}", workspace_id=ws, scope=ws)
    chunk = database.documents.insert_chunks([(doc, f"{anchor} {other}", 0, [0.02] * 768)], scope=ws)[0]
    database.entities.insert_relation(
        database.entities.upsert(anchor, "ORG"), database.entities.upsert(other, "ORG"), doc, chunk)
    return doc


def test_a_name_from_another_workspace_is_not_returned(database, workspaces):
    a, b = workspaces
    anchor = f"Anchor{uuid.uuid4().hex[:6]}"
    _relate(database, a, anchor, f"{anchor}Own")
    _relate(database, b, anchor, f"{anchor}Foreign")
    assert database.entities.related_names([anchor], scope=a) == [f"{anchor}Own"]


def test_a_retired_document_contributes_nothing(database, workspaces):
    a, _ = workspaces
    anchor = f"Anchor{uuid.uuid4().hex[:6]}"
    doc = _relate(database, a, anchor, f"{anchor}Retired")
    database.documents.retire(doc, scope=a)
    assert database.entities.related_names([anchor], scope=a) == []


def test_a_chunk_retired_by_a_reingest_contributes_nothing(database, workspaces):
    """A name removed from a document must not outlive the re-ingest that removed it."""
    a, _ = workspaces
    anchor = f"Anchor{uuid.uuid4().hex[:6]}"
    doc = _relate(database, a, anchor, f"{anchor}Old")
    database.documents.retire_chunks(doc, scope=a)
    assert database.entities.related_names([anchor], scope=a) == []
