"""The ``app`` fixture undoes a mock a test sets on one of the singleton's repositories.

``app.state.db`` is the process-wide ``src.db.db``. Since QP-4 a test mocks
``app.state.db.connectors.create``, which lands on the repository rather than on ``db``,
and the fixture used to restore ``db`` alone: a mock returning ``"conn-new"`` then reached
the over-the-wire integration suite, which asked Postgres for a connector whose id is not
a UUID (#481).

The two tests run in file order. The first leaves a mock behind on purpose; the second
fails if it is still there.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit

_LEFT_BEHIND = MagicMock(return_value="conn-new")


class TestTheAppFixtureRestoresRepositories:
    def test_a_test_mocks_a_repository_method_and_does_not_clean_up(self, app):
        app.state.db.connectors.create = _LEFT_BEHIND
        assert app.state.db.connectors.create is _LEFT_BEHIND

    def test_the_next_test_sees_the_real_method(self):
        from src.db import db

        assert db.connectors.create is not _LEFT_BEHIND
        assert db.connectors.create.__func__.__qualname__ == "ConnectorsRepository.create"
