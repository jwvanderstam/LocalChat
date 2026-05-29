"""
Annotations Mixin
=================

Provides CRUD operations for the ``annotations`` table.
Annotations allow users to attach notes to specific document chunks,
optionally linked to a conversation.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..utils.logging_config import get_logger
from .connection import DatabaseUnavailableError

if TYPE_CHECKING:
    from .connection import DatabaseConnection

logger = get_logger(__name__)


class AnnotationsMixin:
    """Mixin providing annotation CRUD operations."""

    is_connected: bool
    get_connection: DatabaseConnection.get_connection  # type: ignore[assignment]

    def add_annotation(
        self,
        chunk_id: int,
        text: str,
        user_id: str | None = None,
        conversation_id: str | None = None,
    ) -> str:
        """Insert an annotation and return its UUID string."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot add annotation: DB not connected")
        if not text or not text.strip():
            raise ValueError("Annotation text must not be empty")
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO annotations (chunk_id, text, user_id, conversation_id)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (chunk_id, text.strip(), user_id, conversation_id),
                )
                annotation_id = str(cur.fetchone()[0])
                conn.commit()
        logger.debug(f"[Annotations] Created {annotation_id} on chunk {chunk_id}")
        return annotation_id

    def get_annotations_for_chunk(self, chunk_id: int) -> list[dict[str, Any]]:
        """Return all annotations for a given chunk, ordered by creation time."""
        if not self.is_connected:
            return []
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT a.id, a.chunk_id, a.conversation_id, a.user_id,
                           a.text, a.created_at, u.username
                    FROM annotations a
                    LEFT JOIN users u ON u.id = a.user_id
                    WHERE a.chunk_id = %s
                    ORDER BY a.created_at
                    """,
                    (chunk_id,),
                )
                rows = cur.fetchall()
        return [
            {
                'id': str(r[0]),
                'chunk_id': r[1],
                'conversation_id': str(r[2]) if r[2] else None,
                'user_id': str(r[3]) if r[3] else None,
                'text': r[4],
                'created_at': r[5].isoformat() if r[5] else None,
                'username': r[6],
            }
            for r in rows
        ]

    def delete_annotation(self, annotation_id: str, user_id: str | None = None) -> bool:
        """Delete an annotation.

        If *user_id* is provided, only deletes if the annotation belongs to that user.
        Returns True if a row was deleted.
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot delete annotation: DB not connected")
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                if user_id:
                    cur.execute(
                        "DELETE FROM annotations WHERE id = %s AND user_id = %s",
                        (annotation_id, user_id),
                    )
                else:
                    cur.execute("DELETE FROM annotations WHERE id = %s", (annotation_id,))
                deleted = cur.rowcount > 0
                conn.commit()
        return deleted
