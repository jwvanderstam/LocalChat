"""
Long-Term Memory Operations
============================

Mixin providing CRUD and vector-search operations for the ``memories`` table.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import numpy as np

from ..utils.logging_config import get_logger
from .connection import DatabaseUnavailableError

if TYPE_CHECKING:
    from .connection import DatabaseConnection

logger = get_logger(__name__)

_MIN_SIMILARITY_DEFAULT = 0.50
_DEDUP_THRESHOLD = 0.92


class MemoriesMixin:
    """Mixin that adds long-term memory operations to the Database class."""

    is_connected: bool
    get_connection: DatabaseConnection.get_connection  # type: ignore[assignment]
    _embedding_to_pg_array: DatabaseConnection._embedding_to_pg_array  # type: ignore[assignment]

    # ── Write operations ───────────────────────────────────────────────────────

    def insert_memory(
        self,
        content: str,
        embedding: list[float],
        source_conv_id: str | None = None,
        memory_type: str = "fact",
        confidence: float = 1.0,
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
                                         memory_type, confidence)
                    VALUES (%s, %s, %s::vector, %s, %s, %s)
                    """,
                    (memory_id, content, emb_str, source_conv_id, memory_type, confidence),
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

    def delete_memory(self, memory_id: str) -> None:
        """Delete a single memory by UUID."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot delete memory: Database not connected")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM memories WHERE id = %s::uuid", (memory_id,))
                conn.commit()

    def delete_all_memories(self) -> int:
        """Delete all memories. Returns count deleted."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot delete memories: Database not connected")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM memories")
                count = cursor.rowcount
                conn.commit()
        logger.info(f"Deleted {count} memories")
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
    ) -> list[dict[str, Any]]:
        """Return top-k memories ordered by cosine similarity."""
        if not self.is_connected:
            return []
        emb_str = self._embedding_to_pg_array(np.array(embedding))
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id::text, content, memory_type, confidence,
                           created_at, use_count,
                           1 - (embedding <=> %s::vector) AS similarity
                    FROM memories
                    WHERE embedding IS NOT NULL
                      AND 1 - (embedding <=> %s::vector) >= %s
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (emb_str, emb_str, min_similarity, emb_str, top_k),
                )
                rows = cursor.fetchall()
        return [
            {
                "id": r[0], "content": r[1], "memory_type": r[2],
                "confidence": r[3], "created_at": r[4].isoformat() if r[4] else None,
                "use_count": r[5], "similarity": float(r[6]),
            }
            for r in rows
        ]

    def is_duplicate_memory(
        self,
        embedding: list[float],
        threshold: float = _DEDUP_THRESHOLD,
    ) -> bool:
        """Return True if a very similar memory already exists (deduplication guard)."""
        if not self.is_connected:
            return False
        emb_str = self._embedding_to_pg_array(np.array(embedding))
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT 1 FROM memories
                    WHERE embedding IS NOT NULL
                      AND 1 - (embedding <=> %s::vector) >= %s
                    LIMIT 1
                    """,
                    (emb_str, threshold),
                )
                return cursor.fetchone() is not None

    def get_all_memories(
        self, limit: int = 200, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Return all memories ordered by creation date descending."""
        if not self.is_connected:
            return []
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id::text, content, memory_type, confidence,
                           created_at, last_used, use_count, source_conv::text
                    FROM memories
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (limit, offset),
                )
                rows = cursor.fetchall()
        return [
            {
                "id": r[0], "content": r[1], "memory_type": r[2],
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
                    SELECT id::text, title, updated_at
                    FROM conversations
                    WHERE memory_extracted_at IS NULL
                       OR memory_extracted_at < updated_at
                    ORDER BY updated_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
        return [
            {"id": r[0], "title": r[1], "updated_at": r[2].isoformat() if r[2] else None}
            for r in rows
        ]
