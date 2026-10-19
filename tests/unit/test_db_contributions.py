"""GKB-2 — ContributionsMixin in the fast suite, against a scripted cursor.

`tests/integration/test_gkb_contribution.py` proves the SQL against Postgres. These pin
what the Python around it decides: a refused contribution writes and commits nothing, a
multi-document contribution reports each document from its own statements, and every
write names the workspace it acts for, since the connection is unscoped and nothing else
will.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.db.connection import DatabaseUnavailableError
from src.db.contributions import ContributionsMixin

pytestmark = pytest.mark.unit

WS = "11111111-1111-1111-1111-111111111111"
ADMIN = "44444444-4444-4444-4444-444444444444"


class _Cursor:
    """Answers each execute from a script of ``(fetchone, fetchall, rowcount)`` steps."""

    def __init__(self, steps: list[tuple[Any, Any, int]]) -> None:
        self.steps = steps
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self._current: tuple[Any, Any, int] = (None, [], 0)

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.executed.append((" ".join(sql.split()), params))
        self._current = self.steps[len(self.executed) - 1]

    def fetchone(self) -> Any:
        return self._current[0]

    def fetchall(self) -> Any:
        return self._current[1]

    @property
    def rowcount(self) -> int:
        return self._current[2]


def _mixin(steps: list[tuple[Any, Any, int]], connected: bool = True):
    cursor = _Cursor(steps)
    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    mixin = ContributionsMixin()
    mixin.is_connected = connected
    mixin.get_connection = MagicMock(return_value=conn)
    return mixin, conn, cursor


class TestContributeDocuments:
    def test_a_document_outside_the_workspace_writes_and_commits_nothing(self):
        mixin, conn, cursor = _mixin([(None, [(7,)], 1)])

        assert mixin.contribute_documents(WS, [7, 8], ADMIN) is None
        assert [params for _, params in cursor.executed] == [([7, 8], WS)]
        conn.commit.assert_not_called()

    def test_each_document_is_reported_from_its_own_statements(self):
        mixin, conn, cursor = _mixin([
            (None, [(7,), (9,)], 2),
            ((70, "retro.md", True), [], 1), (None, [], 0), (None, [], 3),
            ((90, "plan.md", False), [], 1), (None, [], 4), (None, [], 5),
        ])

        result = mixin.contribute_documents(WS, [9, 7, 7], ADMIN)

        assert result == [
            {"document_id": 7, "global_document_id": 70, "filename": "retro.md",
             "chunks": 3, "updated": False},
            {"document_id": 9, "global_document_id": 90, "filename": "plan.md",
             "chunks": 5, "updated": True},
        ]
        conn.commit.assert_called_once_with()

    def test_the_copy_reads_from_the_named_workspace_and_records_the_contributor(self):
        mixin, _, cursor = _mixin([
            (None, [(7,)], 1),
            ((70, "retro.md", True), [], 1), (None, [], 0), (None, [], 2),
        ])
        mixin.contribute_documents(WS, [7], ADMIN)

        (check_sql, check), (upsert_sql, upsert), (_, retire), (_, copy) = cursor.executed
        assert "workspace_id = %s" in check_sql and check == ([7], WS)
        assert "ON CONFLICT (filename, source_project_id)" in upsert_sql
        assert upsert == (ADMIN, 7)
        assert retire == (70,)
        assert copy == (70, 7)

    def test_refuses_when_the_database_is_not_connected(self):
        mixin, _, _ = _mixin([], connected=False)
        with pytest.raises(DatabaseUnavailableError):
            mixin.contribute_documents(WS, [7], ADMIN)


class TestArchiveContributions:
    def test_archives_only_the_named_workspaces_contributions_and_counts_them(self):
        mixin, conn, cursor = _mixin([(None, [], 4)])

        assert mixin.archive_contributions(WS, ADMIN) == 4
        [(sql, params)] = cursor.executed
        assert "WHERE source_project_id = %s" in sql
        assert params == (ADMIN, WS)
        conn.commit.assert_called_once_with()

    def test_refuses_when_the_database_is_not_connected(self):
        mixin, _, _ = _mixin([], connected=False)
        with pytest.raises(DatabaseUnavailableError):
            mixin.archive_contributions(WS, ADMIN)


class TestListContributions:
    def test_rows_become_json_ready_dicts(self):
        at = datetime(2026, 10, 19, 9, 30, tzinfo=UTC)
        mixin, _, _ = _mixin([(None, [
            (70, "retro.md", WS, "Project A", at, "admin", None, 3),
            (71, "old.md", None, None, at, None, at, 0),
        ], 2)])

        assert mixin.list_contributions() == [
            {"id": 70, "filename": "retro.md", "source_project_id": WS,
             "source_project_name": "Project A", "contributed_at": at.isoformat(),
             "contributed_by": "admin", "archived_at": None, "chunk_count": 3},
            {"id": 71, "filename": "old.md", "source_project_id": None,
             "source_project_name": None, "contributed_at": at.isoformat(),
             "contributed_by": None, "archived_at": at.isoformat(), "chunk_count": 0},
        ]

    def test_refuses_when_the_database_is_not_connected(self):
        mixin, _, _ = _mixin([], connected=False)
        with pytest.raises(DatabaseUnavailableError):
            mixin.list_contributions()
