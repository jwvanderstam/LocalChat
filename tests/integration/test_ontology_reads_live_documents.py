"""A workspace's ontology counts only its live documents and their live chunks.

`workspace_ontology` joined each relation to its document without asking whether the
document, or the chunk the relation came from, was retired, so a retired document's
entities kept shaping the ontology. Found by the separate review of #527.
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
def workspace(database: Any) -> Iterator[str]:
    ws = database.workspaces.create(f"onto-{uuid.uuid4().hex[:8]}", owner_id=None)
    yield ws
    database.workspaces.retire(ws)


def _relate(database: Any, ws: str, entity_type: str) -> int:
    tag = uuid.uuid4().hex[:8]
    doc = database.documents.insert(f"onto-{tag}.txt", "x", workspace_id=ws, scope=ws)
    chunk = database.documents.insert_chunks([(doc, "x", 0, [0.02] * 768)], scope=ws)[0]
    database.entities.insert_relation(
        database.entities.upsert(f"A{tag}", entity_type), database.entities.upsert(f"B{tag}", entity_type),
        doc, chunk)
    return doc


def test_a_retired_document_and_a_retired_chunk_leave_the_ontology(database, workspace):
    _relate(database, workspace, "LIVE")
    database.documents.retire(_relate(database, workspace, "RETIRED_DOC"), scope=workspace)
    database.documents.retire_chunks(_relate(database, workspace, "RETIRED_CHUNK"), scope=workspace)
    types = {t["type"] for t in database.entities.workspace_ontology(scope=workspace)["entity_types"]}
    assert types == {"LIVE"}
