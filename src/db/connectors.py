"""
Connectors DB Mixin
====================

CRUD operations for the ``connectors`` and ``connector_sync_log`` tables,
plus the helpers called by ``SyncWorker`` during each sync cycle.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timezone
from typing import Any

from ..utils.logging_config import get_logger
from .connection import DatabaseUnavailableError

logger = get_logger(__name__)


class ConnectorsMixin:
    """Mixin providing connector persistence operations."""

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_connector(
        self,
        connector_type: str,
        display_name: str,
        config: dict,
        workspace_id: str | None = None,
        sync_interval: int = 900,
    ) -> str:
        """Insert a new connector row and return its UUID string."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot create connector: DB not connected")
        from psycopg.types.json import Jsonb
        connector_id = str(uuid.uuid4())
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO connectors
                        (id, workspace_id, connector_type, display_name, config, sync_interval)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (connector_id, workspace_id, connector_type,
                     display_name, Jsonb(config), sync_interval),
                )
                conn.commit()
        logger.info(f"[Connectors] Created {connector_type} connector id={connector_id}")
        return connector_id

    def get_connector(self, connector_id: str) -> dict[str, Any] | None:
        """Return connector row dict or None."""
        if not self.is_connected:
            return None
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, workspace_id, connector_type, display_name, config, "
                    "enabled, sync_interval, last_sync_at, last_error, created_at "
                    "FROM connectors WHERE id = %s",
                    (connector_id,),
                )
                row = cur.fetchone()
        return _row_to_connector(row) if row else None

    def list_connectors(
        self,
        workspace_id: str | None = None,
        enabled_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Return all connectors, optionally filtered by workspace or enabled state."""
        if not self.is_connected:
            return []
        clauses = []
        params: list = []
        if workspace_id:
            clauses.append("workspace_id = %s")
            params.append(workspace_id)
        if enabled_only:
            clauses.append("enabled = true")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT id, workspace_id, connector_type, display_name, config, "
                    f"enabled, sync_interval, last_sync_at, last_error, created_at "
                    f"FROM connectors {where} ORDER BY created_at",
                    params,
                )
                return [_row_to_connector(r) for r in cur.fetchall()]

    def update_connector(self, connector_id: str, **fields) -> bool:
        """Update editable connector fields. Returns True if a row was changed."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot update connector: DB not connected")
        allowed = {"display_name", "config", "enabled", "sync_interval", "workspace_id"}
        sets: list[str] = []
        params: list = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key == "config":
                from psycopg.types.json import Jsonb
                value = Jsonb(value)
            sets.append(f"{key} = %s")
            params.append(value)
        if not sets:
            return False
        params.append(connector_id)
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE connectors SET {', '.join(sets)} WHERE id = %s",
                    params,
                )
                updated = cur.rowcount > 0
                conn.commit()
        return updated

    def delete_connector(self, connector_id: str) -> bool:
        """Delete a connector and its sync log. Returns True if deleted."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot delete connector: DB not connected")
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM connectors WHERE id = %s", (connector_id,))
                deleted = cur.rowcount > 0
                conn.commit()
        return deleted

    # ------------------------------------------------------------------
    # SyncWorker helpers
    # ------------------------------------------------------------------

    def get_connector_interval(self, connector_id: str) -> int | None:
        """Return the sync_interval for a connector (seconds)."""
        if not self.is_connected:
            return None
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT sync_interval FROM connectors WHERE id = %s",
                    (connector_id,),
                )
                row = cur.fetchone()
        return int(row[0]) if row else None

    def update_connector_sync_status(
        self,
        connector_id: str,
        error: str | None = None,
    ) -> None:
        """Update last_sync_at and last_error after a sync cycle."""
        if not self.is_connected:
            return
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE connectors SET last_sync_at = %s, last_error = %s WHERE id = %s",
                    (datetime.now(UTC), error, connector_id),
                )
                conn.commit()

    def start_sync_log(self, connector_id: str) -> int | None:
        """Insert a started sync log row and return its id."""
        if not self.is_connected:
            return None
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO connector_sync_log (connector_id) VALUES (%s) RETURNING id",
                    (connector_id,),
                )
                row = cur.fetchone()
                conn.commit()
        return int(row[0]) if row else None

    def finish_sync_log(
        self,
        log_id: int | None,
        counts: dict[str, int],
        error: str | None = None,
    ) -> None:
        """Mark a sync log row as finished."""
        if not self.is_connected or log_id is None:
            return
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE connector_sync_log
                       SET finished_at = %s,
                           files_added = %s,
                           files_updated = %s,
                           files_deleted = %s,
                           error = %s
                     WHERE id = %s
                    """,
                    (
                        datetime.now(UTC),
                        counts.get("added", 0),
                        counts.get("updated", 0),
                        counts.get("deleted", 0),
                        error,
                        log_id,
                    ),
                )
                conn.commit()

    def get_connector_sync_history(
        self, connector_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Return recent sync log entries for a connector."""
        if not self.is_connected:
            return []
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, started_at, finished_at,
                           files_added, files_updated, files_deleted, error
                    FROM connector_sync_log
                    WHERE connector_id = %s
                    ORDER BY started_at DESC
                    LIMIT %s
                    """,
                    (connector_id, limit),
                )
                rows = cur.fetchall()
        return [
            {
                "id": r[0],
                "started_at": r[1].isoformat() if r[1] else None,
                "finished_at": r[2].isoformat() if r[2] else None,
                "files_added": r[3],
                "files_updated": r[4],
                "files_deleted": r[5],
                "error": r[6],
            }
            for r in rows
        ]

    def delete_document_by_filename(self, filename: str) -> bool:
        """Delete a document and all its chunks by filename. Returns True if found."""
        if not self.is_connected:
            return False
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM documents WHERE filename = %s", (filename,)
                )
                deleted = cur.rowcount > 0
                conn.commit()
        return deleted


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _row_to_connector(row: tuple) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "workspace_id": str(row[1]) if row[1] else None,
        "connector_type": row[2],
        "display_name": row[3],
        "config": dict(row[4]) if row[4] else {},
        "enabled": row[5],
        "sync_interval": row[6],
        "last_sync_at": row[7].isoformat() if row[7] else None,
        "last_error": row[8],
        "created_at": row[9].isoformat() if row[9] else None,
    }
