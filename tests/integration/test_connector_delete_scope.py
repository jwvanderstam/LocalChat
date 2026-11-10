"""R-2 (QP-9 review) — a connector's delete event retires only what that connector ingested.

`retire_document_by_filename` matched on the filename alone, on an all-workspaces
connection. Any user could create a workspace, add a webhook connector, post a `deleted`
event naming a filename, and retire that file in every workspace and in the global tier.
This drives the real `SyncWorker._handle_delete` against Postgres with that attacker's
connector next to the victim's.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.connectors.base import DocumentSource
from src.connectors.worker import SyncWorker

pytestmark = [pytest.mark.integration, pytest.mark.db]

FILENAME = "q3-report.pdf"


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


def _live(db, doc_id: int, workspace: str) -> bool:
    return any(d["id"] == doc_id for d in db.documents.list_all(scope=workspace))


@pytest.fixture
def world(database) -> Iterator[SimpleNamespace]:
    """The victim's connector ingested FILENAME into A; B uploaded its own FILENAME."""
    tag = uuid.uuid4().hex[:8]
    victim_ws = database.workspaces.create(f"r2-victim-{tag}", owner_id=None)
    other_ws = database.workspaces.create(f"r2-other-{tag}", owner_id=None)
    attacker_ws = database.workspaces.create(f"r2-attacker-{tag}", owner_id=None)
    victim_conn = f"victim-conn-{tag}"
    synced = database.documents.insert(
        FILENAME, "synced", workspace_id=victim_ws, source_id=victim_conn, scope=victim_ws
    )
    uploaded = database.documents.insert(
        FILENAME, "uploaded", workspace_id=other_ws, scope=other_ws
    )
    yield SimpleNamespace(
        victim_ws=victim_ws, other_ws=other_ws, attacker_ws=attacker_ws,
        victim_conn=victim_conn, synced=synced, uploaded=uploaded, tag=tag,
    )
    for ws in (victim_ws, other_ws, attacker_ws):
        database.workspaces.retire(ws)


def _delete_event(database, connector_id: str, workspace: str | None) -> None:
    worker = SyncWorker(MagicMock(), database, MagicMock())
    connector = SimpleNamespace(connector_id=connector_id, workspace_id=workspace, owner_user_id=None)
    worker._handle_delete(connector, DocumentSource(source_id="x", filename=FILENAME))


def test_an_attackers_connector_retires_nothing_outside_its_own_workspace(database, world):
    _delete_event(database, f"attacker-conn-{world.tag}", world.attacker_ws)
    assert (_live(database, world.synced, world.victim_ws), _live(database, world.uploaded, world.other_ws)) == (True, True)


def test_a_connector_retires_the_document_it_ingested(database, world):
    # The permitted case: without it, the refusal above would pass on a delete that never works.
    _delete_event(database, world.victim_conn, world.victim_ws)
    assert _live(database, world.synced, world.victim_ws) is False


def test_a_connector_leaves_another_workspaces_document_of_the_same_name(database, world):
    _delete_event(database, world.victim_conn, world.victim_ws)
    assert _live(database, world.uploaded, world.other_ws) is True


def test_a_connector_naming_another_workspaces_connector_id_retires_nothing_there(database, world):
    # An id is not a credential: the delete runs in the caller's workspace scope.
    _delete_event(database, world.victim_conn, world.attacker_ws)
    assert _live(database, world.synced, world.victim_ws) is True
