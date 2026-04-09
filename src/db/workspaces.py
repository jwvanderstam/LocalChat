"""
Workspaces Mixin
================

Provides CRUD operations for the ``workspaces`` table and the helpers
needed to scope documents, conversations, and memories per workspace.
"""
from __future__ import annotations

from typing import Any

from ..utils.logging_config import get_logger
from .connection import DatabaseUnavailableError

logger = get_logger(__name__)


class WorkspacesMixin:
    """Mixin providing workspace CRUD operations."""

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_workspace(
        self,
        name: str,
        description: str = '',
        system_prompt: str = '',
        model_class: str | None = None,
    ) -> str:
        """Create a new workspace and return its UUID string."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot create workspace: DB not connected")
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO workspaces (name, description, system_prompt, model_class)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (name[:255], description, system_prompt, model_class),
                )
                workspace_id = str(cur.fetchone()[0])
        logger.info(f"[Workspace] Created '{name}' id={workspace_id}")
        return workspace_id

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        """Return workspace dict or None if not found."""
        if not self.is_connected:
            return None
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, name, description, system_prompt, model_class, created_at
                    FROM workspaces WHERE id = %s
                    """,
                    (workspace_id,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return _row_to_workspace(row)

    def list_workspaces(self) -> list[dict[str, Any]]:
        """Return all workspaces with document/conversation counts."""
        if not self.is_connected:
            return []
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT w.id, w.name, w.description, w.system_prompt, w.model_class,
                           w.created_at,
                           COUNT(DISTINCT d.id)  AS document_count,
                           COUNT(DISTINCT c.id)  AS conversation_count
                    FROM   workspaces w
                    LEFT JOIN documents     d ON d.workspace_id = w.id
                    LEFT JOIN conversations c ON c.workspace_id = w.id
                    GROUP BY w.id
                    ORDER BY w.created_at
                    """
                )
                rows = cur.fetchall()
        return [
            {**_row_to_workspace(r[:6]), 'document_count': r[6], 'conversation_count': r[7]}
            for r in rows
        ]

    def get_default_workspace_id(self) -> str | None:
        """Return the UUID of the oldest workspace (used as the default)."""
        if not self.is_connected:
            return None
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM workspaces ORDER BY created_at LIMIT 1")
                row = cur.fetchone()
        return str(row[0]) if row else None

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update_workspace(
        self,
        workspace_id: str,
        name: str | None = None,
        description: str | None = None,
        system_prompt: str | None = None,
        model_class: str | None = None,
    ) -> bool:
        """Update editable workspace fields. Returns True if a row was changed."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot update workspace: DB not connected")
        sets: list[str] = []
        params: list = []
        if name is not None:
            sets.append("name = %s")
            params.append(name[:255])
        if description is not None:
            sets.append("description = %s")
            params.append(description)
        if system_prompt is not None:
            sets.append("system_prompt = %s")
            params.append(system_prompt)
        if model_class is not None:
            sets.append("model_class = %s")
            params.append(model_class)
        if not sets:
            return False
        params.append(workspace_id)
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE workspaces SET {', '.join(sets)} WHERE id = %s",
                    params,
                )
                return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_workspace(self, workspace_id: str) -> bool:
        """Delete a workspace (cascades to member rows). Returns True if deleted."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot delete workspace: DB not connected")
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM workspaces WHERE id = %s", (workspace_id,))
                return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _row_to_workspace(row: tuple) -> dict[str, Any]:
    return {
        'id': str(row[0]),
        'name': row[1],
        'description': row[2] or '',
        'system_prompt': row[3] or '',
        'model_class': row[4],
        'created_at': row[5].isoformat() if row[5] else None,
    }
