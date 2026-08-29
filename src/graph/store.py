"""
Graph Store
===========

Abstraction layer for the GraphRAG knowledge graph backend.

``GraphStore`` is a protocol/ABC defining the three operations needed by
EntityExtractor and QueryExpander.  One implementation is provided:

- ``PostgresGraphStore``  — delegates to the existing ``entities`` /
  ``entity_relations`` PostgreSQL tables (no extra deps).

The ABC is kept rather than inlined: it is what lets a second backend be
added without touching either caller. A Kuzu implementation lived here
until DEL-1a removed it, unused and behind a config flag.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


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


def create_graph_store(db: Any) -> GraphStore:
    """Factory: returns the GraphStore instance backing GraphRAG."""
    return PostgresGraphStore(db)
