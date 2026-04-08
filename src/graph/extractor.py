"""
Entity Extractor
================

Extracts named entities from document chunks using spaCy and persists them
in the ``entities`` / ``entity_relations`` tables.

spaCy and an NLP model are optional.  If neither is available the extractor
is a safe no-op — the rest of the ingest pipeline is unaffected.
"""

from __future__ import annotations

import itertools
from typing import Any

from ..utils.logging_config import get_logger

logger = get_logger(__name__)

# ── spaCy bootstrap ───────────────────────────────────────────────────────────
# Try small model first, fall back to blank English pipeline as last resort so
# we can always return an empty entity list rather than crashing.

_nlp = None
_NLP_UNAVAILABLE_LOGGED = False
_PREFERRED_MODELS = ["en_core_web_sm", "en_core_web_md", "en_core_web_trf"]


def _get_nlp():
    """Lazily load spaCy NLP pipeline; returns None if unavailable."""
    global _nlp, _NLP_UNAVAILABLE_LOGGED
    if _nlp is not None:
        return _nlp
    try:
        import spacy
        for model in _PREFERRED_MODELS:
            try:
                _nlp = spacy.load(model, disable=["parser", "tagger", "lemmatizer"])
                logger.info(f"[GraphRAG] spaCy NLP loaded: {model}")
                return _nlp
            except OSError:
                continue
        if not _NLP_UNAVAILABLE_LOGGED:
            logger.warning(
                "[GraphRAG] No spaCy model found. "
                "Run: python -m spacy download en_core_web_sm"
            )
            _NLP_UNAVAILABLE_LOGGED = True
    except ImportError:
        if not _NLP_UNAVAILABLE_LOGGED:
            logger.info(
                "[GraphRAG] spaCy not installed — entity extraction disabled. "
                "Install with: pip install 'spacy>=3.7.0'"
            )
            _NLP_UNAVAILABLE_LOGGED = True
    return None


# Entity types worth storing
_KEEP_TYPES = {"PERSON", "ORG", "GPE", "PRODUCT", "WORK_OF_ART", "LAW", "EVENT", "FAC"}


class EntityExtractor:
    """Extract entities from ingested document chunks and persist to the graph DB."""

    def extract_for_document(
        self,
        doc_id: int,
        chunks_data: list[dict[str, Any]],
        db: Any,
    ) -> int:
        """
        Extract entities from all chunks of a document.

        Args:
            doc_id: Database ID of the parent document.
            chunks_data: List of chunk dicts as stored by insert_chunks_batch.
            db: Database instance.

        Returns:
            Number of (entity, chunk) pairs processed.
        """
        nlp = _get_nlp()
        if nlp is None:
            return 0

        total = 0
        for chunk in chunks_data:
            chunk_id = chunk.get('chunk_id')
            text = chunk.get('chunk_text', '')
            if not text or not chunk_id:
                continue
            try:
                entities = self._extract_entities(nlp, text)
                if entities:
                    self._persist_entities(entities, doc_id, chunk_id, db)
                    total += len(entities)
            except Exception as exc:
                logger.debug(f"[GraphRAG] Chunk {chunk_id} extraction failed: {exc}")

        logger.debug(f"[GraphRAG] doc {doc_id}: processed {total} entity occurrences")
        return total

    @staticmethod
    def _extract_entities(nlp, text: str) -> list[tuple[str, str]]:
        """Return deduplicated (name, type) pairs from the text."""
        doc = nlp(text[:10_000])  # cap at 10k chars per chunk
        seen: set[tuple[str, str]] = set()
        for ent in doc.ents:
            if ent.label_ not in _KEEP_TYPES:
                continue
            name = ent.text.strip()
            if len(name) < 2 or len(name) > 200:
                continue
            pair = (name, ent.label_)
            seen.add(pair)
        return list(seen)

    @staticmethod
    def _persist_entities(
        entities: list[tuple[str, str]],
        doc_id: int,
        chunk_id: int,
        db: Any,
    ) -> None:
        """Upsert entities and create co-occurrence pairs."""
        entity_ids: list[str] = []
        for name, etype in entities:
            try:
                eid = db.upsert_entity(name, etype)
                entity_ids.append(eid)
            except Exception as exc:
                logger.debug(f"[GraphRAG] upsert_entity failed for {name!r}: {exc}")

        # Create co-occurrence relations for all pairs in this chunk
        for eid_a, eid_b in itertools.combinations(entity_ids, 2):
            try:
                db.insert_entity_relation(eid_a, eid_b, doc_id, chunk_id)
            except Exception as exc:
                logger.debug(f"[GraphRAG] relation insert failed: {exc}")
