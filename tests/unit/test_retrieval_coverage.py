# -*- coding: utf-8 -*-
"""Additional coverage for rag/retrieval.py."""

import pytest
from unittest.mock import MagicMock, patch


def _make_retriever():
    from src.rag.retrieval import RetrievalMixin
    r = RetrievalMixin()
    return r


class TestFormatSingleChunk:
    def test_basic_chunk_formatting(self):
        r = _make_retriever()
        result = r._format_single_chunk("Some chunk text.", {})
        assert "[Passage]" in result
        assert "Some chunk text." in result

    def test_with_page_number(self):
        r = _make_retriever()
        result = r._format_single_chunk("Text.", {"page_number": 5})
        assert "p. 5" in result

    def test_with_short_section_title(self):
        r = _make_retriever()
        result = r._format_single_chunk("Text.", {"section_title": "Introduction"})
        assert "Introduction" in result

    def test_with_long_section_title_truncated(self):
        r = _make_retriever()
        long_title = "A" * 60
        result = r._format_single_chunk("Text.", {"section_title": long_title})
        assert "..." in result

    def test_ends_with_double_newline(self):
        r = _make_retriever()
        result = r._format_single_chunk("Text.", {})
        assert result.endswith("\n\n")


class TestApplyHybridScoring:
    def test_no_op_when_use_hybrid_false(self):
        r = _make_retriever()
        all_results = {
            'chunk1': {'text': 'python code', 'filename': 'a.pdf', 'chunk_index': 0, 'similarity': 0.5},
            'chunk2': {'text': 'unrelated', 'filename': 'b.pdf', 'chunk_index': 1, 'similarity': 0.8},
        }
        r._apply_hybrid_scoring(all_results, 'python', use_hybrid_search=False)
        # no exception, dict unchanged
        assert len(all_results) == 2

    def test_no_op_with_single_result(self):
        r = _make_retriever()
        all_results = {
            'chunk1': {'text': 'text', 'filename': 'a.pdf', 'chunk_index': 0, 'similarity': 0.5},
        }
        r._apply_hybrid_scoring(all_results, 'text', use_hybrid_search=True)
        assert len(all_results) == 1

    def test_hybrid_scoring_with_multiple_results(self):
        r = _make_retriever()
        all_results = {
            'chunk1': {'chunk_text': 'python programming language', 'filename': 'a.pdf', 'chunk_index': 0, 'semantic_score': 0.5},
            'chunk2': {'chunk_text': 'unrelated topic here', 'filename': 'b.pdf', 'chunk_index': 1, 'semantic_score': 0.8},
        }
        r._apply_hybrid_scoring(all_results, 'python', use_hybrid_search=True)
        assert 'combined_score' in all_results['chunk1']
        assert 'bm25_score' in all_results['chunk2']


class TestDeduplicateResults:
    def test_removes_adjacent_chunk_duplicates(self):
        r = _make_retriever()
        results = [
            {'filename': 'doc.pdf', 'chunk_index': 0, 'text': 'a', 'similarity': 0.9},
            {'filename': 'doc.pdf', 'chunk_index': 1, 'text': 'b', 'similarity': 0.8},
            {'filename': 'doc.pdf', 'chunk_index': 5, 'text': 'c', 'similarity': 0.7},
        ]
        deduped = r._deduplicate_results(results)
        # chunk 0 and 1 are adjacent (distance=1 ≤ 2), so chunk 1 should be deduped
        assert len(deduped) <= 3

    def test_preserves_non_adjacent_results(self):
        r = _make_retriever()
        results = [
            {'filename': 'doc.pdf', 'chunk_index': 0, 'text': 'a', 'similarity': 0.9},
            {'filename': 'doc.pdf', 'chunk_index': 10, 'text': 'b', 'similarity': 0.8},
            {'filename': 'other.pdf', 'chunk_index': 0, 'text': 'c', 'similarity': 0.7},
        ]
        deduped = r._deduplicate_results(results)
        assert len(deduped) == 3

    def test_empty_returns_empty(self):
        r = _make_retriever()
        assert r._deduplicate_results([]) == []


class TestFormatContextForLLM:
    def setup_method(self):
        self.r = _make_retriever()

    def test_empty_results_returns_empty_string(self):
        result = self.r.format_context_for_llm([])
        assert result == ""

    def test_formats_single_result(self):
        results = [("chunk text content here", "doc.pdf", 0, 0.9, {})]
        result = self.r.format_context_for_llm(results)
        assert "chunk text content here" in result

    def test_respects_max_length(self):
        big_chunk = "word " * 1000
        results = [(big_chunk, "doc.pdf", i, 0.9 - i * 0.01, {}) for i in range(10)]
        result = self.r.format_context_for_llm(results, max_length=500)
        assert len(result) <= 1000  # some tolerance

    def test_groups_by_document(self):
        results = [
            ("chunk 1", "doc_a.pdf", 0, 0.9, {}),
            ("chunk 2", "doc_b.pdf", 0, 0.8, {}),
            ("chunk 3", "doc_a.pdf", 1, 0.7, {}),
        ]
        result = self.r.format_context_for_llm(results)
        assert "doc_a.pdf" in result
        assert "doc_b.pdf" in result


class TestRetrieveContext:
    def setup_method(self):
        self.r = _make_retriever()

    def test_returns_empty_when_no_embedding_model(self):
        with patch("src.rag.retrieval.ollama_client") as mock_client:
            mock_client.get_embedding_model.return_value = None
            result = self.r.retrieve_context("query")
            assert result == []

    def test_returns_empty_when_embedding_fails(self):
        with patch("src.rag.retrieval.ollama_client") as mock_client, \
             patch("src.rag.retrieval.db") as mock_db:
            mock_client.get_embedding_model.return_value = "model"
            mock_client.generate_embedding.return_value = (False, None)
            result = self.r.retrieve_context("query")
            assert result == []

    def test_returns_list_on_success(self):
        with patch("src.rag.retrieval.ollama_client") as mock_client, \
             patch("src.rag.retrieval.db") as mock_db:
            mock_client.get_embedding_model.return_value = "embed-model"
            mock_client.generate_embedding.return_value = (True, [0.1] * 768)
            mock_db.search_similar_chunks.return_value = []
            mock_db.is_connected = True
            result = self.r.retrieve_context("what is python?")
            assert isinstance(result, list)
