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
from ..utils.scope import Scope, scope_predicate
from .connection import DatabaseUnavailableError

if TYPE_CHECKING:
    from .connection import MixinHost
else:
    MixinHost = object

logger = get_logger(__name__)


class AnnotationsMixin(MixinHost):
    """Mixin providing annotation CRUD operations."""

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
                row = cur.fetchone()
                if row is None:
                    raise AssertionError("INSERT ... RETURNING id always returns a row")
                annotation_id = str(row[0])
                conn.commit()
        logger.debug(f"[Annotations] Created {annotation_id} on chunk {chunk_id}")
        return annotation_id

    def get_annotations_for_chunk(
        self, chunk_id: int, *, scope: Scope
    ) -> list[dict[str, Any]]:
        """Return all annotations for a given chunk, ordered by creation time.

        An annotation has no workspace of its own — it borrows the one belonging to
        its chunk's document, which is what the join is for.
        """
        if not self.is_connected:
            return []
        where, params = scope_predicate(scope, "d.workspace_id")
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT a.id, a.chunk_id, a.conversation_id, a.user_id,
                           a.text, a.created_at, u.username
                    FROM annotations a
                    JOIN document_chunks dc ON dc.id = a.chunk_id
                    JOIN documents d ON d.id = dc.document_id
                    LEFT JOIN users u ON u.id = a.user_id
                    WHERE a.chunk_id = %s AND a.deleted_at IS NULL
                      AND d.deleted_at IS NULL
                    """ + where + """
                    ORDER BY a.created_at
                    """,
                    (chunk_id, *params),
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

    def delete_annotation(
        self,
        annotation_id: str,
        user_id: str | None = None,
        deleted_by: str | None = None,
        *,
        scope: Scope,
    ) -> bool:
        """Soft-delete an annotation.

        If *user_id* is provided, only deletes if the annotation belongs to that user.
        Returns True if a live row was retired. Scoped through the chunk's document,
        so an annotation in another workspace is not retirable by id (C2).
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot delete annotation: DB not connected")
        where, params = scope_predicate(scope, "d.workspace_id")
        in_scope = """
            AND EXISTS (
                SELECT 1 FROM document_chunks dc
                JOIN documents d ON d.id = dc.document_id
                WHERE dc.id = annotations.chunk_id AND d.deleted_at IS NULL
        """ + where + """
            )
        """
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                if user_id:
                    cur.execute(
                        "UPDATE annotations SET deleted_at = NOW(), deleted_by = %s "
                        "WHERE id = %s AND user_id = %s AND deleted_at IS NULL" + in_scope,
                        (deleted_by, annotation_id, user_id, *params),
                    )
                else:
                    cur.execute(
                        "UPDATE annotations SET deleted_at = NOW(), deleted_by = %s "
                        "WHERE id = %s AND deleted_at IS NULL" + in_scope,
                        (deleted_by, annotation_id, *params),
                    )
                deleted = cur.rowcount > 0
                conn.commit()
        return deleted
