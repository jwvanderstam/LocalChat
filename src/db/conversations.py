from __future__ import annotations

import uuid
from typing import Any

from ..utils.encryption import decrypt as _decrypt
from ..utils.encryption import encrypt as _encrypt
from ..utils.logging_config import get_logger, sanitize_log_value
from ..utils.scope import ALL_WORKSPACES, Scope, scope_predicate
from .connection import DatabaseConnection, DatabaseUnavailableError

logger = get_logger(__name__)


class ConversationsRepository:
    """Conversations and their messages: create, read, retitle, retire and purge."""

    def __init__(self, db: DatabaseConnection) -> None:
        self._db = db

    def create(self, title: str = 'New Conversation', workspace_id: str | None = None) -> str:
        if not self._db.is_connected:
            raise DatabaseUnavailableError("Cannot create conversation: Database is not connected")

        conversation_id = str(uuid.uuid4())
        with self._db.get_connection(scope=workspace_id or ALL_WORKSPACES) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO conversations (id, title, workspace_id) VALUES (%s, %s, %s)",
                    (conversation_id, title[:255], workspace_id),
                )
                conn.commit()
        logger.debug(f"Created conversation: {conversation_id}")
        return conversation_id

    def create_with_message(
        self,
        title: str,
        role: str,
        content: str,
        workspace_id: str | None = None,
        plan_json: dict[str, Any] | None = None,
    ) -> tuple[str, int]:
        """Create a conversation and save its first message in a single transaction.

        Avoids an orphaned empty conversation if the message insert fails.

        Returns:
            (conversation_id, message_id)
        """
        if not self._db.is_connected:
            raise DatabaseUnavailableError(
                "Cannot create conversation: Database is not connected"
            )

        from psycopg.types.json import Jsonb

        conversation_id = str(uuid.uuid4())
        with self._db.get_connection(scope=workspace_id or ALL_WORKSPACES) as conn:
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
                if row is None:
                    raise AssertionError("INSERT ... RETURNING id always returns a row")
                message_id = row[0]
                conn.commit()
        logger.debug(f"Created conversation {conversation_id} with first message (id={message_id})")
        return conversation_id, message_id

    def count(self, *, scope: Scope) -> int:
        """Total live conversations, so a paged listing can say whether more exist.

        Without it a caller cannot tell a full page from the end of the list, and the
        default page of 50 silently hides everything past it.
        """
        if not self._db.is_connected:
            raise DatabaseUnavailableError("Cannot count conversations: Database is not connected")

        scope_sql, scope_params = scope_predicate(scope, "workspace_id")
        with self._db.get_connection(scope=scope) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT COUNT(*) FROM conversations WHERE deleted_at IS NULL{scope_sql}",  # nosec B608  # scope_predicate fragment: literal column, value is %s
                    scope_params,
                )
                row = cursor.fetchone()
                return int(row[0]) if row else 0

    def list_page(
        self,
        limit: int = 50,
        offset: int = 0,
        *,
        scope: Scope,
    ) -> list[dict[str, Any]]:
        """Return conversations ordered by updated_at DESC (id, title, created_at, updated_at, message_count)."""
        if not self._db.is_connected:
            raise DatabaseUnavailableError("Cannot list conversations: Database is not connected")

        limit = max(1, min(limit, 200))
        offset = max(0, offset)

        scope_sql, scope_params = scope_predicate(scope, "c.workspace_id")
        with self._db.get_connection(scope=scope) as conn:
            with conn.cursor() as cursor:
                cursor.execute(f"""
                    SELECT c.id, c.title, c.created_at, c.updated_at,
                           COUNT(cm.id) AS message_count
                    FROM conversations c
                    LEFT JOIN conversation_messages cm ON c.id = cm.conversation_id
                    WHERE c.deleted_at IS NULL{scope_sql}
                    GROUP BY c.id, c.title, c.created_at, c.updated_at
                    ORDER BY c.updated_at DESC
                    LIMIT %s OFFSET %s
                """, (*scope_params, limit, offset))  # nosec B608  # scope_predicate fragment: literal column, value is %s
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

    def messages(
        self, conversation_id: str, *, scope: Scope
    ) -> list[dict[str, Any]] | None:
        """Return messages (role, content, timestamp) ordered ASC, or None if not found.

        Out of scope reads as not found, so a conversation in another workspace cannot
        be told apart from one that does not exist (C2).
        """
        if not self._db.is_connected:
            raise DatabaseUnavailableError("Cannot get messages: Database is not connected")

        where, params = scope_predicate(scope, "c.workspace_id")
        bare_where, _ = scope_predicate(scope, "workspace_id")
        with self._db.get_connection(scope=scope) as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT cm.role, cm.content, cm.created_at
                    FROM conversations c
                    JOIN conversation_messages cm ON cm.conversation_id = c.id
                    WHERE c.id = %s AND c.deleted_at IS NULL
                """ + where + " ORDER BY cm.created_at ASC, cm.id ASC",  # nosec B608  # scope_predicate fragment: literal column, value is %s
                (conversation_id, *params))
                rows = cursor.fetchall()
                if not rows:
                    cursor.execute(
                        "SELECT 1 FROM conversations"
                        " WHERE id = %s AND deleted_at IS NULL" + bare_where,  # nosec B608  # scope_predicate fragment: literal column, value is %s
                        (conversation_id, *params),
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
        plan_json: dict[str, Any] | None = None,
        *,
        scope: Scope,
    ) -> int | None:
        """Append a message to a live conversation in *scope*; None when there is none.

        It wrote to any conversation id on an all-workspaces connection, so a chat naming
        another workspace's conversation appended to it (QP-9 review, R-3).
        """
        if not self._db.is_connected:
            raise DatabaseUnavailableError("Cannot save message: Database is not connected")

        from psycopg.types.json import Jsonb

        where, params = scope_predicate(scope, "workspace_id")
        with self._db.get_connection(scope=scope) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    WITH conv AS (
                        SELECT id FROM conversations
                        WHERE id = %s AND deleted_at IS NULL{where}
                    ), ins AS (
                        INSERT INTO conversation_messages (conversation_id, role, content, plan_json)
                        SELECT id, %s, %s, %s FROM conv RETURNING id
                    ), upd AS (
                        UPDATE conversations SET updated_at = CURRENT_TIMESTAMP
                        WHERE id IN (SELECT id FROM conv)
                    )
                    SELECT id FROM ins
                    """,  # nosec B608  # scope_predicate fragment: literal column, value is %s
                    (conversation_id, *params, role, _encrypt(content), Jsonb(plan_json) if plan_json else None),
                )
                row = cursor.fetchone()
                conn.commit()
                if row is None:
                    return None
                message_id = row[0]
        logger.debug(f"Saved {role} message (id={message_id}) to conversation {conversation_id}")
        return int(message_id)

    def set_title(
        self, conversation_id: str, title: str, *, scope: Scope
    ) -> bool:
        if not self._db.is_connected:
            raise DatabaseUnavailableError("Cannot update conversation: Database is not connected")

        where, params = scope_predicate(scope, "workspace_id")
        with self._db.get_connection(scope=scope) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE conversations SET title = %s, updated_at = CURRENT_TIMESTAMP"
                    " WHERE id = %s AND deleted_at IS NULL" + where,  # nosec B608  # scope_predicate fragment: literal column, value is %s
                    (title[:255], conversation_id, *params),
                )
                updated = cursor.rowcount > 0
                conn.commit()
        return bool(updated)

    def document_filter(
        self, conversation_id: str, *, scope: Scope
    ) -> list[str] | None:
        """Filenames retrieval is restricted to, or None when there is no such
        conversation in scope.

        The distinction matters to the caller: an empty list means "this conversation
        exists and is unfiltered", None means "you cannot see this conversation". Both
        used to be [], which made the route's own 404 branch unreachable and had it
        answer 200 for a conversation in someone else's workspace.
        """
        if not self._db.is_connected:
            raise DatabaseUnavailableError("Cannot get document filter: Database is not connected")

        where, params = scope_predicate(scope, "workspace_id")
        with self._db.get_connection(scope=scope) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT document_ids FROM conversations"
                    " WHERE id = %s AND deleted_at IS NULL" + where,  # nosec B608  # scope_predicate fragment: literal column, value is %s
                    (conversation_id, *params),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        return list(row[0]) if row[0] else []

    def set_document_filter(
        self, conversation_id: str, filenames: list[str], *, scope: Scope
    ) -> bool:
        """Store a document filename filter; pass an empty list to clear (all documents)."""
        if not self._db.is_connected:
            raise DatabaseUnavailableError("Cannot set document filter: Database is not connected")

        import json as _json
        where, params = scope_predicate(scope, "workspace_id")
        with self._db.get_connection(scope=scope) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE conversations SET document_ids = %s::jsonb"
                    " WHERE id = %s AND deleted_at IS NULL" + where,  # nosec B608  # scope_predicate fragment: literal column, value is %s
                    (_json.dumps(filenames), conversation_id, *params),
                )
                updated = cursor.rowcount > 0
                conn.commit()
        if updated:
            logger.debug(f"Set document filter for {conversation_id}: {filenames}")
        return bool(updated)

    def retire(
        self, conversation_id: str, deleted_by: str | None = None, *, scope: Scope
    ) -> bool:
        if not self._db.is_connected:
            raise DatabaseUnavailableError("Cannot delete conversation: Database is not connected")

        where, params = scope_predicate(scope, "workspace_id")
        with self._db.get_connection(scope=scope) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE conversations SET deleted_at = NOW(), deleted_by = %s"
                    " WHERE id = %s AND deleted_at IS NULL" + where,  # nosec B608  # scope_predicate fragment: literal column, value is %s
                    (deleted_by, conversation_id, *params),
                )
                updated = cursor.rowcount > 0
                conn.commit()
        if updated:
            logger.debug(f"Soft-deleted conversation: {conversation_id}")
        return bool(updated)

    def retire_all(self, deleted_by: str | None = None, *, scope: Scope) -> int:
        """Soft-delete every live conversation in *scope*."""
        if not self._db.is_connected:
            raise DatabaseUnavailableError("Cannot delete conversations: Database is not connected")

        if scope is ALL_WORKSPACES:
            logger.warning("Soft-deleting ALL conversations across all workspaces")
        scope_sql, scope_params = scope_predicate(scope, "workspace_id")
        with self._db.get_connection(scope=scope) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE conversations SET deleted_at = NOW(), deleted_by = %s"
                    f" WHERE deleted_at IS NULL{scope_sql}",  # nosec B608  # scope_predicate fragment: literal column, value is %s
                    (deleted_by, *scope_params),
                )
                count = cursor.rowcount
                conn.commit()
        logger.info(f"Soft-deleted {count} conversations")
        return int(count)

    def purge(self, conversation_id: str) -> bool:
        """Hard-delete a soft-deleted conversation if no memories cite it. Returns False when blocked."""
        if not self._db.is_connected:
            raise DatabaseUnavailableError("Cannot purge conversation: Database is not connected")

        with self._db.get_connection(scope=ALL_WORKSPACES) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM memories WHERE source_conv = %s LIMIT 1",
                    (conversation_id,),
                )
                if cursor.fetchone():
                    logger.debug("Purge blocked: memories cite conversation %s",
                                 sanitize_log_value(conversation_id))
                    return False
                cursor.execute("DELETE FROM conversations WHERE id = %s", (conversation_id,))
                deleted = cursor.rowcount > 0
                conn.commit()
        if deleted:
            logger.info("Purged conversation: %s", sanitize_log_value(conversation_id))
        return bool(deleted)

    def low_confidence_queries(
        self, threshold: float = 0.5, limit: int = 50, *, scope: Scope
    ) -> list[str]:
        """Return user query strings that received poor or no positive feedback.

        Identifies queries by joining conversation_messages (role=user) with
        answer_feedback on the next assistant message.  Returns queries where
        the average rating is below *threshold* or where no feedback was given.
        """
        if not self._db.is_connected:
            return []
        # Outside the try, as in get_stale_documents: a missing scope is a defect to
        # raise, not a failed report to render as an empty list.
        ws_filter, scope_params = scope_predicate(scope, "c.workspace_id")
        try:
            live_filter = "AND c.deleted_at IS NULL"
            params: list[Any] = [*scope_params, threshold, limit]
            with self._db.get_connection(scope=scope) as conn:
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
                        """,  # nosec B608  # scope_predicate fragment: literal column, value is %s
                        params,
                    )
                    return [row[0] for row in cursor.fetchall()]
        except Exception as exc:  # noqa: BLE001 — a reporting query; the caller renders an empty list rather than failing
            logger.warning(f"get_low_confidence_queries failed: {exc}")
            return []
