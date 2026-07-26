"""
Tests for hybrid scoring and deduplication in RetrievalMixin.

These tests verify the scoring math and deduplication window logic as
standalone unit tests — no database or Ollama required.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

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
        "lexical_score": 0.0,
        "combined_score": semantic_score,
        "metadata": {},
    }


def _results_dict(*args):
    """Build the dict[chunk_id → result] structure used by _merge_semantic_and_lexical."""
    d = {}
    for r in args:
        d[f"{r['filename']}:{r['chunk_index']}"] = r
    return d


def _semantic_row(filename, chunk_index, similarity, chunk_id=1, text="some chunk content here"):
    """Row shape returned by db.search_similar_chunks."""
    return (text, filename, chunk_index, similarity, {}, chunk_id)


def _lexical_row(filename, chunk_index, score, chunk_id=1, text="some chunk content here"):
    """Row shape returned by db.search_lexical_chunks."""
    return (text, filename, chunk_index, score, {}, chunk_id)


# ---------------------------------------------------------------------------
# _merge_semantic_and_lexical
# ---------------------------------------------------------------------------

class TestMergeSemanticAndLexical:
    def test_semantic_only_when_lexical_empty(self, retriever):
        """With no lexical results, combined_score stays exactly the semantic score
        (preserves non-hybrid ranking) — proves the blend is skipped, not applied
        with a zero lexical contribution."""
        semantic = [_semantic_row("a.pdf", 0, 0.8), _semantic_row("b.pdf", 0, 0.6)]

        merged = retriever._merge_semantic_and_lexical(semantic, [])

        assert merged["a.pdf:0"]["combined_score"] == 0.8
        assert merged["b.pdf:0"]["combined_score"] == 0.6

    def test_lexical_only_chunk_is_included(self, retriever):
        """A chunk found ONLY by lexical search (never returned by vector search
        at all) must survive into the merged set — this is the fix for hybrid
        search only ever reordering vector search's own candidates."""
        semantic = [_semantic_row("a.pdf", 0, 0.8)]
        lexical = [_lexical_row("rare-code.pdf", 3, 0.9)]

        merged = retriever._merge_semantic_and_lexical(semantic, lexical)

        assert "rare-code.pdf:3" in merged
        assert merged["rare-code.pdf:3"]["semantic_score"] == 0.0
        assert merged["rare-code.pdf:3"]["lexical_score"] == 0.9
        assert merged["rare-code.pdf:3"]["combined_score"] > 0.0

    def test_combined_score_blends_at_configured_semantic_weight(self, retriever):
        """combined_score = SEMANTIC_WEIGHT * semantic + (1 - SEMANTIC_WEIGHT) * lexical."""
        semantic = [_semantic_row("a.pdf", 0, 0.8), _semantic_row("b.pdf", 0, 0.6)]
        lexical = [_lexical_row("a.pdf", 0, 0.5), _lexical_row("b.pdf", 0, 1.0)]

        with patch("src.rag.retrieval.config") as cfg:
            cfg.app_state.get_rag_param.return_value = 0.7
            merged = retriever._merge_semantic_and_lexical(semantic, lexical)

        expected_a = 0.7 * 0.8 + 0.3 * 0.5
        expected_b = 0.7 * 0.6 + 0.3 * 1.0
        assert abs(merged["a.pdf:0"]["combined_score"] - expected_a) < 1e-9
        assert abs(merged["b.pdf:0"]["combined_score"] - expected_b) < 1e-9

    def test_chunk_in_both_arms_records_both_scores(self, retriever):
        """A chunk present in both result sets keeps its real semantic_score
        and gets lexical_score populated (not left at the semantic-only default)."""
        semantic = [_semantic_row("a.pdf", 0, 0.8)]
        lexical = [_lexical_row("a.pdf", 0, 0.4)]

        with patch("src.rag.retrieval.config") as cfg:
            cfg.app_state.get_rag_param.return_value = 0.7
            merged = retriever._merge_semantic_and_lexical(semantic, lexical)

        assert merged["a.pdf:0"]["semantic_score"] == 0.8
        assert merged["a.pdf:0"]["lexical_score"] == 0.4

    def test_semantic_only_chunk_gets_discounted_when_hybrid_active(self, retriever):
        """Once the lexical arm contributes anything, a chunk with NO lexical
        match must still go through the same blend formula (semantic_weight *
        semantic + 0), not keep its full undiluted semantic score — otherwise
        chunks with zero lexical evidence would rank artificially higher than
        chunks with some lexical evidence."""
        semantic = [_semantic_row("a.pdf", 0, 0.8), _semantic_row("b.pdf", 0, 0.8)]
        lexical = [_lexical_row("b.pdf", 0, 1.0)]  # only b.pdf:0 has a lexical match

        with patch("src.rag.retrieval.config") as cfg:
            cfg.app_state.get_rag_param.return_value = 0.7
            merged = retriever._merge_semantic_and_lexical(semantic, lexical)

        expected_a = 0.7 * 0.8 + 0.3 * 0.0
        assert abs(merged["a.pdf:0"]["combined_score"] - expected_a) < 1e-9


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


