"""GKB-2 — the contribution TPs against a real Postgres, migrations applied.

What only a database can show: the copy carries its chunks and embeddings, the upsert
lands on 0020's partial index (re-contributing updates in place, two projects may share a
filename), archiving takes a document out of what every workspace reads, and a refused
contribution writes nothing.

Every read of the global tier here goes through `get_connection(scope=<another
workspace>)` — the restricted role under row-level security, which is how a workspace
actually sees the tier — not through the owner connection the writes use.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.db]

DIM = 768


def _vector(seed: int) -> list[float]:
    return [float((seed + i) % 7) / 7 for i in range(DIM)]


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


@pytest.fixture(scope="module")
def admin(database: Any) -> str:
    return database.users.create(f"gkb2-admin-{uuid.uuid4().hex[:8]}", "x", role="admin")


@pytest.fixture()
def workspaces(database: Any) -> Iterator[dict[str, str]]:
    """Two contributing projects and a reader, each new per test so filenames never meet."""
    suffix = uuid.uuid4().hex[:8]
    ids = {name: database.workspaces.create(f"gkb2-{name}-{suffix}", owner_id=None)
           for name in ("a", "b", "reader")}
    yield ids
    for ws in ids.values():
        database.contributions.archive(ws, None)
        database.documents.retire_all(scope=ws)
        database.workspaces.retire(ws)


def _document(database: Any, workspace: str, filename: str, chunks: int = 2) -> int:
    doc_id = database.documents.insert(filename, f"{filename} content", workspace_id=workspace)
    database.documents.insert_chunks(
        [(doc_id, f"{filename} chunk {i}", i, _vector(doc_id + i)) for i in range(chunks)]
    )
    return doc_id


def _visible(database: Any, scope: str, doc_id: int) -> list[tuple[str, int]]:
    """What *scope* reads of *doc_id* under RLS: its live chunk texts, by index."""
    with database.get_connection(scope=scope) as conn:
        return conn.execute(
            "SELECT chunk_text, chunk_index FROM document_chunks"
            " WHERE document_id = %s AND deleted_at IS NULL ORDER BY chunk_index",
            (doc_id,),
        ).fetchall()


def _owner_row(database: Any, doc_id: int) -> tuple[Any, ...]:
    with database.get_connection() as conn:
        return conn.execute(
            "SELECT workspace_id, source_project_id::text, contributed_by::text, archived_at"
            " FROM documents WHERE id = %s",
            (doc_id,),
        ).fetchone()


def test_a_contribution_copies_the_document_and_its_chunks_into_the_global_tier(
    database: Any, workspaces: dict[str, str], admin: str
) -> None:
    source = _document(database, workspaces["a"], "retro.md", chunks=3)
    [result] = database.contributions.contribute(workspaces["a"], [source], admin)

    assert (result["document_id"], result["filename"], result["chunks"], result["updated"]) == (
        source, "retro.md", 3, False)
    assert result["global_document_id"] != source
    assert _owner_row(database, result["global_document_id"]) == (
        None, workspaces["a"], admin, None)
    assert _visible(database, workspaces["reader"], result["global_document_id"]) == [
        (f"retro.md chunk {i}", i) for i in range(3)]


def test_the_copied_chunks_keep_their_embeddings(
    database: Any, workspaces: dict[str, str], admin: str
) -> None:
    source = _document(database, workspaces["a"], "retro.md")
    [result] = database.contributions.contribute(workspaces["a"], [source], admin)
    with database.get_connection() as conn:
        rows = conn.execute(
            "SELECT document_id, chunk_index, embedding::text FROM document_chunks"
            " WHERE document_id = ANY(%s) ORDER BY chunk_index, document_id",
            ([source, result["global_document_id"]],),
        ).fetchall()
    by_index: dict[int, set[str]] = {}
    for _, index, embedding in rows:
        by_index.setdefault(index, set()).add(embedding)
    assert len(rows) == 4
    assert all(len(embeddings) == 1 for embeddings in by_index.values())


def test_the_source_document_stays_in_its_workspace(
    database: Any, workspaces: dict[str, str], admin: str
) -> None:
    source = _document(database, workspaces["a"], "retro.md")
    database.contributions.contribute(workspaces["a"], [source], admin)
    names = [d["filename"] for d in database.documents.list_all(scope=workspaces["a"])]
    assert names == ["retro.md"]


def test_recontributing_updates_in_place_and_retires_the_old_chunks(
    database: Any, workspaces: dict[str, str], admin: str
) -> None:
    source = _document(database, workspaces["a"], "retro.md", chunks=2)
    [first] = database.contributions.contribute(workspaces["a"], [source], admin)
    database.documents.insert_chunks([(source, "retro.md chunk 2", 2, _vector(99))])
    [second] = database.contributions.contribute(workspaces["a"], [source], admin)

    assert second["global_document_id"] == first["global_document_id"]
    assert (second["updated"], second["chunks"]) == (True, 3)
    assert _visible(database, workspaces["reader"], first["global_document_id"]) == [
        (f"retro.md chunk {i}", i) for i in range(3)]


def test_two_projects_can_both_contribute_the_same_filename(
    database: Any, workspaces: dict[str, str], admin: str
) -> None:
    [from_a] = database.contributions.contribute(
        workspaces["a"], [_document(database, workspaces["a"], "retro.md")], admin)
    [from_b] = database.contributions.contribute(
        workspaces["b"], [_document(database, workspaces["b"], "retro.md")], admin)

    assert from_a["global_document_id"] != from_b["global_document_id"]
    assert (from_a["updated"], from_b["updated"]) == (False, False)


def test_purging_both_source_projects_cannot_collide_their_contributions(
    database: Any, workspaces: dict[str, str], admin: str
) -> None:
    """What `ON DELETE SET NULL` does at purge; a unique index treats NULLs as distinct."""
    ids = [
        database.contributions.contribute(
            ws, [_document(database, ws, "retro.md")], admin)[0]["global_document_id"]
        for ws in (workspaces["a"], workspaces["b"])
    ]
    with database.get_connection() as conn:
        cursor = conn.execute(
            "UPDATE documents SET source_project_id = NULL WHERE id = ANY(%s)", (ids,))
        updated = cursor.rowcount
        conn.rollback()
    assert updated == 2


def test_a_document_of_another_workspace_refuses_the_whole_contribution(
    database: Any, workspaces: dict[str, str], admin: str
) -> None:
    own = _document(database, workspaces["a"], "retro.md")
    foreign = _document(database, workspaces["b"], "secret.md")

    assert database.contributions.contribute(workspaces["a"], [own, foreign], admin) is None
    assert [d["filename"] for d in database.contributions.list_all()
            if d["source_project_id"] in (workspaces["a"], workspaces["b"])] == []


def test_archiving_takes_a_contribution_out_of_what_workspaces_read(
    database: Any, workspaces: dict[str, str], admin: str
) -> None:
    source = _document(database, workspaces["a"], "retro.md")
    [result] = database.contributions.contribute(workspaces["a"], [source], admin)

    assert database.contributions.archive(workspaces["a"], admin) == 1
    assert _visible(database, workspaces["reader"], result["global_document_id"]) == []
    workspace, _, _, archived_at = _owner_row(database, result["global_document_id"])
    assert (workspace, archived_at is not None) == (None, True)


def test_archiving_one_project_leaves_another_projects_contribution(
    database: Any, workspaces: dict[str, str], admin: str
) -> None:
    database.contributions.contribute(
        workspaces["a"], [_document(database, workspaces["a"], "retro.md")], admin)
    [from_b] = database.contributions.contribute(
        workspaces["b"], [_document(database, workspaces["b"], "retro.md")], admin)

    database.contributions.archive(workspaces["a"], admin)
    assert len(_visible(database, workspaces["reader"], from_b["global_document_id"])) == 2


def test_a_file_can_be_contributed_again_after_it_was_archived(
    database: Any, workspaces: dict[str, str], admin: str
) -> None:
    source = _document(database, workspaces["a"], "retro.md")
    [first] = database.contributions.contribute(workspaces["a"], [source], admin)
    database.contributions.archive(workspaces["a"], admin)
    [again] = database.contributions.contribute(workspaces["a"], [source], admin)

    assert again["updated"] is False
    assert again["global_document_id"] != first["global_document_id"]


def test_the_listing_names_the_source_project_and_keeps_archived_ones(
    database: Any, workspaces: dict[str, str], admin: str
) -> None:
    source = _document(database, workspaces["a"], "retro.md")
    [result] = database.contributions.contribute(workspaces["a"], [source], admin)
    database.contributions.archive(workspaces["a"], admin)

    [row] = [d for d in database.contributions.list_all() if d["id"] == result["global_document_id"]]
    assert row["source_project_id"] == workspaces["a"]
    assert row["source_project_name"] == database.workspaces.get(workspaces["a"])["name"]
    assert row["chunk_count"] == 2
    assert row["archived_at"] is not None


def test_the_workspace_list_tags_what_it_shares_until_it_is_withdrawn(
    database: Any, workspaces: dict[str, str], admin: str
) -> None:
    """Read through the workspace's own scope, as the Documents page does: only 0019's
    read policy lets that transaction see the global row the tag is computed from."""
    shared = _document(database, workspaces["a"], "retro.md")
    _document(database, workspaces["a"], "draft.md")
    _document(database, workspaces["b"], "retro.md")
    database.contributions.contribute(workspaces["a"], [shared], admin)

    def tags(ws: str) -> dict[str, bool]:
        return {d["filename"]: d["shared_globally"] for d in database.documents.list_all(scope=ws)}

    assert tags(workspaces["a"]) == {"retro.md": True, "draft.md": False}
    assert tags(workspaces["b"]) == {"retro.md": False}
    database.contributions.archive(workspaces["a"], admin)
    assert tags(workspaces["a"]) == {"retro.md": False, "draft.md": False}
