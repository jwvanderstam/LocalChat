"""``POST /api/annotations`` refuses a malformed ``conversation_id`` before looking it up.

Postgres refuses anything but a UUID in that column, and the route answered 500.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.routes_fastapi.annotation_routes import router
from tests.utils.auth import admin_headers, authorise_db

CONVERSATION = "00000000-0000-4000-8000-000000000001"


def _client() -> tuple[MagicMock, TestClient]:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    db = MagicMock()
    db.documents.chunk_by_id.return_value = {"id": 5}
    db.conversations.document_filter.return_value = []
    db.annotations.add.return_value = "00000000-0000-4000-8000-0000000000a1"
    app.state.db = authorise_db(db, role="admin")
    client = TestClient(app, raise_server_exceptions=False)
    client.headers.update(admin_headers())
    return db, client


@pytest.mark.parametrize("conversation_id", ["not-a-uuid", f"urn:uuid:{CONVERSATION}", f"{{{CONVERSATION}}}", 12])
def test_a_malformed_conversation_id_is_a_400_and_nothing_is_written(conversation_id: object) -> None:
    db, client = _client()
    resp = client.post("/api/annotations", json={"chunk_id": 5, "text": "note", "conversation_id": conversation_id})
    assert (resp.status_code, db.conversations.document_filter.called, db.annotations.add.called) == (400, False, False)


def test_a_well_formed_conversation_id_is_looked_up_and_annotated() -> None:
    """The control: a check refusing every id would pass the test above."""
    db, client = _client()
    resp = client.post("/api/annotations", json={"chunk_id": 5, "text": "note", "conversation_id": CONVERSATION})
    assert resp.status_code == 201
    assert db.conversations.document_filter.call_args.args == (CONVERSATION,)
