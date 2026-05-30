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
from typing import TYPE_CHECKING

from .. import config as app_config
from ..utils.logging_config import get_logger
from .base import EventType

if TYPE_CHECKING:
    from ..rag.processor import DocumentProcessor

logger = get_logger(__name__)

_TICK = 5              # seconds between "is it time for this connector?" checks
_MAX_FILE_MB = 50      # reject fetched files larger than this
_REINGEST_TICK = 3600  # re-ingest loop check interval (1 hour)


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
        self._reingest_thread: threading.Thread | None = None
        self._next_run: dict[str, float] = {}   # connector_id → epoch seconds

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="connector-sync-worker", daemon=True
        )
        self._thread.start()
        if app_config.REINGEST_ENABLED:
            self._reingest_thread = threading.Thread(
                target=self._reingest_loop, name="connector-reingest-worker", daemon=True
            )
            self._reingest_thread.start()
            logger.info(f"[SyncWorker] Re-ingest loop enabled (max_age={app_config.REINGEST_MAX_AGE_HOURS}h)")
        logger.info("[SyncWorker] Started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=15)
        if self._reingest_thread is not None:
            self._reingest_thread.join(timeout=15)
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
            logger.exception("[SyncWorker] Connector %s error", connector_id)
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
                source_id=connector.connector_id or None,
            )
            if success:
                counts["added" if event.event_type == EventType.ADDED else "updated"] += 1
                logger.debug(f"[SyncWorker] Ingested {event.source.filename}: {message}")
            else:
                logger.warning(f"[SyncWorker] Ingest failed for {event.source.filename}: {message}")
        except Exception:
            logger.exception("[SyncWorker] Ingest error for %s", event.source.filename)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def _reingest_loop(self) -> None:
        """Periodically re-ingest documents older than REINGEST_MAX_AGE_HOURS."""
        while not self._stop_event.is_set():
            try:
                stale = self._db.get_stale_documents(app_config.REINGEST_MAX_AGE_HOURS)
                if stale:
                    logger.info(f"[SyncWorker] Re-ingesting {len(stale)} stale document(s)")
                for doc in stale:
                    if self._stop_event.is_set():
                        break
                    self._reingest_document(doc)
            except Exception:
                logger.exception("[SyncWorker] Re-ingest loop error")
            self._stop_event.wait(timeout=_REINGEST_TICK)

    def _reingest_document(self, doc: dict) -> None:
        filename = doc.get('filename', '')
        doc_id = doc.get('id')
        workspace_id = doc.get('workspace_id')
        try:
            success, message, _new_id = self._doc_processor.ingest_document(
                filename,
                workspace_id=workspace_id,
            )
            if success and doc_id is not None:
                self._db.update_last_ingested_at(doc_id)
                logger.debug(f"[SyncWorker] Re-ingested: {filename}")
            else:
                logger.warning(f"[SyncWorker] Re-ingest failed for {filename}: {message}")
        except Exception as exc:
            logger.warning(f"[SyncWorker] Re-ingest error for {filename}: {exc}")

    def _handle_delete(self, source) -> None:
        try:
            deleted = self._db.delete_document_by_filename(source.filename)
            if deleted:
                logger.info(f"[SyncWorker] Deleted document: {source.filename}")
        except Exception as exc:
            logger.warning(f"[SyncWorker] Could not delete {source.filename}: {exc}")
