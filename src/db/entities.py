from __future__ import annotations

from typing import Any

from ..utils.logging_config import get_logger
from ..utils.scope import Scope, scope_predicate
from .connection import DatabaseConnection, DatabaseUnavailableError

logger = get_logger(__name__)


class EntitiesRepository:
    """GraphRAG entities and their relations."""

    def __init__(self, db: DatabaseConnection) -> None:
        self._db = db

    # ── Write operations ───────────────────────────────────────────────────────

    def upsert(
        self,
        name: str,
        entity_type: str,
    ) -> str:
        """
        Insert or retrieve an entity.  Bumps doc_count on conflict.

        Returns:
            UUID string of the entity.
        """
        if not self._db.is_connected:
            raise DatabaseUnavailableError("Cannot upsert entity: Database not connected")

        with self._db.get_connection() as conn:
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
                row = cursor.fetchone()
                if row is None:
                    raise AssertionError("INSERT ... RETURNING id always returns a row")
                entity_id: str = row[0]
                conn.commit()
        return entity_id

    def insert_relation(
        self,
        source_id: str,
        target_id: str,
        doc_id: int,
        chunk_id: int,
        relation: str = "mentioned_with",
        weight: float = 1.0,
    ) -> None:
        """Upsert an entity co-occurrence relation, accumulating weight."""
        if not self._db.is_connected:
            return
        with self._db.get_connection() as conn:
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

    # ── Read operations ────────────────────────────────────────────────────────

    def related_names(
        self,
        entity_names: list[str],
        max_results: int = 20,
    ) -> list[str]:
        """
        Return names of entities co-occurring with any of the given entity names.

        Used by the query expander to broaden lexical search terms.
        """
        if not entity_names or not self._db.is_connected:
            return []
        with self._db.get_connection() as conn:
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

    def workspace_ontology(self, top_n: int = 20, *, scope: Scope) -> dict[str, Any]:
        """Return the ontology of *scope*: top entity types and relation patterns."""
        if not self._db.is_connected:
            return {"entity_types": [], "relation_patterns": []}

        ws_filter, params_ws = scope_predicate(scope, "d.workspace_id")

        with self._db.get_connection(scope=scope) as conn:
            with conn.cursor() as cursor:
                # Top entity types by occurrence in workspace docs
                cursor.execute(
                    f"""
                    SELECT e.type, COUNT(DISTINCT er.source_id) AS entity_count
                    FROM entity_relations er
                    JOIN entities e ON e.id = er.source_id
                    JOIN documents d ON d.id = er.doc_id
                    WHERE true {ws_filter}
                    GROUP BY e.type
                    ORDER BY entity_count DESC
                    LIMIT %s
                    """,  # nosec B608  # scope_predicate fragment: literal column, value is %s
                    (*params_ws, top_n),
                )
                entity_types = [
                    {"type": row[0], "count": row[1]}
                    for row in cursor.fetchall()
                ]

                # Top relation patterns by frequency
                cursor.execute(
                    f"""
                    SELECT er.relation, COUNT(*) AS freq
                    FROM entity_relations er
                    JOIN documents d ON d.id = er.doc_id
                    WHERE true {ws_filter}
                    GROUP BY er.relation
                    ORDER BY freq DESC
                    LIMIT %s
                    """,  # nosec B608  # scope_predicate fragment: literal column, value is %s
                    (*params_ws, top_n),
                )
                relation_patterns = [
                    {"relation": row[0], "count": row[1]}
                    for row in cursor.fetchall()
                ]

        return {"entity_types": entity_types, "relation_patterns": relation_patterns}
