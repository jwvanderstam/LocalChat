"""Which scope each repository method opens its connection with (QP-5 step 2, ADR-5).

Since migration 0023 a connection that names neither a workspace nor ALL_WORKSPACES reads
nothing from the ten row-level-security tables. The ratchet in test_layering_ratchets.py
proves every method names *a* scope; these pin *which*, for the methods no other test
drives: the installation-wide paths carry the flag, and a workspace's own keys are read
and revoked in that workspace.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.db.connectors import ConnectorsRepository
from src.db.documents import DocumentsRepository
from src.db.feedback import FeedbackRepository
from src.db.workspace_keys import KEY_PREFIX, WorkspaceKeysRepository
from src.utils.scope import ALL_WORKSPACES

pytestmark = pytest.mark.unit

WS = "11111111-1111-1111-1111-111111111111"


class _Host:
    """A connection that records the scope each transaction was opened with."""

    def __init__(self, fetchone: Any = None, fetchall: list[Any] | None = None, rowcount: int = 1) -> None:
        self.is_connected = True
        self.scopes: list[Any] = []
        self.cur = MagicMock()
        self.cur.fetchone.return_value = fetchone
        self.cur.fetchall.return_value = fetchall or []
        self.cur.rowcount = rowcount
        self.cur.description = []
        self.cur.__enter__.return_value = self.cur
        self.conn = MagicMock()
        self.conn.cursor.return_value = self.cur
        self.conn.execute.return_value = self.cur

    @contextmanager
    def get_connection(self, *, scope: Any = None) -> Iterator[MagicMock]:
        self.scopes.append(scope)
        yield self.conn


class TestWorkspaceKeys:
    def test_resolving_a_key_is_installation_wide(self):
        """It runs before any workspace is authorised: the key is what names one."""
        host = _Host(fetchall=[])
        assert WorkspaceKeysRepository(host).resolve(f"{KEY_PREFIX}abcdefgh-secret") is None
        assert host.scopes == [ALL_WORKSPACES]

    def test_recording_last_use_is_installation_wide(self):
        host = _Host()
        WorkspaceKeysRepository(host)._touch("key-1")
        assert host.scopes == [ALL_WORKSPACES]

    def test_listing_reads_only_the_workspace(self):
        host = _Host(fetchall=[])
        assert WorkspaceKeysRepository(host).list_for_workspace(WS) == []
        assert host.scopes == [WS]

    def test_revoking_writes_only_in_the_workspace(self):
        host = _Host(rowcount=1)
        assert WorkspaceKeysRepository(host).revoke("key-1", WS, revoked_by="u") is True
        assert host.scopes == [WS]


class TestFeedbackAggregatesAreInstallationWide:
    """Admin statistics and the fine-tuning export read every workspace on purpose."""

    def test_stats(self):
        host = _Host(fetchone=(0, 0, 0), fetchall=[])
        FeedbackRepository(host).stats(days=7)
        assert set(host.scopes) == {ALL_WORKSPACES}

    def test_stale_chunks(self):
        host = _Host(fetchall=[])
        assert FeedbackRepository(host).stale_chunks() == []
        assert host.scopes == [ALL_WORKSPACES]

    def test_trend(self):
        host = _Host(fetchall=[])
        assert FeedbackRepository(host).trend(days=7) == []
        assert host.scopes == [ALL_WORKSPACES]

    def test_export_pairs(self):
        host = _Host(fetchall=[])
        assert FeedbackRepository(host).export_pairs(days=7) == []
        assert host.scopes == [ALL_WORKSPACES]


class TestConnectorWorkerPathsAreInstallationWide:
    """The sync worker and an admin's purge act for no request, so they carry the flag."""

    def test_purge(self):
        host = _Host(fetchone=None, rowcount=1)
        ConnectorsRepository(host).purge("c-1")
        assert host.scopes == [ALL_WORKSPACES]

    def test_interval(self):
        host = _Host(fetchone=(900,))
        assert ConnectorsRepository(host).interval("c-1") == 900
        assert host.scopes == [ALL_WORKSPACES]

    def test_set_sync_status(self):
        host = _Host()
        ConnectorsRepository(host).set_sync_status("c-1", error=None)
        assert host.scopes == [ALL_WORKSPACES]


class TestAConnectorRetiresOnlyInItsWorkspace:
    def test_retiring_a_synced_document_by_filename(self):
        # R-2: this ran on ALL_WORKSPACES and retired the filename everywhere.
        host = _Host(rowcount=1)
        assert ConnectorsRepository(host).retire_document_by_filename(
            "a.pdf", source_id="c-1", deleted_by=None, scope=WS
        ) is True
        assert host.scopes == [WS]


class TestDocumentChecksAreInstallationWide:
    def test_the_local_only_check(self):
        host = _Host(fetchone=None)
        assert DocumentsRepository(host).any_local_only_sources(["a.pdf"]) is False
        assert host.scopes == [ALL_WORKSPACES]

    def test_marking_a_reingest(self):
        host = _Host()
        DocumentsRepository(host).mark_ingested(7)
        assert host.scopes == [ALL_WORKSPACES]
