"""
Tests for hybrid scoring and deduplication in Retriever.

These tests verify the scoring math and deduplication window logic as
standalone unit tests — no database or Ollama required.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

# src/config.py raises at import time if PG_PASSWORD is missing.
# Set a test sentinel so collection succeeds without a real database.
os.environ.setdefault("PG_PASSWORD", "test-sentinel")

from src.rag.retrieval import Retriever
from src.utils.scope import ALL_WORKSPACES


@pytest.fixture
def retriever():
    return Retriever(db=None, ollama_client=None)


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
    """Row shape returned by db.documents.search_similar."""
    return (text, filename, chunk_index, similarity, {}, chunk_id)


def _lexical_row(filename, chunk_index, score, chunk_id=1, text="some chunk content here"):
    """Row shape returned by db.documents.search_lexical."""
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


class TestLexicalOnlyChunksAreBlendedWithTheirSimilarity:
    """A lexical-only chunk blended as semantic 0.0 ranked below every semantic hit, so on the
    P2-3 corpus none reached the context; 20 of the 29 answers lost before reranking were such
    chunks (2026-11-21)."""

    def test_a_lexical_only_chunk_blends_its_real_similarity(self, retriever):
        lexical = [_lexical_row("sheet.xlsx", 4, 0.8, chunk_id=9)]

        with patch("src.rag.retrieval.config") as cfg:
            cfg.app_state.get_rag_param.return_value = 0.7
            merged = retriever._merge_semantic_and_lexical([], lexical, {9: 0.6})

        assert merged["sheet.xlsx:4"]["semantic_score"] == 0.6
        assert abs(merged["sheet.xlsx:4"]["combined_score"] - (0.7 * 0.6 + 0.3 * 0.8)) < 1e-9

    def test_a_strong_lexical_only_chunk_now_outranks_a_weaker_semantic_hit(self, retriever):
        semantic = [_semantic_row("deck.pdf", 0, 0.65, chunk_id=1)]
        lexical = [_lexical_row("sheet.xlsx", 4, 0.8, chunk_id=9)]

        with patch("src.rag.retrieval.config") as cfg:
            cfg.app_state.get_rag_param.return_value = 0.7
            merged = retriever._merge_semantic_and_lexical(semantic, lexical, {9: 0.6})

        # 0.7 * 0.6 + 0.3 * 0.8 = 0.66 against 0.7 * 0.65 = 0.455; scored 0.0 it was 0.24.
        assert merged["sheet.xlsx:4"]["combined_score"] > merged["deck.pdf:0"]["combined_score"]

    def test_the_pipeline_asks_only_for_chunks_vector_search_did_not_return(self, retriever):
        retriever._db = MagicMock()
        retriever._db.documents.search_similar.return_value = [_semantic_row("a.pdf", 0, 0.7, chunk_id=1)]
        retriever._db.documents.search_lexical.return_value = [
            _lexical_row("a.pdf", 0, 0.5, chunk_id=1),
            _lexical_row("b.docx", 2, 0.9, chunk_id=7),
        ]
        retriever._db.documents.similarity_for_chunks.return_value = {7: 0.55}

        filtered = retriever._run_retrieval_pipeline(
            query_clean="query", query_embedding=[0.5] * 768, top_k=5, min_similarity=0.30,
            file_type_filter=None, use_hybrid_search=True, scope="ws-1",
        )

        retriever._db.documents.similarity_for_chunks.assert_called_once_with([0.5] * 768, [7], scope="ws-1")
        assert filtered["b.docx:2"]["semantic_score"] == 0.55

    def test_a_failed_similarity_lookup_falls_back_to_semantic_zero(self, retriever):
        retriever._db = MagicMock()
        retriever._db.documents.search_similar.return_value = []
        retriever._db.documents.search_lexical.return_value = [_lexical_row("b.docx", 2, 0.9, chunk_id=7)]
        retriever._db.documents.similarity_for_chunks.side_effect = RuntimeError("pool exhausted")

        filtered = retriever._run_retrieval_pipeline(
            query_clean="query", query_embedding=[0.5] * 768, top_k=5, min_similarity=0.30,
            file_type_filter=None, use_hybrid_search=True, scope="ws-1",
        )

        assert filtered["b.docx:2"]["semantic_score"] == 0.0


# ---------------------------------------------------------------------------
# _run_retrieval_pipeline — the threshold must gate on each arm's own score,
# never on the blended combined_score. Regression coverage for a bug where
# _merge_semantic_and_lexical was tested in isolation but the pipeline-level
# filter that runs immediately after it was not: a lexical-only chunk's
# semantic_score is 0.0, so combined_score = lexical_weight * lexical_score,
# and ts_rank_cd's rank/(rank+1) normalization is always < 1.0 — at default
# weights (0.70/0.30) and threshold (0.30), no lexical-only chunk could ever
# reach 0.30, and any query with even one lexical hit silently shrank every
# pure-semantic result by 30%, dropping previously-passing matches.
# ---------------------------------------------------------------------------

class TestRunRetrievalPipelineThreshold:
    def test_lexical_only_chunk_survives_the_pipeline_filter(self, retriever):
        """At default weights this chunk's combined_score (0.30 * 0.9 = 0.27)
        is below min_similarity (0.30) — it must survive anyway, on
        lexical_score > 0, not on the blended score."""
        retriever._db = MagicMock()
        retriever._db.documents.search_similar.return_value = []
        retriever._db.documents.search_lexical.return_value = [
            _lexical_row("only_lexical.pdf", 0, 0.9, chunk_id=1),
        ]
        # Its real similarity is below the threshold: it must survive on lexical_score alone.
        retriever._db.documents.similarity_for_chunks.return_value = {1: 0.10}

        filtered = retriever._run_retrieval_pipeline(
            query_clean="exact identifier",
            query_embedding=[0.0] * 768,
            top_k=5,
            min_similarity=0.30,
            file_type_filter=None,
            use_hybrid_search=True, scope=ALL_WORKSPACES,
        )

        assert "only_lexical.pdf:0" in filtered

    def test_pure_semantic_chunk_not_punished_by_unrelated_lexical_hit(self, retriever):
        """A chunk found only by vector search, already above min_similarity
        (search_similar_chunks applies the threshold at the SQL level), must
        survive even though the lexical arm returned results — for a
        different chunk entirely — for this query. Diluting this chunk's
        own score by the blend (0.70 * 0.40 = 0.28 < 0.30) must not drop it."""
        retriever._db = MagicMock()
        retriever._db.documents.search_similar.return_value = [
            _semantic_row("semantic_only.pdf", 0, 0.40, chunk_id=2),
        ]
        retriever._db.documents.search_lexical.return_value = [
            _lexical_row("other_chunk.pdf", 0, 0.9, chunk_id=3),
        ]
        retriever._db.documents.similarity_for_chunks.return_value = {3: 0.20}

        filtered = retriever._run_retrieval_pipeline(
            query_clean="query",
            query_embedding=[0.0] * 768,
            top_k=5,
            min_similarity=0.30,
            file_type_filter=None,
            use_hybrid_search=True, scope=ALL_WORKSPACES,
        )

        assert "semantic_only.pdf:0" in filtered

    def test_chunk_below_both_thresholds_is_still_dropped(self, retriever):
        """The fix must not turn the filter into a no-op — a chunk with
        neither a qualifying semantic score nor any lexical match at all
        must still be excluded."""
        retriever._db = MagicMock()
        retriever._db.documents.search_similar.return_value = [
            _semantic_row("weak.pdf", 0, 0.10, chunk_id=4),
        ]
        retriever._db.documents.search_lexical.return_value = []

        filtered = retriever._run_retrieval_pipeline(
            query_clean="query",
            query_embedding=[0.0] * 768,
            top_k=5,
            min_similarity=0.30,
            file_type_filter=None,
            use_hybrid_search=True, scope=ALL_WORKSPACES,
        )

        assert "weak.pdf:0" not in filtered
        assert filtered == {}


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


# ---------------------------------------------------------------------------
# _rank_and_finalize — the cross-encoder chooses from RERANK_CANDIDATES, not RERANK_TOP_K.
# It scored only the blend's top RERANK_TOP_K, and the blend ranks worse than it does: on the
# P2-3 corpus a pool of 36 put the answer in the context for 67 of 105 questions against 57.
# ---------------------------------------------------------------------------

def _distinct(n: int) -> dict:
    """n candidates in different files, blend-ranked 0 (best) .. n-1, each with distinct words."""
    return _results_dict(*(
        _result(f"doc{i:02d}.pdf", 0, semantic_score=0.9 - i * 0.01, text=f"unique words for passage {i} only{i}")
        for i in range(n)
    ))


def _cross_encoder_preferring(winner: str):
    reranker = MagicMock()
    reranker.is_available.return_value = True
    reranker.score.side_effect = lambda q, passages: [5.0 if winner in p else -1.0 for p in passages]
    return reranker


def _finalize(retriever, candidates: dict, *, reranker_enabled: bool, pool: int, top_k: int = 3):
    with patch("src.rag.retrieval.config") as cfg, \
         patch("src.rag.reranker.get_reranker", return_value=_cross_encoder_preferring("passage 20 ")):
        cfg.ENABLE_DIVERSITY_FILTER = True
        cfg.RERANK_RESULTS = False
        cfg.RERANKER_ENABLED = reranker_enabled
        cfg.RERANKER_WEIGHT = 0.3
        cfg.RERANK_MIN_SCORE = -5.0
        cfg.RERANK_CANDIDATES = pool
        cfg.app_state.get_rag_param.side_effect = {"RERANK_TOP_K": top_k, "DIVERSITY_THRESHOLD": 0.7}.get
        return retriever._rank_and_finalize("query", candidates)


class TestTheCrossEncoderChoosesFromAWiderPool:
    def test_a_candidate_ranked_21st_by_the_blend_reaches_the_context(self, retriever):
        results = _finalize(retriever, _distinct(30), reranker_enabled=True, pool=24)

        assert "doc20.pdf" in {r.filename for r in results}

    def test_only_rerank_top_k_are_kept(self, retriever):
        results = _finalize(retriever, _distinct(30), reranker_enabled=True, pool=24, top_k=3)

        assert len(results) == 3

    def test_a_pool_smaller_than_the_candidate_misses_it(self, retriever):
        # The counterpart: with the old reach the same candidate never meets the cross-encoder.
        results = _finalize(retriever, _distinct(30), reranker_enabled=True, pool=12)

        assert "doc20.pdf" not in {r.filename for r in results}

    def test_without_the_reranker_the_blend_keeps_its_own_top_k(self, retriever):
        results = _finalize(retriever, _distinct(30), reranker_enabled=False, pool=24, top_k=3)

        assert {r.filename for r in results} == {"doc00.pdf", "doc01.pdf", "doc02.pdf"}
