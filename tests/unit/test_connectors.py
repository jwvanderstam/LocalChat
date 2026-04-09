"""
Unit tests for the connectors package (Feature 4.3).

Covers:
- LocalFolderConnector: scan, poll (added/modified/deleted), fetch, validate_config
- WebhookConnector: push_event validation, poll drains queue, fetch via URL
- ConnectorRegistry: add, get, remove, available_types, unknown type raises
- SyncWorker: _is_due, _handle_delete, _handle_event (added/modified), oversized file skipped
"""

import os
import tempfile
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from src.connectors.base import DocumentEvent, DocumentSource, EventType
from src.connectors.local_folder import LocalFolderConnector
from src.connectors.registry import ConnectorRegistry
from src.connectors.webhook import WebhookConnector
from src.connectors.worker import SyncWorker


# ---------------------------------------------------------------------------
# LocalFolderConnector
# ---------------------------------------------------------------------------

class TestLocalFolderConnector:

    def _make(self, path, recursive=True, extensions=None):
        cfg = {"path": path, "recursive": recursive}
        if extensions:
            cfg["extensions"] = extensions
        return LocalFolderConnector(cfg)

    def test_connector_type(self, tmp_path):
        c = self._make(str(tmp_path))
        assert c.connector_type == "local_folder"

    def test_display_name_contains_path(self, tmp_path):
        c = self._make(str(tmp_path))
        assert str(tmp_path) in c.display_name

    def test_validate_config_missing_path(self):
        c = LocalFolderConnector({})
        errors = c.validate_config()
        assert any("path" in e for e in errors)

    def test_validate_config_nonexistent_dir(self, tmp_path):
        c = LocalFolderConnector({"path": str(tmp_path / "nope")})
        errors = c.validate_config()
        assert errors

    def test_validate_config_valid(self, tmp_path):
        c = self._make(str(tmp_path))
        assert c.validate_config() == []

    def test_list_sources_empty_dir(self, tmp_path):
        c = self._make(str(tmp_path))
        assert c.list_sources() == []

    def test_list_sources_finds_supported_file(self, tmp_path):
        f = tmp_path / "doc.txt"
        f.write_text("hello")
        with patch("src.connectors.local_folder.app_config") as mock_cfg:
            mock_cfg.SUPPORTED_EXTENSIONS = [".txt"]
            c = self._make(str(tmp_path))
            sources = c.list_sources()
        assert len(sources) == 1
        assert sources[0].filename == "doc.txt"

    def test_poll_detects_added_file(self, tmp_path):
        with patch("src.connectors.local_folder.app_config") as mock_cfg:
            mock_cfg.SUPPORTED_EXTENSIONS = [".txt"]
            c = self._make(str(tmp_path))
            # Initial poll — no files yet
            events = c.poll()
            assert events == []
            # Add a file
            (tmp_path / "new.txt").write_text("content")
            events = c.poll()
        assert len(events) == 1
        assert events[0].event_type == EventType.ADDED
        assert events[0].source.filename == "new.txt"

    def test_poll_detects_modified_file(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("v1")
        with patch("src.connectors.local_folder.app_config") as mock_cfg:
            mock_cfg.SUPPORTED_EXTENSIONS = [".txt"]
            c = self._make(str(tmp_path))
            c.poll()  # establish baseline
            # Modify mtime
            os.utime(f, (time.time() + 1, time.time() + 1))
            events = c.poll()
        assert any(e.event_type == EventType.MODIFIED for e in events)

    def test_poll_detects_deleted_file(self, tmp_path):
        f = tmp_path / "gone.txt"
        f.write_text("data")
        with patch("src.connectors.local_folder.app_config") as mock_cfg:
            mock_cfg.SUPPORTED_EXTENSIONS = [".txt"]
            c = self._make(str(tmp_path))
            c.poll()  # establish baseline
            f.unlink()
            events = c.poll()
        assert any(e.event_type == EventType.DELETED for e in events)

    def test_poll_no_changes_returns_empty(self, tmp_path):
        (tmp_path / "stable.txt").write_text("data")
        with patch("src.connectors.local_folder.app_config") as mock_cfg:
            mock_cfg.SUPPORTED_EXTENSIONS = [".txt"]
            c = self._make(str(tmp_path))
            c.poll()
            events = c.poll()
        assert events == []

    def test_extension_filter(self, tmp_path):
        (tmp_path / "keep.txt").write_text("yes")
        (tmp_path / "skip.pdf").write_bytes(b"%PDF")
        c = self._make(str(tmp_path), extensions=[".txt"])
        sources = c.list_sources()
        filenames = [s.filename for s in sources]
        assert "keep.txt" in filenames
        assert "skip.pdf" not in filenames

    def test_fetch_returns_bytes(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_bytes(b"hello bytes")
        c = self._make(str(tmp_path))
        source = DocumentSource(source_id=str(f), filename="data.txt")
        assert c.fetch(source) == b"hello bytes"

    def test_non_recursive_does_not_descend(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.txt").write_text("deep")
        (tmp_path / "top.txt").write_text("top")
        with patch("src.connectors.local_folder.app_config") as mock_cfg:
            mock_cfg.SUPPORTED_EXTENSIONS = [".txt"]
            c = self._make(str(tmp_path), recursive=False)
            sources = c.list_sources()
        filenames = [s.filename for s in sources]
        assert "top.txt" in filenames
        assert "deep.txt" not in filenames


# ---------------------------------------------------------------------------
# WebhookConnector
# ---------------------------------------------------------------------------

class TestWebhookConnector:

    def _make(self, secret=None):
        cfg = {}
        if secret:
            cfg["secret"] = secret
        return WebhookConnector(cfg)

    def test_connector_type(self):
        assert self._make().connector_type == "webhook"

    def test_poll_empty(self):
        c = self._make()
        assert c.poll() == []

    def test_push_event_valid_added(self):
        c = self._make()
        errors = c.push_event({
            "event_type": "added",
            "source_id": "doc-123",
            "filename": "report.pdf",
            "fetch_url": "http://example.com/report.pdf",
        })
        assert errors == []
        events = c.poll()
        assert len(events) == 1
        assert events[0].event_type == EventType.ADDED
        assert events[0].source.filename == "report.pdf"

    def test_push_event_valid_deleted(self):
        c = self._make()
        errors = c.push_event({
            "event_type": "deleted",
            "source_id": "doc-456",
        })
        assert errors == []
        events = c.poll()
        assert events[0].event_type == EventType.DELETED

    def test_push_event_missing_source_id(self):
        c = self._make()
        errors = c.push_event({"event_type": "added", "fetch_url": "http://x.com"})
        assert any("source_id" in e for e in errors)

    def test_push_event_missing_fetch_url_for_added(self):
        c = self._make()
        errors = c.push_event({"event_type": "added", "source_id": "x"})
        assert any("fetch_url" in e for e in errors)

    def test_push_event_bad_event_type(self):
        c = self._make()
        errors = c.push_event({"event_type": "upsert", "source_id": "x"})
        assert errors

    def test_poll_drains_queue(self):
        c = self._make()
        for i in range(3):
            c.push_event({
                "event_type": "added",
                "source_id": f"doc-{i}",
                "fetch_url": "http://x.com",
            })
        events = c.poll()
        assert len(events) == 3
        assert c.poll() == []  # drained

    def test_fetch_calls_urlopen(self):
        c = self._make()
        source = DocumentSource(
            source_id="doc-1", filename="f.txt",
            metadata={"fetch_url": "http://example.com/f.txt"},
        )
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = b"content"
        with patch("urllib.request.urlopen", return_value=mock_resp):
            data = c.fetch(source)
        assert data == b"content"

    def test_fetch_raises_if_no_url(self):
        c = self._make()
        source = DocumentSource(source_id="x", filename="x.txt")
        with pytest.raises(ValueError, match="fetch_url"):
            c.fetch(source)

    def test_list_sources_returns_empty(self):
        assert self._make().list_sources() == []


# ---------------------------------------------------------------------------
# ConnectorRegistry
# ---------------------------------------------------------------------------

class TestConnectorRegistry:

    def test_available_types(self):
        reg = ConnectorRegistry()
        types = reg.available_types()
        assert "local_folder" in types
        assert "s3" in types
        assert "webhook" in types

    def test_get_class_known(self):
        reg = ConnectorRegistry()
        cls = reg.get_class("local_folder")
        assert cls is LocalFolderConnector

    def test_get_class_unknown(self):
        reg = ConnectorRegistry()
        assert reg.get_class("nonexistent") is None

    def test_add_and_get(self, tmp_path):
        reg = ConnectorRegistry()
        inst = reg.add("id-1", "local_folder", {"path": str(tmp_path)})
        assert inst is reg.get("id-1")
        assert inst.connector_id == "id-1"

    def test_add_unknown_type_raises(self):
        reg = ConnectorRegistry()
        with pytest.raises(ValueError, match="Unknown connector type"):
            reg.add("id-2", "ftp", {})

    def test_remove(self, tmp_path):
        reg = ConnectorRegistry()
        reg.add("id-3", "local_folder", {"path": str(tmp_path)})
        reg.remove("id-3")
        assert reg.get("id-3") is None

    def test_all_instances(self, tmp_path):
        reg = ConnectorRegistry()
        reg.add("a", "local_folder", {"path": str(tmp_path)})
        reg.add("b", "webhook", {})
        assert len(reg.all_instances()) == 2

    def test_load_from_db_skips_unknown_type(self):
        reg = ConnectorRegistry()
        mock_db = MagicMock()
        mock_db.is_connected = True
        mock_db.list_connectors.return_value = [
            {"id": "x", "connector_type": "ftp", "config": {}, "workspace_id": None},
        ]
        reg.load_from_db(mock_db)
        assert reg.get("x") is None

    def test_load_from_db_loads_known_type(self, tmp_path):
        reg = ConnectorRegistry()
        mock_db = MagicMock()
        mock_db.is_connected = True
        mock_db.list_connectors.return_value = [
            {
                "id": "folder-1",
                "connector_type": "local_folder",
                "config": {"path": str(tmp_path)},
                "workspace_id": None,
            },
        ]
        reg.load_from_db(mock_db)
        assert reg.get("folder-1") is not None


# ---------------------------------------------------------------------------
# SyncWorker
# ---------------------------------------------------------------------------

class TestSyncWorker:

    def _make_worker(self, registry=None, db=None, processor=None):
        return SyncWorker(
            registry or MagicMock(),
            db or MagicMock(),
            processor or MagicMock(),
        )

    def test_start_stop(self):
        w = self._make_worker()
        w.start()
        assert w._thread is not None and w._thread.is_alive()
        w.stop()
        assert not w._thread.is_alive()

    def test_start_is_idempotent(self):
        w = self._make_worker()
        w.start()
        t1 = w._thread
        w.start()
        assert w._thread is t1
        w.stop()

    def test_is_due_returns_true_initially(self):
        w = self._make_worker()
        connector = MagicMock()
        connector.connector_id = "c1"
        w._db.get_connector_interval.return_value = 900
        assert w._is_due(connector) is True

    def test_is_due_false_after_recent_run(self):
        w = self._make_worker()
        connector = MagicMock()
        connector.connector_id = "c1"
        w._db.get_connector_interval.return_value = 900
        w._next_run["c1"] = time.monotonic() + 900
        assert w._is_due(connector) is False

    def test_handle_delete_calls_db(self):
        mock_db = MagicMock()
        mock_db.delete_document_by_filename.return_value = True
        w = self._make_worker(db=mock_db)
        source = DocumentSource(source_id="/path/file.txt", filename="file.txt")
        w._handle_delete(MagicMock(), source)
        mock_db.delete_document_by_filename.assert_called_once_with("file.txt")

    def test_handle_event_added_calls_ingest(self, tmp_path):
        mock_processor = MagicMock()
        mock_processor.ingest_document.return_value = (True, "ok", 1)
        w = self._make_worker(processor=mock_processor)
        connector = MagicMock()
        connector.workspace_id = None
        connector.fetch.return_value = b"pdf content"
        source = DocumentSource(source_id="doc.pdf", filename="doc.pdf")
        event = DocumentEvent(EventType.ADDED, source)
        w._handle_event(connector, event, {"added": 0, "updated": 0, "deleted": 0})
        mock_processor.ingest_document.assert_called_once()

    def test_handle_event_oversized_file_skipped(self):
        mock_processor = MagicMock()
        w = self._make_worker(processor=mock_processor)
        connector = MagicMock()
        # Return more than _MAX_FILE_MB megabytes
        from src.connectors.worker import _MAX_FILE_MB
        connector.fetch.return_value = b"x" * (_MAX_FILE_MB * 1024 * 1024 + 1)
        source = DocumentSource(source_id="huge.pdf", filename="huge.pdf")
        event = DocumentEvent(EventType.ADDED, source)
        w._handle_event(connector, event, {"added": 0, "updated": 0, "deleted": 0})
        mock_processor.ingest_document.assert_not_called()

    def test_handle_event_fetch_failure_does_not_raise(self):
        mock_processor = MagicMock()
        w = self._make_worker(processor=mock_processor)
        connector = MagicMock()
        connector.fetch.side_effect = OSError("network error")
        source = DocumentSource(source_id="x.pdf", filename="x.pdf")
        event = DocumentEvent(EventType.ADDED, source)
        # Should not raise
        w._handle_event(connector, event, {"added": 0, "updated": 0, "deleted": 0})
        mock_processor.ingest_document.assert_not_called()
