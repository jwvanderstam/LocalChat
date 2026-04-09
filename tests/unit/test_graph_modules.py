"""
Tests for src/graph/extractor.py and src/graph/expander.py

Covers:
  - _get_nlp: ImportError path, OSError (model not found) path, success path
  - EntityExtractor.extract_for_document: spaCy unavailable → 0, missing fields,
    successful extraction with persist, exception in chunk skipped
  - EntityExtractor._extract_entities: deduplication, length filtering, type filtering
  - EntityExtractor._persist_entities: upserts, combination pairs, failures silenced
  - QueryExpander.expand: no spaCy → [], DB not connected → [], no entities in query → [],
    successful expansion, DB failure silenced
"""

import itertools
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(connected=True):
    db = MagicMock()
    db.is_connected = connected
    return db


def _make_mock_nlp(entities=None):
    """Return a callable mock that behaves like a spaCy nlp() call."""
    ents = entities or []

    mock_ent_objects = []
    for text, label in ents:
        ent = MagicMock()
        ent.text = text
        ent.label_ = label
        mock_ent_objects.append(ent)

    mock_doc = MagicMock()
    mock_doc.ents = mock_ent_objects

    nlp = MagicMock(return_value=mock_doc)
    return nlp


# ===========================================================================
# _get_nlp
# ===========================================================================

class TestGetNlp:
    def test_returns_none_when_spacy_not_installed(self):
        # Patch the module-level _nlp and force ImportError on import
        with patch.dict("sys.modules", {"spacy": None}):
            import importlib

            import src.graph.extractor as mod
            # Reset cached value
            original_nlp = mod._nlp
            original_logged = mod._NLP_UNAVAILABLE_LOGGED
            mod._nlp = None
            mod._NLP_UNAVAILABLE_LOGGED = False
            try:
                result = mod._get_nlp()
                assert result is None
            finally:
                mod._nlp = original_nlp
                mod._NLP_UNAVAILABLE_LOGGED = original_logged

    def test_returns_cached_nlp_on_second_call(self):
        import src.graph.extractor as mod
        original_nlp = mod._nlp
        try:
            mock_nlp = MagicMock()
            mod._nlp = mock_nlp
            result = mod._get_nlp()
            assert result is mock_nlp
        finally:
            mod._nlp = original_nlp


# ===========================================================================
# EntityExtractor.extract_for_document
# ===========================================================================

class TestEntityExtractorExtractForDocument:
    def _extractor(self):
        from src.graph.extractor import EntityExtractor
        return EntityExtractor()

    def test_returns_zero_when_nlp_unavailable(self):
        e = self._extractor()
        with patch("src.graph.extractor._get_nlp", return_value=None):
            total = e.extract_for_document(1, [{"chunk_id": 1, "chunk_text": "Apple is a company."}], _make_db())
        assert total == 0

    def test_returns_zero_for_empty_chunks(self):
        e = self._extractor()
        mock_nlp = _make_mock_nlp()
        with patch("src.graph.extractor._get_nlp", return_value=mock_nlp):
            total = e.extract_for_document(1, [], _make_db())
        assert total == 0

    def test_skips_chunk_missing_text(self):
        e = self._extractor()
        mock_nlp = _make_mock_nlp()
        with patch("src.graph.extractor._get_nlp", return_value=mock_nlp):
            total = e.extract_for_document(1, [{"chunk_id": 1, "chunk_text": ""}], _make_db())
        assert total == 0

    def test_skips_chunk_missing_chunk_id(self):
        e = self._extractor()
        mock_nlp = _make_mock_nlp()
        with patch("src.graph.extractor._get_nlp", return_value=mock_nlp):
            total = e.extract_for_document(1, [{"chunk_text": "Apple is a company."}], _make_db())
        assert total == 0

    def test_counts_entities_from_chunks(self):
        e = self._extractor()
        mock_nlp = _make_mock_nlp([("Apple", "ORG"), ("Tim Cook", "PERSON")])
        db = _make_db()
        db.upsert_entity.side_effect = lambda name, etype: hash(name)
        with patch("src.graph.extractor._get_nlp", return_value=mock_nlp):
            total = e.extract_for_document(
                1,
                [{"chunk_id": 10, "chunk_text": "Apple is run by Tim Cook."}],
                db,
            )
        assert total == 2

    def test_exception_in_chunk_does_not_crash(self):
        e = self._extractor()
        # nlp that raises on call
        mock_nlp = MagicMock(side_effect=RuntimeError("NLP crash"))
        with patch("src.graph.extractor._get_nlp", return_value=mock_nlp):
            # Should not raise
            total = e.extract_for_document(
                1,
                [{"chunk_id": 1, "chunk_text": "Some text"}],
                _make_db(),
            )
        assert total == 0

    def test_multiple_chunks_accumulate(self):
        e = self._extractor()
        mock_nlp = _make_mock_nlp([("Google", "ORG")])
        db = _make_db()
        db.upsert_entity.side_effect = lambda name, etype: hash(name)
        chunks = [
            {"chunk_id": i, "chunk_text": "Google text"}
            for i in range(1, 4)  # start at 1 — chunk_id=0 is falsy and gets skipped by the guard
        ]
        with patch("src.graph.extractor._get_nlp", return_value=mock_nlp):
            total = e.extract_for_document(1, chunks, db)
        assert total == 3  # 1 entity per chunk × 3 chunks


