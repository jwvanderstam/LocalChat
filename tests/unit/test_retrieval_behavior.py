"""
Tests for hybrid scoring and deduplication in RetrievalMixin.

These tests verify the scoring math and deduplication window logic as
standalone unit tests — no database or Ollama required.
"""

import os
import pytest
from unittest.mock import MagicMock, patch

# src/config.py raises at import time if PG_PASSWORD is missing.
# Set a test sentinel so collection succeeds without a real database.
os.environ.setdefault("PG_PASSWORD", "test-sentinel")

from src.rag.retrieval import RetrievalMixin


# ---------------------------------------------------------------------------
# Minimal concrete class for testing the mixin
# ---------------------------------------------------------------------------

class Retriever(RetrievalMixin):
    pass


@pytest.fixture
def retriever():
    return Retriever()


def _result(filename, chunk_index, semantic_score=0.8, text="some chunk content here"):
    return {
        "chunk_text": text,
        "filename": filename,
        "chunk_index": chunk_index,
        "semantic_score": semantic_score,
        "bm25_score": 0.0,
        "combined_score": semantic_score,
        "metadata": {},
    }


def _results_dict(*args):
    """Build the dict[chunk_id → result] structure used by _apply_hybrid_scoring."""
    d = {}
    for r in args:
        d[f"{r['filename']}:{r['chunk_index']}"] = r
    return d


# ---------------------------------------------------------------------------
# _apply_hybrid_scoring
# ---------------------------------------------------------------------------

class TestApplyHybridScoring:
    def test_skipped_when_hybrid_disabled(self, retriever):
        """BM25 computation is not called when use_hybrid_search=False."""
        results = _results_dict(
            _result("a.pdf", 0, 0.9),
            _result("b.pdf", 0, 0.7),
        )
        with patch.object(retriever, "_compute_bm25_scores") as mock_bm25:
            retriever._apply_hybrid_scoring(results, "query", use_hybrid_search=False)
        mock_bm25.assert_not_called()

    def test_skipped_with_single_result(self, retriever):
        """BM25 computation is not called when there is only one result."""
        results = _results_dict(_result("a.pdf", 0, 0.9))
        with patch.object(retriever, "_compute_bm25_scores") as mock_bm25:
            retriever._apply_hybrid_scoring(results, "query", use_hybrid_search=True)
        mock_bm25.assert_not_called()

    def test_combined_score_blends_semantic_and_bm25_at_configured_weights(self, retriever):
        """combined_score = SIMILARITY_WEIGHT * semantic + (BM25_WEIGHT + KEYWORD_WEIGHT) * bm25."""
        r_a = _result("a.pdf", 0, semantic_score=0.8)
        r_b = _result("b.pdf", 0, semantic_score=0.6)
        results = _results_dict(r_a, r_b)
        bm25_scores = {"a.pdf:0": 0.5, "b.pdf:0": 1.0}

        with patch.object(retriever, "_compute_bm25_scores", return_value=bm25_scores):
            with patch("src.rag.retrieval.config") as cfg:
                cfg.SIMILARITY_WEIGHT = 0.7
                cfg.BM25_WEIGHT = 0.2
                cfg.KEYWORD_WEIGHT = 0.1
                retriever._apply_hybrid_scoring(results, "query", use_hybrid_search=True)

        expected_a = 0.7 * 0.8 + 0.3 * 0.5
        expected_b = 0.7 * 0.6 + 0.3 * 1.0
        assert abs(results["a.pdf:0"]["combined_score"] - expected_a) < 1e-9
        assert abs(results["b.pdf:0"]["combined_score"] - expected_b) < 1e-9

    def test_bm25_score_is_stored_on_each_result(self, retriever):
        """The per-result bm25_score field must be updated, not just combined_score."""
        r_a = _result("a.pdf", 0, 0.8)
        r_b = _result("b.pdf", 0, 0.6)
        results = _results_dict(r_a, r_b)
        bm25_scores = {"a.pdf:0": 0.4, "b.pdf:0": 0.9}

        with patch.object(retriever, "_compute_bm25_scores", return_value=bm25_scores):
            with patch("src.rag.retrieval.config") as cfg:
                cfg.SIMILARITY_WEIGHT = 0.7
                cfg.BM25_WEIGHT = 0.2
                cfg.KEYWORD_WEIGHT = 0.1
                retriever._apply_hybrid_scoring(results, "query", use_hybrid_search=True)

        assert results["a.pdf:0"]["bm25_score"] == pytest.approx(0.4)
        assert results["b.pdf:0"]["bm25_score"] == pytest.approx(0.9)

    def test_missing_bm25_score_treated_as_zero(self, retriever):
        """A chunk absent from bm25_scores gets bm25_score=0 and combined=semantic only."""
        r = _result("a.pdf", 0, semantic_score=0.75)
        results = _results_dict(r)
        r2 = _result("b.pdf", 0, semantic_score=0.5)
        results.update(_results_dict(r2))

        # bm25_scores only covers one of the two chunks
        with patch.object(retriever, "_compute_bm25_scores", return_value={"a.pdf:0": 0.6}):
            with patch("src.rag.retrieval.config") as cfg:
                cfg.SIMILARITY_WEIGHT = 0.7
                cfg.BM25_WEIGHT = 0.2
                cfg.KEYWORD_WEIGHT = 0.1
                retriever._apply_hybrid_scoring(results, "query", use_hybrid_search=True)

        # b.pdf:0 has no BM25 score — contribution should be 0
        expected_b = 0.7 * 0.5 + 0.3 * 0.0
        assert abs(results["b.pdf:0"]["combined_score"] - expected_b) < 1e-9


