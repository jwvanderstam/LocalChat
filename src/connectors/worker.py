"""
Sync Worker
===========

Background thread that drives the connector poll / ingest loop.

Lifecycle:
    SyncWorker.start()   — launch the daemon thread (idempotent)
    SyncWorker.stop()    — signal the thread to exit gracefully

Per-connector sync cycle:
    1. Call connector.poll() to get DocumentEvents since last run.
    2. For ADDED / MODIFIED: fetch bytes → write to tmp file → call
       doc_processor.ingest_document() (re-uses the same pipeline as
       manual uploads including chunking, embedding, and de-duplication).
    3. For DELETED: call db.delete_document_by_filename().
    4. Update connectors.last_sync_at and last_error via db.
    5. Append a row to connector_sync_log.

A connector's configured ``sync_interval`` (seconds) is respected.
The worker sleeps in short bursts so stop() is responsive.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
from typing import TYPE_CHECKING, Any

from ..utils.logging_config import get_logger
from .base import EventType

if TYPE_CHECKING:
    from ..rag.processor import DocumentProcessor

logger = get_logger(__name__)

_TICK = 5          # seconds between "is it time for this connector?" checks
_MAX_FILE_MB = 50  # reject fetched files larger than this


class SyncWorker:
    """
    Daemon thread that polls all registered connectors and ingests changes.

    Usage::

        worker = SyncWorker(connector_registry, db, doc_processor)
        worker.start()
        ...
        worker.stop()
    """

    def __init__(self, registry, db, doc_processor: DocumentProcessor) -> None:
        self._registry = registry
        self._db = db
        self._doc_processor = doc_processor
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._next_run: dict[str, float] = {}   # connector_id → epoch seconds

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="connector-sync-worker", daemon=True
        )
        self._thread.start()
        logger.info("[SyncWorker] Started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=15)
        logger.info("[SyncWorker] Stopped")

    # ------------------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            for connector in self._registry.all_instances():
                if self._stop_event.is_set():
                    break
                if self._is_due(connector):
                    self._sync_one(connector)
            self._stop_event.wait(timeout=_TICK)

    def _is_due(self, connector) -> bool:
        now = time.monotonic()
        return now >= self._next_run.get(connector.connector_id, 0)

    def _sync_one(self, connector) -> None:
        connector_id = connector.connector_id
        interval = float(self._db.get_connector_interval(connector_id) or 900)
        self._next_run[connector_id] = time.monotonic() + interval

        started = time.time()
        counts = {"added": 0, "updated": 0, "deleted": 0}
        error_msg: str | None = None

        log_id = self._db.start_sync_log(connector_id)
        try:
            events = connector.poll()
            for event in events:
                self._handle_event(connector, event, counts)
        except Exception as exc:
            error_msg = str(exc)
            logger.error(f"[SyncWorker] Connector {connector_id} error: {exc}", exc_info=True)
        finally:
            self._db.finish_sync_log(log_id, counts, error_msg)
            self._db.update_connector_sync_status(connector_id, error=error_msg)
            elapsed = time.time() - started
            logger.info(
                f"[SyncWorker] {connector.display_name}: "
                f"+{counts['added']} ~{counts['updated']} -{counts['deleted']} "
                f"in {elapsed:.1f}s"
                + (f" [error: {error_msg}]" if error_msg else "")
            )

    def _handle_event(self, connector, event, counts: dict[str, int]) -> None:
        if event.event_type == EventType.DELETED:
            self._handle_delete(event.source)
            counts["deleted"] += 1
            return

        # ADDED or MODIFIED — fetch and ingest
        try:
            data = connector.fetch(event.source)
        except Exception as exc:
            logger.warning(
                f"[SyncWorker] Could not fetch {event.source.filename}: {exc}"
            )
            return

        if len(data) > _MAX_FILE_MB * 1024 * 1024:
            logger.warning(
                f"[SyncWorker] Skipping {event.source.filename}: "
                f"size {len(data) // 1024 // 1024}MB exceeds {_MAX_FILE_MB}MB limit"
            )
            return

        suffix = os.path.splitext(event.source.filename)[1] or ".bin"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        try:
            success, message, _doc_id = self._doc_processor.ingest_document(
                tmp_path,
                workspace_id=connector.workspace_id,
            )
            if success:
                counts["added" if event.event_type == EventType.ADDED else "updated"] += 1
                logger.debug(f"[SyncWorker] Ingested {event.source.filename}: {message}")
            else:
                logger.warning(f"[SyncWorker] Ingest failed for {event.source.filename}: {message}")
        except Exception as exc:
            logger.error(f"[SyncWorker] Ingest error for {event.source.filename}: {exc}")
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def _handle_delete(self, source) -> None:
        try:
            deleted = self._db.delete_document_by_filename(source.filename)
            if deleted:
                logger.info(f"[SyncWorker] Deleted document: {source.filename}")
        except Exception as exc:
            logger.warning(f"[SyncWorker] Could not delete {source.filename}: {exc}")