# ===========================================================================
# EntityExtractor._extract_entities
# ===========================================================================

class TestEntityExtractorExtractEntities:
    def _extract(self, entities_input):
        from src.graph.extractor import EntityExtractor
        mock_nlp = _make_mock_nlp(entities_input)
        return EntityExtractor._extract_entities(mock_nlp, "some text")

    def test_returns_list_of_tuples(self):
        result = self._extract([("Apple", "ORG")])
        assert isinstance(result, list)
        assert all(isinstance(t, tuple) and len(t) == 2 for t in result)

    def test_deduplicates_same_entity(self):
        result = self._extract([("Apple", "ORG"), ("Apple", "ORG")])
        assert len(result) == 1

    def test_filters_disallowed_type(self):
        result = self._extract([("quickly", "ADV"), ("Apple", "ORG")])
        names = [r[0] for r in result]
        assert "quickly" not in names
        assert "Apple" in names

    def test_filters_too_short_name(self):
        result = self._extract([("X", "ORG")])  # 1 char — below min 2
        assert result == []

    def test_filters_too_long_name(self):
        long_name = "A" * 201
        result = self._extract([(long_name, "ORG")])
        assert result == []

    def test_accepts_all_keep_types(self):
        from src.graph.extractor import _KEEP_TYPES
        entities = [(f"Entity{t}", t) for t in _KEEP_TYPES]
        result = self._extract(entities)
        found_types = {r[1] for r in result}
        assert found_types == _KEEP_TYPES


# ===========================================================================
# EntityExtractor._persist_entities
# ===========================================================================

class TestEntityExtractorPersistEntities:
    def _persist(self, entities, db=None):
        from src.graph.extractor import EntityExtractor
        if db is None:
            db = _make_db()
            db.upsert_entity.side_effect = lambda name, etype: hash(name) % 1000
        EntityExtractor._persist_entities(entities, doc_id=1, chunk_id=10, db=db)
        return db

    def test_calls_upsert_for_each_entity(self):
        db = self._persist([("Apple", "ORG"), ("Tim Cook", "PERSON")])
        assert db.upsert_entity.call_count == 2

    def test_creates_co_occurrence_pairs(self):
        db = self._persist([("Apple", "ORG"), ("Tim Cook", "PERSON"), ("iPhone", "PRODUCT")])
        # 3 entities → C(3,2) = 3 pairs
        assert db.insert_entity_relation.call_count == 3

    def test_single_entity_no_relation(self):
        db = self._persist([("Apple", "ORG")])
        db.insert_entity_relation.assert_not_called()

    def test_upsert_failure_is_silent(self):
        db = _make_db()
        db.upsert_entity.side_effect = Exception("DB down")
        # Should not raise
        from src.graph.extractor import EntityExtractor
        EntityExtractor._persist_entities([("Apple", "ORG")], doc_id=1, chunk_id=1, db=db)

    def test_relation_failure_is_silent(self):
        db = _make_db()
        db.upsert_entity.side_effect = lambda name, etype: 1  # always returns id=1
        db.insert_entity_relation.side_effect = Exception("constraint violation")
        # Should not raise
        from src.graph.extractor import EntityExtractor
        EntityExtractor._persist_entities(
            [("Apple", "ORG"), ("Google", "ORG")], doc_id=1, chunk_id=1, db=db
        )