# ---------------------------------------------------------------------------
# _deduplicate_results
# ---------------------------------------------------------------------------

class TestDeduplicateResults:
    def test_immediately_adjacent_chunk_is_removed(self, retriever):
        """Chunk at index N+1 in the same file as chunk N must be deduplicated."""
        results = [_result("doc.pdf", 0), _result("doc.pdf", 1)]
        deduped = retriever._deduplicate_results(results)
        assert len(deduped) == 1
        assert deduped[0]["chunk_index"] == 0

    def test_chunks_within_window_of_2_are_removed(self, retriever):
        """Chunks at indices 0, 1, 2 all fall within the deduplication window."""
        results = [_result("doc.pdf", i) for i in range(3)]
        deduped = retriever._deduplicate_results(results)
        assert len(deduped) == 1

    def test_chunks_outside_window_are_kept(self, retriever):
        """Chunk at index 5 is more than 2 positions away from chunk 0 — both kept."""
        results = [_result("doc.pdf", 0), _result("doc.pdf", 5)]
        deduped = retriever._deduplicate_results(results)
        assert len(deduped) == 2

    def test_same_index_different_files_both_kept(self, retriever):
        """Chunk index 0 from two different files are completely independent."""
        results = [_result("a.pdf", 0), _result("b.pdf", 0)]
        deduped = retriever._deduplicate_results(results)
        assert len(deduped) == 2

    def test_empty_input_returns_empty(self, retriever):
        assert retriever._deduplicate_results([]) == []

    def test_single_result_is_passed_through_unchanged(self, retriever):
        results = [_result("doc.pdf", 3)]
        assert retriever._deduplicate_results(results) == results

    def test_interleaved_files_deduplicated_independently(self, retriever):
        """Deduplication state is per-file; chunks from other files don't interfere."""
        results = [
            _result("a.pdf", 0),
            _result("b.pdf", 0),  # same index, different file — kept
            _result("a.pdf", 1),  # adjacent to a.pdf:0 — removed
            _result("b.pdf", 5),  # far from b.pdf:0 — kept
        ]
        deduped = retriever._deduplicate_results(results)
        filenames_and_indices = [(r["filename"], r["chunk_index"]) for r in deduped]

        assert ("a.pdf", 0) in filenames_and_indices
        assert ("b.pdf", 0) in filenames_and_indices
        assert ("a.pdf", 1) not in filenames_and_indices
        assert ("b.pdf", 5) in filenames_and_indices
