"""`DocumentProcessor._extract_entities` — the optional GraphRAG side-effect.

Extracted from `ingest_document` to bring that function under the cognitive
complexity limit. Extracting it also made these lines *new* code, which is how
they turned out never to have been covered: GraphRAG is disabled in every test
environment, so only the early return had ever run.

The property that matters is the one the extraction preserved: this never fails
an ingest. A document that is indexed and searchable must not be reported as
failed because entity extraction fell over.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.rag.processor import DocumentProcessor

pytestmark = pytest.mark.unit

_CHUNKS = [
    {'chunk_text': 'first chunk'},
    {'chunk_text': 'second chunk'},
]


@pytest.fixture
def processor():
    return DocumentProcessor(db=MagicMock(), ollama_client=MagicMock())


class TestDisabled:
    def test_nothing_is_extracted_when_graphrag_is_off(self, processor):
        """The default in every deployment that has not opted in."""
        with patch('src.rag.processor.config.GRAPH_RAG_ENABLED', False), \
             patch('src.graph.extractor.EntityExtractor') as extractor:
            processor._extract_entities(7, [1, 2], _CHUNKS)

        extractor.assert_not_called()


class TestEnabled:
    def test_chunk_ids_are_paired_with_their_text(self, processor):
        """Two chunks, not one: the pairing is a zip, and a single-element list
        cannot tell a correct zip from one that drops or repeats an id."""
        with patch('src.rag.processor.config.GRAPH_RAG_ENABLED', True), \
             patch('src.graph.extractor.EntityExtractor') as extractor:
            processor._extract_entities(7, [101, 102], _CHUNKS)

        doc_id, chunks_with_ids, _db = extractor.return_value.extract_for_document.call_args[0]
        assert doc_id == 7
        assert chunks_with_ids == [
            {'chunk_id': 101, 'chunk_text': 'first chunk'},
            {'chunk_id': 102, 'chunk_text': 'second chunk'},
        ]

    def test_surplus_chunks_without_an_id_are_dropped(self, processor):
        """`zip(..., strict=False)` is deliberate — insert_chunks_batch can return
        fewer ids than chunks, and truncating beats raising inside a best-effort
        step. Asserted so the flag cannot flip to strict unnoticed."""
        with patch('src.rag.processor.config.GRAPH_RAG_ENABLED', True), \
             patch('src.graph.extractor.EntityExtractor') as extractor:
            processor._extract_entities(7, [101], _CHUNKS)

        _, chunks_with_ids, _ = extractor.return_value.extract_for_document.call_args[0]
        assert chunks_with_ids == [{'chunk_id': 101, 'chunk_text': 'first chunk'}]


class TestFailureIsNonFatal:
    def test_an_extractor_that_raises_does_not_propagate(self, processor):
        """The whole reason this is wrapped. An ingest that stored the document and
        its chunks must not be reported as failed because this step fell over."""
        with patch('src.rag.processor.config.GRAPH_RAG_ENABLED', True), \
             patch('src.graph.extractor.EntityExtractor',
                   side_effect=RuntimeError("spaCy model missing")):
            processor._extract_entities(7, [101, 102], _CHUNKS)

    def test_the_failure_is_logged_as_a_warning(self, processor, caplog):
        """Silently swallowing it would make a half-built graph invisible."""
        with patch('src.rag.processor.config.GRAPH_RAG_ENABLED', True), \
             patch('src.graph.extractor.EntityExtractor',
                   side_effect=RuntimeError("spaCy model missing")):
            processor._extract_entities(7, [101], _CHUNKS)

        assert "spaCy model missing" in caplog.text