# ---------------------------------------------------------------------------
# _apply_cross_encoder
# ---------------------------------------------------------------------------

class TestApplyCrossEncoder:
    def test_reranker_reorders_chunks_by_cross_encoder_score(self, retriever):
        """Chunk with low vector-sim but high CE score must rank first after reranking."""
        chunk_b = _result("b.pdf", 0, semantic_score=0.9, text="chunk b text")
        chunk_a = _result("a.pdf", 0, semantic_score=0.3, text="chunk a text")
        # chunk_b starts first (higher combined_score=0.9 vs 0.3)
        deduped = [chunk_b, chunk_a]

        mock_reranker = MagicMock()
        mock_reranker.is_available.return_value = True
        # CE scores in input order: b=0.1 (low), a=0.9 (high)
        # With weight=0.5: b → 0.5*0.9 + 0.5*0.1 = 0.50; a → 0.5*0.3 + 0.5*0.9 = 0.60
        mock_reranker.score.return_value = [0.1, 0.9]

        with patch("src.rag.reranker.get_reranker", return_value=mock_reranker):
            with patch("src.rag.retrieval.config") as cfg:
                cfg.RERANKER_WEIGHT = 0.5
                result = retriever._apply_cross_encoder("test query", deduped)

        assert result[0]["filename"] == "a.pdf"
        assert result[1]["filename"] == "b.pdf"

    def test_order_unchanged_when_reranker_unavailable(self, retriever):
        """When is_available() is False the input order must be preserved."""
        chunk_a = _result("a.pdf", 0, semantic_score=0.9)
        chunk_b = _result("b.pdf", 0, semantic_score=0.3)
        deduped = [chunk_a, chunk_b]

        mock_reranker = MagicMock()
        mock_reranker.is_available.return_value = False

        with patch("src.rag.reranker.get_reranker", return_value=mock_reranker):
            result = retriever._apply_cross_encoder("test query", deduped)

        assert result[0]["filename"] == "a.pdf"
        assert result[1]["filename"] == "b.pdf"

    def test_order_unchanged_when_scores_list_empty(self, retriever):
        """When score() returns [] the if-ce_scores branch is skipped and order is unchanged."""
        chunk_a = _result("a.pdf", 0, semantic_score=0.9)
        chunk_b = _result("b.pdf", 0, semantic_score=0.3)
        deduped = [chunk_a, chunk_b]

        mock_reranker = MagicMock()
        mock_reranker.is_available.return_value = True
        mock_reranker.score.return_value = []

        with patch("src.rag.reranker.get_reranker", return_value=mock_reranker):
            with patch("src.rag.retrieval.config") as cfg:
                cfg.RERANKER_WEIGHT = 0.5
                result = retriever._apply_cross_encoder("test query", deduped)

        assert result[0]["filename"] == "a.pdf"
        assert result[1]["filename"] == "b.pdf"

    def test_combined_score_is_blended_at_configured_weight(self, retriever):
        """combined = (1 - w) * old_combined + w * ce_score."""
        chunk = _result("doc.pdf", 0, semantic_score=0.6, text="some text")
        # combined_score starts at 0.6 (same as semantic_score via _result)

        mock_reranker = MagicMock()
        mock_reranker.is_available.return_value = True
        mock_reranker.score.return_value = [0.4]

        with patch("src.rag.reranker.get_reranker", return_value=mock_reranker):
            with patch("src.rag.retrieval.config") as cfg:
                cfg.RERANKER_WEIGHT = 0.3
                result = retriever._apply_cross_encoder("test query", [chunk])

        expected = 0.7 * 0.6 + 0.3 * 0.4  # 0.54
        assert abs(result[0]["combined_score"] - expected) < 1e-9
