"""
Graph Store
===========

Abstraction layer for the GraphRAG knowledge graph backend.

``GraphStore`` is a protocol/ABC defining the three operations needed by
EntityExtractor and QueryExpander.  Two implementations are provided:

- ``PostgresGraphStore``  — delegates to the existing ``entities`` /
  ``entity_relations`` PostgreSQL tables (default, no extra deps).
- ``KuzuGraphStore``       — uses the Kuzu embedded graph database for
  native Cypher-style queries (requires ``kuzu>=0.6.0``).

Select the backend via ``config.GRAPH_BACKEND`` ("postgres" or "kuzu").
When Kuzu is chosen, kuzu must be installed and ``config.KUZU_DB_PATH``
must point to a writable directory.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..utils.logging_config import get_logger

logger = get_logger(__name__)


class GraphStore(ABC):
    """Abstract interface for the entity / relation graph store."""

    @abstractmethod
    def upsert_entity(self, name: str, entity_type: str) -> str:
        """Insert or update an entity. Returns the entity id string."""

    @abstractmethod
    def insert_relation(
        self,
        source_id: str,
        target_id: str,
        doc_id: int,
        chunk_id: int,
        relation: str = 'mentioned_with',
    ) -> None:
        """Record a co-occurrence relation between two entities."""

    @abstractmethod
    def get_related_entity_names(
        self, entity_names: list[str], max_results: int = 20
    ) -> list[str]:
        """Return entity names that co-occur with any of *entity_names*."""


class PostgresGraphStore(GraphStore):
    """GraphStore backed by the existing PostgreSQL entities tables."""

    def __init__(self, db: Any) -> None:
        self._db = db

    def upsert_entity(self, name: str, entity_type: str) -> str:
        return self._db.upsert_entity(name, entity_type)

    def insert_relation(
        self,
        source_id: str,
        target_id: str,
        doc_id: int,
        chunk_id: int,
        relation: str = 'mentioned_with',
    ) -> None:
        self._db.insert_entity_relation(source_id, target_id, doc_id, chunk_id, relation)

    def get_related_entity_names(
        self, entity_names: list[str], max_results: int = 20
    ) -> list[str]:
        return self._db.get_related_entity_names(entity_names, max_results=max_results)


class KuzuGraphStore(GraphStore):
    """GraphStore backed by Kuzu embedded graph database.

    Requires ``kuzu>=0.6.0``.  Raises ImportError at instantiation if not
    installed.

    Kuzu schema:
        Node table: Entity {id STRING PK, name STRING, type STRING, doc_count INT64}
        Rel  table: CoOccursWith {doc_id INT64, chunk_id INT64, relation STRING, weight DOUBLE}
    """

    def __init__(self, db_path: str) -> None:
        try:
            import kuzu  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "kuzu is required for GRAPH_BACKEND=kuzu. "
                "Install with: pip install kuzu>=0.6.0"
            ) from exc

        self._kuzu = kuzu
        self._db = kuzu.Database(db_path)
        self._conn = kuzu.Connection(self._db)
        self._ensure_schema()
        logger.info(f"[KuzuGraphStore] Opened at {db_path}")

    def _ensure_schema(self) -> None:
        """Create node/rel tables if they don't exist."""
        try:
            self._conn.execute(
                "CREATE NODE TABLE IF NOT EXISTS Entity("
                "id STRING, name STRING, type STRING, doc_count INT64, "
                "PRIMARY KEY(id))"
            )
            self._conn.execute(
                "CREATE REL TABLE IF NOT EXISTS CoOccursWith("
                "FROM Entity TO Entity, "
                "doc_id INT64, chunk_id INT64, relation STRING, weight DOUBLE)"
            )
        except Exception as exc:
            logger.warning(f"[KuzuGraphStore] Schema init warning: {exc}")

    def upsert_entity(self, name: str, entity_type: str) -> str:
        import hashlib
        entity_id = hashlib.sha256(f"{name}::{entity_type}".encode()).hexdigest()[:32]
        try:
            # kuzu's execute() is typed as QueryResult | list[QueryResult] (the list
            # variant only occurs for multi-statement scripts, never for a single
            # parameterized query like this one) and get_next()'s row shape isn't
            # precisely stubbed — treat both as Any rather than assert a shape we
            # can't verify against the real kuzu package in this environment.
            result: Any = self._conn.execute(
                "MATCH (e:Entity {id: $id}) RETURN e.doc_count",
                {"id": entity_id},
            )
            if result.has_next():
                row: Any = result.get_next()
                new_count = (row[0] or 0) + 1
                self._conn.execute(
                    "MATCH (e:Entity {id: $id}) SET e.doc_count = $count",
                    {"id": entity_id, "count": new_count},
                )
            else:
                self._conn.execute(
                    "CREATE (e:Entity {id: $id, name: $name, type: $type, doc_count: 1})",
                    {"id": entity_id, "name": name[:255], "type": entity_type[:50]},
                )
        except Exception as exc:
            logger.debug(f"[KuzuGraphStore] upsert_entity failed for {name!r}: {exc}")
        return entity_id

    def insert_relation(
        self,
        source_id: str,
        target_id: str,
        doc_id: int,
        chunk_id: int,
        relation: str = 'mentioned_with',
    ) -> None:
        try:
            self._conn.execute(
                "MATCH (a:Entity {id: $src}), (b:Entity {id: $tgt}) "
                "CREATE (a)-[:CoOccursWith {doc_id: $doc_id, chunk_id: $chunk_id, "
                "relation: $relation, weight: 1.0}]->(b)",
                {"src": source_id, "tgt": target_id, "doc_id": doc_id,
                 "chunk_id": chunk_id, "relation": relation},
            )
        except Exception as exc:
            logger.debug(f"[KuzuGraphStore] insert_relation failed: {exc}")

    def get_related_entity_names(
        self, entity_names: list[str], max_results: int = 20
    ) -> list[str]:
        if not entity_names:
            return []
        related: list[str] = []
        try:
            for name in entity_names:
                result: Any = self._conn.execute(
                    "MATCH (a:Entity {name: $name})-[:CoOccursWith]-(b:Entity) "
                    "WHERE b.name <> $name "
                    "RETURN DISTINCT b.name LIMIT $limit",
                    {"name": name, "limit": max_results},
                )
                while result.has_next():
                    row: Any = result.get_next()
                    if row[0] and row[0] not in entity_names:
                        related.append(row[0])
        except Exception as exc:
            logger.debug(f"[KuzuGraphStore] get_related_entity_names failed: {exc}")
        return related[:max_results]


def create_graph_store(db: Any) -> GraphStore:
    """Factory: returns the configured GraphStore instance.

    Uses ``config.GRAPH_BACKEND`` to select the implementation.
    Falls back to PostgresGraphStore on any Kuzu error.
    """
    from .. import config

    if config.GRAPH_BACKEND == 'kuzu':
        if not config.KUZU_DB_PATH:
            logger.warning("[GraphStore] KUZU_DB_PATH not set, falling back to postgres")
        else:
            try:
                store = KuzuGraphStore(config.KUZU_DB_PATH)
                logger.info("[GraphStore] Using Kuzu backend")
                return store
            except Exception as exc:
                logger.warning(f"[GraphStore] Kuzu init failed, falling back to postgres: {exc}")

    return PostgresGraphStore(db)
