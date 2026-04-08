"""
Query Expander
==============

Uses the entity knowledge graph to expand BM25 query terms.

Given a user query, extracts named entities with spaCy, looks up
1-hop co-occurrences from the ``entity_relations`` table, and returns
additional entity names to include in BM25 scoring.
"""

from __future__ import annotations

from typing import Any

from ..utils.logging_config import get_logger
from .extractor import _KEEP_TYPES, _get_nlp

logger = get_logger(__name__)


class QueryExpander:
    """Expand a query string with graph-neighbour entity names."""

    def expand(self, query: str, db: Any, max_extra: int = 5) -> list[str]:
        """
        Return additional entity-name strings for BM25 expansion.

        Args:
            query: Raw user query.
            db: Database instance.
            max_extra: Maximum additional names to return.

        Returns:
            List of extra entity name strings (may be empty).
        """
        nlp = _get_nlp()
        if nlp is None or not db.is_connected:
            return []

        try:
            doc = nlp(query[:2000])
            query_entities = [
                ent.text.strip()
                for ent in doc.ents
                if ent.label_ in _KEEP_TYPES and 2 <= len(ent.text.strip()) <= 200
            ]
        except Exception as exc:
            logger.debug(f"[GraphRAG] Query entity extraction failed: {exc}")
            return []

        if not query_entities:
            return []

        try:
            related = db.get_related_entity_names(query_entities, max_results=max_extra)
            if related:
                logger.info(f"[GraphRAG] Expanded query with {len(related)} entity terms")
            return related
        except Exception as exc:
            logger.debug(f"[GraphRAG] Graph expansion failed: {exc}")
            return []
