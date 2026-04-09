"""
Knowledge Graph Operations
==========================

Mixin providing entity and relation CRUD for the GraphRAG feature.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from ..utils.logging_config import get_logger
from .connection import DatabaseUnavailableError

if TYPE_CHECKING:
    from .connection import DatabaseConnection

logger = get_logger(__name__)


class EntitiesMixin:
    """Mixin that adds knowledge-graph entity operations to the Database class."""

    is_connected: bool
    get_connection: DatabaseConnection.get_connection  # type: ignore[assignment]

    # ── Write operations ───────────────────────────────────────────────────────

    def upsert_entity(
        self,
        name: str,
        entity_type: str,
    ) -> str:
        """
        Insert or retrieve an entity.  Bumps doc_count on conflict.

        Returns:
            UUID string of the entity.
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot upsert entity: Database not connected")

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO entities (name, type)
                    VALUES (%s, %s)
                    ON CONFLICT (name, type) DO UPDATE
                    SET doc_count = entities.doc_count + 1
                    RETURNING id::text
                    """,
                    (name[:255], entity_type[:50]),
                )
                entity_id: str = cursor.fetchone()[0]
                conn.commit()
        return entity_id

    def insert_entity_relation(
        self,
        source_id: str,
        target_id: str,
        doc_id: int,
        chunk_id: int,
        relation: str = "mentioned_with",
        weight: float = 1.0,
    ) -> None:
        """Upsert an entity co-occurrence relation, accumulating weight."""
        if not self.is_connected:
            return
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO entity_relations
                        (source_id, target_id, doc_id, chunk_id, relation, weight)
                    VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s)
                    ON CONFLICT (source_id, target_id, chunk_id)
                    DO UPDATE SET weight = entity_relations.weight + EXCLUDED.weight
                    """,
                    (source_id, target_id, doc_id, chunk_id, relation, weight),
                )
                conn.commit()

    def delete_document_entities(self, doc_id: int) -> None:
        """Remove all entity relations for a document (for cleanup on deletion)."""
        if not self.is_connected:
            return
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM entity_relations WHERE doc_id = %s", (doc_id,)
                )
                conn.commit()

    # ── Read operations ────────────────────────────────────────────────────────

    def get_related_entity_names(
        self,
        entity_names: list[str],
        max_results: int = 20,
    ) -> list[str]:
        """
        Return names of entities co-occurring with any of the given entity names.

        Used by the query expander to broaden BM25 search terms.
        """
        if not entity_names or not self.is_connected:
            return []
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT DISTINCT e2.name
                    FROM entities e1
                    JOIN entity_relations er ON er.source_id = e1.id OR er.target_id = e1.id
                    JOIN entities e2 ON (
                        CASE WHEN er.source_id = e1.id THEN er.target_id ELSE er.source_id END = e2.id
                    )
                    WHERE e1.name = ANY(%s)
                      AND e2.name != ALL(%s)
                    ORDER BY e2.name
                    LIMIT %s
                    """,
                    (entity_names, entity_names, max_results),
                )
                return [r[0] for r in cursor.fetchall()]

    def get_entity_by_name(self, name: str) -> dict[str, Any] | None:
        """Return entity dict for an exact name match or None."""
        if not self.is_connected:
            return None
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id::text, name, type, doc_count FROM entities WHERE name = %s LIMIT 1",
                    (name,),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        return {"id": row[0], "name": row[1], "type": row[2], "doc_count": row[3]}

    def get_all_entities(
        self, limit: int = 200, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Return entities ordered by doc_count descending."""
        if not self.is_connected:
            return []
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id::text, name, type, doc_count
                    FROM entities
                    ORDER BY doc_count DESC, name
                    LIMIT %s OFFSET %s
                    """,
                    (limit, offset),
                )
                rows = cursor.fetchall()
        return [
            {"id": r[0], "name": r[1], "type": r[2], "doc_count": r[3]}
            for r in rows
        ]

    def get_entity_stats(self) -> dict[str, int]:
        """Return {entity_count, relation_count} summary."""
        if not self.is_connected:
            return {"entity_count": 0, "relation_count": 0}
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM entities")
                entity_count = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM entity_relations")
                relation_count = cursor.fetchone()[0]
        return {"entity_count": entity_count, "relation_count": relation_count}
