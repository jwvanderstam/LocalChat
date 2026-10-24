"""
Tests for cache manager behaviour.

Verifies that EmbeddingCache and QueryCache honour cache-hit/miss semantics,
produce independent entries for different parameters, and correctly invalidate.
"""


from src.cache.managers import EmbeddingCache, QueryCache

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _query_results(n=1):
    return [("chunk text", f"file{i}.pdf", i, 0.9 - i * 0.05, {}) for i in range(n)]


# ---------------------------------------------------------------------------
# EmbeddingCache
# ---------------------------------------------------------------------------

class TestEmbeddingCacheKeys:

    def test_different_models_have_independent_entries(self):
        """Same text embedded by two different models must not share cache entries."""
        cache = EmbeddingCache()
        emb_a = [1.0, 0.0]
        emb_b = [0.0, 1.0]
        cache.set("text", "model-a", emb_a)
        cache.set("text", "model-b", emb_b)

        assert cache.get("text", "model-a") == emb_a
        assert cache.get("text", "model-b") == emb_b

    def test_clear_removes_all_entries(self):
        """After clear(), previously cached embeddings return None."""
        cache = EmbeddingCache()
        cache.set("text", "model-a", [1.0, 2.0])
        cache.clear()

        assert cache.get("text", "model-a") is None


# ---------------------------------------------------------------------------
# QueryCache
# ---------------------------------------------------------------------------

class TestQueryCacheKeys:

    def test_different_top_k_produces_separate_entries(self):
        """Same query with different top_k values must have independent cache entries."""
        cache = QueryCache()
        results_5 = _query_results(1)
        results_10 = _query_results(2)
        cache.set("q", 5, 0.3, True, results_5)
        cache.set("q", 10, 0.3, True, results_10)

        assert cache.get("q", 5, 0.3, True) == results_5
        assert cache.get("q", 10, 0.3, True) == results_10

    def test_different_min_similarity_produces_separate_entries(self):
        """Same query with different min_similarity must have independent cache entries."""
        cache = QueryCache()
        strict = _query_results(1)
        loose = _query_results(5)
        cache.set("q", 5, 0.7, True, strict)
        cache.set("q", 5, 0.3, True, loose)

        assert cache.get("q", 5, 0.7, True) == strict
        assert cache.get("q", 5, 0.3, True) == loose

    def test_hybrid_flag_differentiates_entries(self):
        """Hybrid vs non-hybrid retrieval for the same query must be stored separately."""
        cache = QueryCache()
        hybrid_results = _query_results(3)
        semantic_results = _query_results(2)
        cache.set("q", 5, 0.3, True, hybrid_results)
        cache.set("q", 5, 0.3, False, semantic_results)

        assert cache.get("q", 5, 0.3, True) == hybrid_results
        assert cache.get("q", 5, 0.3, False) == semantic_results

    def test_clear_removes_all_entries(self):
        """After clear(), no previously cached results remain."""
        cache = QueryCache()
        cache.set("q", 5, 0.3, True, _query_results())
        cache.clear()

        assert cache.get("q", 5, 0.3, True) is None
