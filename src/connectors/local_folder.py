"""
Local Folder Connector
======================

Watches a local directory tree for new, modified, and deleted documents.

Uses ``watchdog`` when available (inotify on Linux, FSEvents on macOS,
ReadDirectoryChangesW on Windows) and falls back to stat-based polling
when watchdog is not installed.

Config keys:
    path          (required) Absolute path to the folder to watch.
    recursive     (optional, default true) Watch sub-directories.
    extensions    (optional) List of extensions to watch, e.g. [".pdf", ".docx"].
                  Empty list / omitted = all supported extensions.
"""

from __future__ import annotations

import os
import time
from datetime import UTC
from pathlib import Path
from typing import Any

from .. import config as app_config
from ..utils.logging_config import get_logger
from .base import BaseConnector, DocumentEvent, DocumentSource, EventType

logger = get_logger(__name__)

# Snapshot: path → mtime used for polling fallback
_Snapshot = dict[str, float]


class LocalFolderConnector(BaseConnector):
    """Watches a local directory and emits events for changed files."""

    @property
    def connector_type(self) -> str:
        return "local_folder"

    @property
    def display_name(self) -> str:
        folder = self.config.get("path", "")
        return f"Local folder: {folder}"

    def validate_config(self) -> list[str]:
        errors: list[str] = []
        path = self.config.get("path", "").strip()
        if not path:
            errors.append("'path' is required")
        elif not os.path.isdir(path):
            errors.append(f"Directory does not exist: {path}")
        return errors

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _watched_extensions(self) -> set[str]:
        exts = self.config.get("extensions") or []
        if exts:
            return {e.lower() if e.startswith(".") else f".{e.lower()}" for e in exts}
        return set(app_config.SUPPORTED_EXTENSIONS)

    def _is_watched(self, path: str) -> bool:
        return Path(path).suffix.lower() in self._watched_extensions()

    def _build_source(self, file_path: str) -> DocumentSource:
        stat = os.stat(file_path)
        return DocumentSource(
            source_id=file_path,
            filename=os.path.basename(file_path),
            last_modified=_mtime_to_dt(stat.st_mtime),
            size_bytes=stat.st_size,
            metadata={"full_path": file_path},
        )

    def _scan(self) -> _Snapshot:
        """Scan the watched folder and return {path: mtime}."""
        root = self.config.get("path", "")
        recursive = self.config.get("recursive", True)
        try:
            if recursive:
                return self._scan_recursive(root)
            return self._scan_flat(root)
        except OSError as e:
            logger.warning(f"[LocalFolder] Scan error: {e}")
            return {}

    def _scan_recursive(self, root: str) -> _Snapshot:
        snapshot: _Snapshot = {}
        for dirpath, _dirs, filenames in os.walk(root):
            for fname in filenames:
                full = os.path.join(dirpath, fname)
                if self._is_watched(full):
                    snapshot[full] = os.stat(full).st_mtime
        return snapshot

    def _scan_flat(self, root: str) -> _Snapshot:
        snapshot: _Snapshot = {}
        for entry in os.scandir(root):
            if entry.is_file() and self._is_watched(entry.path):
                snapshot[entry.path] = entry.stat().st_mtime
        return snapshot

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    def list_sources(self) -> list[DocumentSource]:
        return [self._build_source(p) for p in self._scan()]

    def poll(self) -> list[DocumentEvent]:
        """Diff current snapshot against the stored one; return change events."""
        previous: _Snapshot = getattr(self, "_snapshot", {})
        current = self._scan()
        self._snapshot: _Snapshot = current

        events: list[DocumentEvent] = []

        for path, mtime in current.items():
            if path not in previous:
                events.append(DocumentEvent(EventType.ADDED, self._build_source(path)))
            elif mtime != previous[path]:
                events.append(DocumentEvent(EventType.MODIFIED, self._build_source(path)))

        for path in previous:
            if path not in current:
                events.append(DocumentEvent(
                    EventType.DELETED,
                    DocumentSource(source_id=path, filename=os.path.basename(path)),
                ))

        if events:
            logger.info(f"[LocalFolder] {len(events)} event(s) from {self.config.get('path')}")
        return events

    def fetch(self, source: DocumentSource) -> bytes:
        with open(source.source_id, "rb") as fh:
            return fh.read()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mtime_to_dt(mtime: float):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(mtime, tz=UTC)
