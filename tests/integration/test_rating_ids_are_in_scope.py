"""R-8 (QP-9 review) — the lookups behind a rating, against Postgres under row-level security.

A rating names a message and chunks, and a chunk's `chunk_stats` row blocks its document's
purge. The caller's own and the global tier's chunks are citable, because a hybrid answer
cites both; another workspace's, a retired and an archived one are not.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest

from src.utils.scope import ALL_WORKSPACES

pytestmark = [pytest.mark.integration, pytest.mark.db]

DIM = 768


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


def _chunk(database: Any, workspace: str, filename: str) -> tuple[int, int]:
    doc_id = database.documents.insert(filename, "content", workspace_id=workspace, scope=workspace)
    [chunk_id] = database.documents.insert_chunks(
        [(doc_id, f"{filename} chunk", 0, [0.1] * DIM)], scope=ALL_WORKSPACES
    )
    return doc_id, chunk_id


def _global_chunk(database: Any, global_doc: int) -> int:
    with database.get_connection(scope=ALL_WORKSPACES) as conn:
        return conn.execute(
            "SELECT id FROM document_chunks WHERE document_id = %s AND deleted_at IS NULL", (global_doc,)
        ).fetchone()[0]


@pytest.fixture()
def world(database: Any) -> Iterator[SimpleNamespace]:
    tag = uuid.uuid4().hex[:8]
    a = database.workspaces.create(f"r8-a-{tag}", owner_id=None)
    b = database.workspaces.create(f"r8-b-{tag}", owner_id=None)
    admin = database.users.create(f"r8-admin-{tag}", "x", role="admin")
    _, own = _chunk(database, a, f"own-{tag}.txt")
    source, foreign = _chunk(database, b, f"foreign-{tag}.txt")
    [contribution] = database.contributions.contribute(b, [source], admin)
    yield SimpleNamespace(
        a=a, b=b, admin=admin, own=own, foreign=foreign,
        shared=_global_chunk(database, contribution["global_document_id"]),
    )
    database.contributions.archive(b, None)
    for ws in (a, b):
        database.documents.retire_all(scope=ws)
        database.workspaces.retire(ws)


def test_a_workspaces_own_chunk_is_citable(database: Any, world: SimpleNamespace) -> None:
    assert database.documents.citable_chunk_ids([world.own], scope=world.a) == {world.own}


def test_a_global_chunk_is_citable_from_any_workspace(database: Any, world: SimpleNamespace) -> None:
    assert database.documents.citable_chunk_ids([world.shared], scope=world.a) == {world.shared}


def test_another_workspaces_chunk_is_not_citable(database: Any, world: SimpleNamespace) -> None:
    assert database.documents.citable_chunk_ids([world.own, world.foreign], scope=world.a) == {world.own}


def test_an_archived_contribution_is_not_citable(database: Any, world: SimpleNamespace) -> None:
    database.contributions.archive(world.b, world.admin)
    assert database.documents.citable_chunk_ids([world.shared], scope=world.a) == set()


def test_a_retired_documents_chunk_is_not_citable(database: Any, world: SimpleNamespace) -> None:
    database.documents.retire_all(scope=world.a)
    assert database.documents.citable_chunk_ids([world.own], scope=world.a) == set()


def test_a_message_in_a_live_conversation_of_the_scope_is_found(database: Any, world: SimpleNamespace) -> None:
    _, message = database.conversations.create_with_message("c", "user", "hi", workspace_id=world.a)
    assert database.conversations.has_message(message, scope=world.a) is True


def test_another_workspaces_message_is_not_found(database: Any, world: SimpleNamespace) -> None:
    _, message = database.conversations.create_with_message("c", "user", "hi", workspace_id=world.b)
    assert database.conversations.has_message(message, scope=world.a) is False


def test_a_retired_conversations_message_is_not_found(database: Any, world: SimpleNamespace) -> None:
    conversation, message = database.conversations.create_with_message("c", "user", "hi", workspace_id=world.a)
    database.conversations.retire(conversation, None, scope=world.a)
    assert database.conversations.has_message(message, scope=world.a) is False
