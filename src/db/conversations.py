from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from ..utils.encryption import decrypt as _decrypt
from ..utils.encryption import encrypt as _encrypt
from ..utils.logging_config import get_logger
from .connection import DatabaseUnavailableError

if TYPE_CHECKING:
    from .connection import MixinHost
else:
    MixinHost = object

logger = get_logger(__name__)


class ConversationsMixin(MixinHost):
    """Mixin that adds conversation and message operations to the Database class."""

    def create_conversation(self, title: str = 'New Conversation', workspace_id: str | None = None) -> str:
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot create conversation: Database is not connected")

        conversation_id = str(uuid.uuid4())
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO conversations (id, title, workspace_id) VALUES (%s, %s, %s)",
                    (conversation_id, title[:255], workspace_id),
                )
                conn.commit()
        logger.debug(f"Created conversation: {conversation_id}")
        return conversation_id

    def create_conversation_with_message(
        self,
        title: str,
        role: str,
        content: str,
        workspace_id: str | None = None,
        plan_json: dict | None = None,
    ) -> tuple[str, int]:
        """Create a conversation and save its first message in a single transaction.

        Avoids an orphaned empty conversation if the message insert fails.

        Returns:
            (conversation_id, message_id)
        """
        if not self.is_connected:
            raise DatabaseUnavailableError(
                "Cannot create conversation: Database is not connected"
            )

        from psycopg.types.json import Jsonb

        conversation_id = str(uuid.uuid4())
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO conversations (id, title, workspace_id) VALUES (%s, %s, %s)",
                    (conversation_id, title[:255], workspace_id),
                )
                cursor.execute(
                    """
                    WITH ins AS (
                        INSERT INTO conversation_messages
                            (conversation_id, role, content, plan_json)
                        VALUES (%s, %s, %s, %s) RETURNING id
                    ), upd AS (
                        UPDATE conversations
                        SET updated_at = CURRENT_TIMESTAMP WHERE id = %s
                    )
                    SELECT id FROM ins
                    """,
                    (
                        conversation_id,
                        role,
                        _encrypt(content),
                        Jsonb(plan_json) if plan_json else None,
                        conversation_id,
                    ),
                )
                row = cursor.fetchone()
                assert row is not None, "INSERT ... RETURNING id always returns a row"
                message_id = row[0]
                conn.commit()
        logger.debug(f"Created conversation {conversation_id} with first message (id={message_id})")
        return conversation_id, message_id

    def list_conversations(
        self,
        limit: int = 50,
        offset: int = 0,
        workspace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return conversations ordered by updated_at DESC (id, title, created_at, updated_at, message_count)."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot list conversations: Database is not connected")

        limit = max(1, min(limit, 200))
        offset = max(0, offset)

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                if workspace_id:
                    cursor.execute("""
                        SELECT c.id, c.title, c.created_at, c.updated_at,
                               COUNT(cm.id) AS message_count
                        FROM conversations c
                        LEFT JOIN conversation_messages cm ON c.id = cm.conversation_id
                        WHERE c.workspace_id = %s AND c.deleted_at IS NULL
                        GROUP BY c.id, c.title, c.created_at, c.updated_at
                        ORDER BY c.updated_at DESC
                        LIMIT %s OFFSET %s
                    """, (workspace_id, limit, offset))
                else:
                    cursor.execute("""
                        SELECT c.id, c.title, c.created_at, c.updated_at,
                               COUNT(cm.id) AS message_count
                        FROM conversations c
                        LEFT JOIN conversation_messages cm ON c.id = cm.conversation_id
                        WHERE c.deleted_at IS NULL
                        GROUP BY c.id, c.title, c.created_at, c.updated_at
                        ORDER BY c.updated_at DESC
                        LIMIT %s OFFSET %s
                    """, (limit, offset))
                rows = cursor.fetchall()
                return [
                    {
                        'id': str(row[0]),
                        'title': row[1],
                        'created_at': row[2].isoformat() if row[2] else None,
                        'updated_at': row[3].isoformat() if row[3] else None,
                        'message_count': row[4],
                    }
                    for row in rows
                ]

    def get_conversation_messages(
        self, conversation_id: str
    ) -> list[dict[str, Any]] | None:
        """Return messages (role, content, timestamp) ordered ASC, or None if conversation not found."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot get messages: Database is not connected")

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT cm.role, cm.content, cm.created_at
                    FROM conversations c
                    JOIN conversation_messages cm ON cm.conversation_id = c.id
                    WHERE c.id = %s AND c.deleted_at IS NULL
                    ORDER BY cm.created_at ASC, cm.id ASC
                """, (conversation_id,))
                rows = cursor.fetchall()
                if not rows:
                    cursor.execute(
                        "SELECT 1 FROM conversations WHERE id = %s AND deleted_at IS NULL",
                        (conversation_id,),
                    )
                    if not cursor.fetchone():
                        return None
                return [
                    {
                        'role': row[0],
                        'content': _decrypt(row[1]),
                        'timestamp': row[2].isoformat() if row[2] else None,
                    }
                    for row in rows
                ]

    def save_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        plan_json: dict | None = None,
    ) -> int:
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot save message: Database is not connected")

        from psycopg.types.json import Jsonb

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    WITH ins AS (
                        INSERT INTO conversation_messages (conversation_id, role, content, plan_json)
                        VALUES (%s, %s, %s, %s) RETURNING id
                    ), upd AS (
                        UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = %s
                    )
                    SELECT id FROM ins
                    """,
                    (conversation_id, role, _encrypt(content), Jsonb(plan_json) if plan_json else None, conversation_id),
                )
                row = cursor.fetchone()
                assert row is not None, "INSERT ... RETURNING id always returns a row"
                message_id = row[0]
                conn.commit()
        logger.debug(f"Saved {role} message (id={message_id}) to conversation {conversation_id}")
        return message_id

    def update_message_plan_json(self, message_id: int, plan_json: dict) -> None:
        """Attach tool_trace and agent warnings to the user turn after AggregatorAgent finishes."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot update message: Database is not connected")

        from psycopg.types.json import Jsonb

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE conversation_messages SET plan_json = %s WHERE id = %s",
                    (Jsonb(plan_json), message_id),
                )
                conn.commit()
        logger.debug(f"Updated plan_json for message id={message_id}")

    def update_conversation_title(self, conversation_id: str, title: str) -> bool:
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot update conversation: Database is not connected")

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE conversations SET title = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s AND deleted_at IS NULL",
                    (title[:255], conversation_id),
                )
                updated = cursor.rowcount > 0
                conn.commit()
        return updated

    def get_conversation_document_filter(self, conversation_id: str) -> list[str]:
        """Return filenames to restrict retrieval to; empty list means all documents."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot get document filter: Database is not connected")

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT document_ids FROM conversations WHERE id = %s AND deleted_at IS NULL",
                    (conversation_id,),
                )
                row = cursor.fetchone()
        if row is None:
            return []
        return list(row[0]) if row[0] else []

    def set_conversation_document_filter(
        self, conversation_id: str, filenames: list[str]
    ) -> bool:
        """Store a document filename filter; pass an empty list to clear (all documents)."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot set document filter: Database is not connected")

        import json as _json
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE conversations SET document_ids = %s::jsonb WHERE id = %s AND deleted_at IS NULL",
                    (_json.dumps(filenames), conversation_id),
                )
                updated = cursor.rowcount > 0
                conn.commit()
        if updated:
            logger.debug(f"Set document filter for {conversation_id}: {filenames}")
        return updated

    def delete_conversation(self, conversation_id: str, deleted_by: str | None = None) -> bool:
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot delete conversation: Database is not connected")

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE conversations SET deleted_at = NOW(), deleted_by = %s WHERE id = %s AND deleted_at IS NULL",
                    (deleted_by, conversation_id),
                )
                updated = cursor.rowcount > 0
                conn.commit()
        if updated:
            logger.debug(f"Soft-deleted conversation: {conversation_id}")
        return updated

    def delete_all_conversations(self, workspace_id: str | None = None, deleted_by: str | None = None) -> int:
        """Soft-delete conversations; scoped to workspace when provided."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot delete conversations: Database is not connected")

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                if workspace_id:
                    cursor.execute(
                        "UPDATE conversations SET deleted_at = NOW(), deleted_by = %s WHERE workspace_id = %s AND deleted_at IS NULL",
                        (deleted_by, workspace_id),
                    )
                else:
                    logger.warning("Soft-deleting ALL conversations across all workspaces")
                    cursor.execute(
                        "UPDATE conversations SET deleted_at = NOW(), deleted_by = %s WHERE deleted_at IS NULL",
                        (deleted_by,),
                    )
                count = cursor.rowcount
                conn.commit()
        logger.info(f"Soft-deleted {count} conversations")
        return count

    def purge_conversation(self, conversation_id: str) -> bool:
        """Hard-delete a soft-deleted conversation if no memories cite it. Returns False when blocked."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot purge conversation: Database is not connected")

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM memories WHERE source_conv = %s LIMIT 1",
                    (conversation_id,),
                )
                if cursor.fetchone():
                    logger.debug(f"Purge blocked: memories cite conversation {conversation_id}")
                    return False
                cursor.execute("DELETE FROM conversations WHERE id = %s", (conversation_id,))
                deleted = cursor.rowcount > 0
                conn.commit()
        if deleted:
            logger.info(f"Purged conversation: {conversation_id}")
        return deleted

    def get_low_confidence_queries(
        self, workspace_id: str | None = None, threshold: float = 0.5, limit: int = 50
    ) -> list[str]:
        """Return user query strings that received poor or no positive feedback.

        Identifies queries by joining conversation_messages (role=user) with
        answer_feedback on the next assistant message.  Returns queries where
        the average rating is below *threshold* or where no feedback was given.
        """
        if not self.is_connected:
            return []
        try:
            ws_filter = "AND c.workspace_id = %s" if workspace_id else ""
            live_filter = "AND c.deleted_at IS NULL"
            params: list[Any] = []
            if workspace_id:
                params.append(workspace_id)
            params.append(threshold)
            params.append(limit)
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        f"""
                        SELECT um.content
                        FROM conversation_messages um
                        JOIN conversations c ON c.id = um.conversation_id
                        WHERE um.role = 'user' {ws_filter} {live_filter}
                          AND (
                            -- has feedback below threshold
                            EXISTS (
                                SELECT 1 FROM answer_feedback af
                                WHERE af.conversation_id = um.conversation_id
                                  AND af.rating < %s
                            )
                            OR
                            -- no feedback at all
                            NOT EXISTS (
                                SELECT 1 FROM answer_feedback af
                                WHERE af.conversation_id = um.conversation_id
                            )
                          )
                        ORDER BY um.created_at DESC
                        LIMIT %s
                        """,
                        params,
                    )
                    return [row[0] for row in cursor.fetchall()]
        except Exception as exc:
            logger.warning(f"get_low_confidence_queries failed: {exc}")
            return []
