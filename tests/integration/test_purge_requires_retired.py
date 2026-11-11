"""R-9 (QP-9 review) against Postgres — a purge destroys only what was retired first.

Each single-object purge checked its references and nothing else, so a live document,
conversation, workspace, connector or user could be hard-deleted in one call, skipping
the reversible step Clark-Wilson puts before it. Now the purge locks the row and refuses
unless it is retired: a live row is a 409 and survives, a missing one is a 404, and a
retired one with nothing citing it is still destroyed.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.services.connectors import ConnectorsService
from src.services.conversations import ConversationsService
from src.services.documents import DocumentsService
from src.services.errors import ServiceError
from src.services.users import UsersService
from src.services.workspaces import WorkspacesService
from src.utils.scope import ALL_WORKSPACES

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
    ws = database.workspaces.create(f"r9-{uuid.uuid4().hex[:8]}", owner_id=None)
    yield ws
    database.workspaces.retire(ws)


def _tag() -> str:
    return uuid.uuid4().hex[:8]


KINDS = {
    "document": SimpleNamespace(
        table="documents",
        create=lambda db, ws: db.documents.insert(f"r9-{_tag()}.txt", "x", workspace_id=ws, scope=ws),
        retire=lambda db, row, ws: db.documents.retire(row, scope=ws),
        purge=lambda db, row: DocumentsService(db).purge(row),
    ),
    "conversation": SimpleNamespace(
        table="conversations",
        create=lambda db, ws: db.conversations.create("r9", workspace_id=ws),
        retire=lambda db, row, ws: db.conversations.retire(row, scope=ws),
        purge=lambda db, row: ConversationsService(db).purge(row),
    ),
    "connector": SimpleNamespace(
        table="connectors",
        create=lambda db, ws: db.connectors.create("webhook", f"r9-{_tag()}", {}, workspace_id=ws),
        retire=lambda db, row, ws: db.connectors.retire(row, scope=ws),
        purge=lambda db, row: ConnectorsService(db, MagicMock()).purge(row),
    ),
    "workspace": SimpleNamespace(
        table="workspaces",
        create=lambda db, ws: db.workspaces.create(f"r9-inner-{_tag()}", owner_id=None),
        retire=lambda db, row, ws: db.workspaces.retire(row),
        purge=lambda db, row: WorkspacesService(db).purge(row),
    ),
    "user": SimpleNamespace(
        table="users",
        create=lambda db, ws: db.users.create(f"r9-{_tag()}", "x", role="user"),
        retire=lambda db, row, ws: db.users.retire(row),
        purge=lambda db, row: UsersService(db).purge_user(row),
    ),
}
MISSING = {"documents": 2_000_000_000, "conversations": str(uuid.uuid4()), "connectors": str(uuid.uuid4()),
           "workspaces": str(uuid.uuid4()), "users": str(uuid.uuid4())}


def _exists(database: Any, table: str, row: Any) -> bool:
    with database.get_connection(scope=ALL_WORKSPACES) as conn:
        found = conn.execute(f"SELECT 1 FROM {table} WHERE id = %s", (row,)).fetchone()  # noqa: S608 — table is a literal from KINDS
    return found is not None


@pytest.mark.parametrize("kind", KINDS)
def test_a_live_row_is_refused_and_survives(database, workspace, kind):
    k = KINDS[kind]
    row = k.create(database, workspace)
    with pytest.raises(ServiceError) as refused:
        k.purge(database, row)
    assert (refused.value.status_code, _exists(database, k.table, row)) == (409, True)


@pytest.mark.parametrize("kind", KINDS)
def test_a_retired_row_is_purged(database, workspace, kind):
    """The permitted case: Retire, then Destroy."""
    k = KINDS[kind]
    row = k.create(database, workspace)
    k.retire(database, row, workspace)
    assert (k.purge(database, row), _exists(database, k.table, row)) == (True, False)


@pytest.mark.parametrize("kind", KINDS)
def test_a_missing_row_is_not_found(database, kind):
    k = KINDS[kind]
    with pytest.raises(ServiceError) as refused:
        k.purge(database, MISSING[k.table])
    assert refused.value.status_code == 404