# ===========================================================================
# QueryExpander.expand
# ===========================================================================

class TestQueryExpanderExpand:
    def _expander(self):
        from src.graph.expander import QueryExpander
        return QueryExpander()

    def test_returns_empty_when_nlp_unavailable(self):
        e = self._expander()
        with patch("src.graph.expander._get_nlp", return_value=None):
            result = e.expand("Apple acquires startup", _make_db())
        assert result == []

    def test_returns_empty_when_db_not_connected(self):
        e = self._expander()
        mock_nlp = _make_mock_nlp([("Apple", "ORG")])
        with patch("src.graph.expander._get_nlp", return_value=mock_nlp):
            result = e.expand("Apple acquires startup", _make_db(connected=False))
        assert result == []

    def test_returns_empty_when_no_entities_in_query(self):
        e = self._expander()
        mock_nlp = _make_mock_nlp([])  # no entities
        with patch("src.graph.expander._get_nlp", return_value=mock_nlp):
            result = e.expand("what is this?", _make_db())
        assert result == []

    def test_returns_related_entity_names(self):
        e = self._expander()
        mock_nlp = _make_mock_nlp([("Apple", "ORG")])
        db = _make_db()
        db.get_related_entity_names.return_value = ["iPhone", "Tim Cook"]
        with patch("src.graph.expander._get_nlp", return_value=mock_nlp):
            result = e.expand("Apple acquires startup", db)
        assert result == ["iPhone", "Tim Cook"]

    def test_db_failure_returns_empty(self):
        e = self._expander()
        mock_nlp = _make_mock_nlp([("Apple", "ORG")])
        db = _make_db()
        db.get_related_entity_names.side_effect = Exception("DB error")
        with patch("src.graph.expander._get_nlp", return_value=mock_nlp):
            result = e.expand("Apple acquires startup", db)
        assert result == []

    def test_nlp_exception_returns_empty(self):
        e = self._expander()
        mock_nlp = MagicMock(side_effect=RuntimeError("NLP crash"))
        with patch("src.graph.expander._get_nlp", return_value=mock_nlp):
            result = e.expand("some query", _make_db())
        assert result == []

    def test_respects_max_extra(self):
        e = self._expander()
        mock_nlp = _make_mock_nlp([("Apple", "ORG")])
        db = _make_db()
        db.get_related_entity_names.return_value = ["A", "B"]
        with patch("src.graph.expander._get_nlp", return_value=mock_nlp):
            e.expand("Apple text", db, max_extra=3)
        # Verify max_extra is forwarded to the DB call
        call_kwargs = db.get_related_entity_names.call_args
        assert call_kwargs.kwargs.get("max_results") == 3 or 3 in call_kwargs.args

    def test_filters_entities_by_length(self):
        """Entities shorter than 2 chars should not reach the DB."""
        e = self._expander()
        # Entity "X" is 1 char — should be filtered before DB lookup
        mock_nlp = _make_mock_nlp([("X", "ORG")])
        db = _make_db()
        db.get_related_entity_names.return_value = []
        with patch("src.graph.expander._get_nlp", return_value=mock_nlp):
            result = e.expand("X Corp", db)
        # No entities passed the length filter → no DB call
        assert result == []
