from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import numpy as np

from ..utils.encryption import decrypt as _decrypt
from ..utils.encryption import encrypt as _encrypt
from ..utils.logging_config import get_logger
from .connection import DatabaseUnavailableError

if TYPE_CHECKING:
    from .connection import MixinHost
else:
    MixinHost = object

logger = get_logger(__name__)

_MIN_SIMILARITY_DEFAULT = 0.50
_DEDUP_THRESHOLD = 0.92


class MemoriesMixin(MixinHost):
    """Mixin that adds long-term memory operations to the Database class."""

    @staticmethod
    def _allowed_workspace_ids(
        workspace_id: str | None, additional_workspace_ids: list[str] | None = None
    ) -> list[str]:
        """Workspaces a query may read from. Empty means unscoped (no filter)."""
        if not workspace_id:
            return []
        return [workspace_id, *(additional_workspace_ids or [])]

    # ── Write operations ───────────────────────────────────────────────────────

    def insert_memory(
        self,
        content: str,
        embedding: list[float],
        source_conv_id: str | None = None,
        memory_type: str = "fact",
        confidence: float = 1.0,
        workspace_id: str | None = None,
    ) -> str:
        """Insert a memory and return its UUID string."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot insert memory: Database not connected")

        memory_id = str(uuid.uuid4())
        emb_str = self._embedding_to_pg_array(np.array(embedding))
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO memories (id, content, embedding, source_conv,
                                         memory_type, confidence, workspace_id)
                    VALUES (%s, %s, %s::vector, %s, %s, %s, %s)
                    """,
                    (memory_id, _encrypt(content), emb_str, source_conv_id,
                     memory_type, confidence, workspace_id),
                )
                conn.commit()
        logger.debug(f"Inserted memory {memory_id} type={memory_type}")
        return memory_id

    def update_memory_usage(self, memory_ids: list[str]) -> None:
        """Bump use_count and last_used for the given memory IDs."""
        if not memory_ids or not self.is_connected:
            return
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE memories
                    SET use_count = use_count + 1, last_used = CURRENT_TIMESTAMP
                    WHERE id = ANY(%s::uuid[])
                    """,
                    (memory_ids,),
                )
                conn.commit()

    def delete_memory(self, memory_id: str, deleted_by: str | None = None) -> bool:
        """Soft-delete a single memory by UUID. Returns True if a live row was retired."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot delete memory: Database not connected")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE memories SET deleted_at = NOW(), deleted_by = %s "
                    "WHERE id = %s::uuid AND deleted_at IS NULL",
                    (deleted_by, memory_id),
                )
                conn.commit()
                return cursor.rowcount > 0

    def delete_all_memories(self, deleted_by: str | None = None) -> int:
        """Soft-delete all memories. Returns count retired."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot delete memories: Database not connected")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE memories SET deleted_at = NOW(), deleted_by = %s "
                    "WHERE deleted_at IS NULL",
                    (deleted_by,),
                )
                count = cursor.rowcount
                conn.commit()
        logger.info(f"Soft-deleted {count} memories")
        return count

    def mark_conversation_extracted(self, conversation_id: str) -> None:
        """Record that memories have been extracted for this conversation."""
        if not self.is_connected:
            return
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE conversations SET memory_extracted_at = CURRENT_TIMESTAMP WHERE id = %s",
                    (conversation_id,),
                )
                conn.commit()

    # ── Read operations ────────────────────────────────────────────────────────

    def search_memories(
        self,
        embedding: list[float],
        top_k: int = 5,
        min_similarity: float = _MIN_SIMILARITY_DEFAULT,
        workspace_id: str | None = None,
        additional_workspace_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return top-k memories ordered by cosine similarity, scoped to a workspace."""
        if not self.is_connected:
            return []
        emb_str = self._embedding_to_pg_array(np.array(embedding))
        # A memory with no workspace cannot be attributed to one, so it stays
        # invisible rather than surfacing everywhere — same call doc retrieval
        # makes. Unscoped callers (workspace_id=None) still see everything.
        allowed = self._allowed_workspace_ids(workspace_id, additional_workspace_ids)
        ws_clause = "  AND workspace_id = ANY(%s::uuid[])\n" if allowed else ""
        params: list[Any] = [emb_str, emb_str, min_similarity]
        if allowed:
            params.append(allowed)
        params += [emb_str, top_k]
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT id::text, content, memory_type, confidence,
                           created_at, use_count,
                           1 - (embedding <=> %s::vector) AS similarity
                    FROM memories
                    WHERE embedding IS NOT NULL
                      AND deleted_at IS NULL
                      AND 1 - (embedding <=> %s::vector) >= %s
                    {ws_clause}
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    tuple(params),
                )
                rows = cursor.fetchall()
        return [
            {
                "id": r[0], "content": _decrypt(r[1]), "memory_type": r[2],
                "confidence": r[3], "created_at": r[4].isoformat() if r[4] else None,
                "use_count": r[5], "similarity": float(r[6]),
            }
            for r in rows
        ]

    def is_duplicate_memory(
        self,
        embedding: list[float],
        threshold: float = _DEDUP_THRESHOLD,
        workspace_id: str | None = None,
    ) -> bool:
        """Return True if a very similar memory already exists in this workspace.

        Scoped deliberately: an unscoped guard lets a memory in one workspace
        suppress the creation of the same memory in another, which is the write
        side of the same isolation failure.
        """
        if not self.is_connected:
            return False
        emb_str = self._embedding_to_pg_array(np.array(embedding))
        ws_clause = "  AND workspace_id = %s::uuid\n" if workspace_id else ""
        params: list[Any] = [emb_str, threshold]
        if workspace_id:
            params.append(workspace_id)
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT 1 FROM memories
                    WHERE embedding IS NOT NULL
                      AND deleted_at IS NULL
                      AND 1 - (embedding <=> %s::vector) >= %s
                    {ws_clause}
                    LIMIT 1
                    """,
                    tuple(params),
                )
                return cursor.fetchone() is not None

    def get_all_memories(
        self, limit: int = 200, offset: int = 0, workspace_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Return memories for a workspace, ordered by creation date descending."""
        if not self.is_connected:
            return []
        ws_clause = "  AND workspace_id = %s::uuid\n" if workspace_id else ""
        params: list[Any] = []
        if workspace_id:
            params.append(workspace_id)
        params += [limit, offset]
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT id::text, content, memory_type, confidence,
                           created_at, last_used, use_count, source_conv::text
                    FROM memories
                    WHERE deleted_at IS NULL
                    {ws_clause}
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    tuple(params),
                )
                rows = cursor.fetchall()
        return [
            {
                "id": r[0], "content": _decrypt(r[1]), "memory_type": r[2],
                "confidence": r[3],
                "created_at": r[4].isoformat() if r[4] else None,
                "last_used": r[5].isoformat() if r[5] else None,
                "use_count": r[6], "source_conv": r[7],
            }
            for r in rows
        ]

    def get_unextracted_conversations(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return conversations whose memory_extracted_at is behind updated_at."""
        if not self.is_connected:
            return []
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id::text, title, updated_at, workspace_id::text
                    FROM conversations
                    WHERE deleted_at IS NULL
                      AND (memory_extracted_at IS NULL OR memory_extracted_at < updated_at)
                    ORDER BY updated_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
        return [
            {
                "id": r[0], "title": r[1],
                "updated_at": r[2].isoformat() if r[2] else None,
                "workspace_id": r[3],
            }
            for r in rows
        ]
