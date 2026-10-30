"""R-3 (QP-9 review) — a message is written only into a live conversation in the caller's scope.

`save_message` inserted into any conversation id on an all-workspaces connection. This runs
the scoped statement against Postgres, where the scoped transaction also runs under
row-level security: the caller's own conversation takes the message, another workspace's
and a retired one take nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from types import SimpleNamespace

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.db]


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


@pytest.fixture
def world(database) -> Iterator[SimpleNamespace]:
    tag = uuid.uuid4().hex[:8]
    a = database.workspaces.create(f"r3-a-{tag}", owner_id=None)
    b = database.workspaces.create(f"r3-b-{tag}", owner_id=None)
    own, _ = database.conversations.create_with_message("own", "user", "hi", workspace_id=a)
    foreign, _ = database.conversations.create_with_message("foreign", "user", "hi", workspace_id=b)
    retired, _ = database.conversations.create_with_message("retired", "user", "hi", workspace_id=a)
    database.conversations.retire(retired, None, scope=a)
    yield SimpleNamespace(a=a, b=b, own=own, foreign=foreign, retired=retired)
    database.workspaces.retire(a)
    database.workspaces.retire(b)


def _count(database, conversation_id: str, workspace: str) -> int:
    return len(database.conversations.messages(conversation_id, scope=workspace) or [])


def test_a_message_reaches_the_callers_own_conversation(database, world):
    # The permitted case: without it the refusals below would pass on a save that never writes.
    database.conversations.save_message(world.own, "user", "next", scope=world.a)
    assert _count(database, world.own, world.a) == 2


def test_another_workspaces_conversation_takes_no_message(database, world):
    assert database.conversations.save_message(world.foreign, "user", "planted", scope=world.a) is None


def test_another_workspaces_conversation_is_left_as_it_was(database, world):
    database.conversations.save_message(world.foreign, "user", "planted", scope=world.a)
    assert _count(database, world.foreign, world.b) == 1


def test_a_retired_conversation_takes_no_message(database, world):
    assert database.conversations.save_message(world.retired, "user", "late", scope=world.a) is None
