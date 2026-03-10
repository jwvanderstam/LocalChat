"""
Conversation Operations Module
===============================

Mixin providing persistent chat-memory operations (conversations and messages).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ..utils.logging_config import get_logger
from .connection import DatabaseUnavailableError

if TYPE_CHECKING:
    from .connection import DatabaseConnection

logger = get_logger(__name__)


class ConversationsMixin:
    """Mixin that adds conversation and message operations to the Database class."""

    # Provided by DatabaseConnection at runtime via MRO
    is_connected: bool
    get_connection: DatabaseConnection.get_connection  # type: ignore[assignment]

    def create_conversation(self, title: str = 'New Conversation') -> str:
        """
        Create a new conversation and return its UUID.

        Args:
            title: Conversation title (truncated to 255 chars)

        Returns:
            str: UUID of the created conversation

        Raises:
            DatabaseUnavailableError: If database is not connected
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot create conversation: Database is not connected")

        conversation_id = str(uuid.uuid4())
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO conversations (id, title) VALUES (%s, %s)",
                    (conversation_id, title[:255]),
                )
                conn.commit()
        logger.debug(f"Created conversation: {conversation_id}")
        return conversation_id

    def list_conversations(self) -> List[Dict[str, Any]]:
        """
        List all conversations ordered by most recently updated.

        Returns:
            List of dicts with keys: id, title, created_at, updated_at, message_count

        Raises:
            DatabaseUnavailableError: If database is not connected
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot list conversations: Database is not connected")

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT c.id, c.title, c.created_at, c.updated_at,
                           COUNT(cm.id) AS message_count
                    FROM conversations c
                    LEFT JOIN conversation_messages cm ON c.id = cm.conversation_id
                    GROUP BY c.id, c.title, c.created_at, c.updated_at
                    ORDER BY c.updated_at DESC
                """)
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
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get all messages for a conversation.

        Args:
            conversation_id: UUID of the conversation

        Returns:
            List of message dicts (role, content, timestamp), or None if not found

        Raises:
            DatabaseUnavailableError: If database is not connected
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot get messages: Database is not connected")

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM conversations WHERE id = %s", (conversation_id,)
                )
                if not cursor.fetchone():
                    return None

                cursor.execute("""
                    SELECT role, content, created_at
                    FROM conversation_messages
                    WHERE conversation_id = %s
                    ORDER BY created_at ASC, id ASC
                """, (conversation_id,))
                rows = cursor.fetchall()
                return [
                    {
                        'role': row[0],
                        'content': row[1],
                        'timestamp': row[2].isoformat() if row[2] else None,
                    }
                    for row in rows
                ]

    def save_message(self, conversation_id: str, role: str, content: str) -> int:
        """
        Append a message to a conversation and update its timestamp.

        Args:
            conversation_id: UUID of the conversation
            role: 'user' or 'assistant'
            content: Message text

        Returns:
            int: ID of the inserted message row

        Raises:
            DatabaseUnavailableError: If database is not connected
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot save message: Database is not connected")

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO conversation_messages (conversation_id, role, content)
                       VALUES (%s, %s, %s) RETURNING id""",
                    (conversation_id, role, content),
                )
                message_id = cursor.fetchone()[0]
                cursor.execute(
                    "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                    (conversation_id,),
                )
                conn.commit()
        logger.debug(f"Saved {role} message (id={message_id}) to conversation {conversation_id}")
        return message_id

    def update_conversation_title(self, conversation_id: str, title: str) -> bool:
        """
        Update a conversation's title.

        Args:
            conversation_id: UUID of the conversation
            title: New title (truncated to 255 chars)

        Returns:
            bool: True if updated, False if conversation not found

        Raises:
            DatabaseUnavailableError: If database is not connected
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot update conversation: Database is not connected")

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE conversations SET title = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                    (title[:255], conversation_id),
                )
                updated = cursor.rowcount > 0
                conn.commit()
        return updated

    def delete_conversation(self, conversation_id: str) -> bool:
        """
        Delete a conversation and all its messages (via CASCADE).

        Args:
            conversation_id: UUID of the conversation

        Returns:
            bool: True if deleted, False if not found

        Raises:
            DatabaseUnavailableError: If database is not connected
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot delete conversation: Database is not connected")

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM conversations WHERE id = %s", (conversation_id,)
                )
                deleted = cursor.rowcount > 0
                conn.commit()
        logger.debug(f"Deleted conversation: {conversation_id}")
        return deleted

    def delete_all_conversations(self) -> int:
        """
        Delete every conversation and all associated messages.

        WARNING: This operation cannot be undone!

        Returns:
            int: Number of conversations deleted

        Raises:
            DatabaseUnavailableError: If database is not connected
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot delete conversations: Database is not connected")

        logger.warning("Deleting ALL conversations and messages")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM conversations")
                deleted = cursor.rowcount
                conn.commit()
        logger.info(f"Deleted {deleted} conversations (messages removed via cascade)")
        return deleted
