"""
Tests for cache manager behaviour.

Verifies that EmbeddingCache and QueryCache honour cache-hit/miss semantics,
produce independent entries for different parameters, and correctly invalidate.
"""

from unittest.mock import MagicMock

from src.cache.managers import EmbeddingCache, QueryCache

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _query_results(n=1):
    return [("chunk text", f"file{i}.pdf", i, 0.9 - i * 0.05, {}) for i in range(n)]


# ---------------------------------------------------------------------------
# EmbeddingCache
# ---------------------------------------------------------------------------

class TestEmbeddingCacheGetOrGenerate:
    def test_hit_does_not_call_generate_fn(self):
        """A cached embedding is returned without invoking generate_fn."""
        cache = EmbeddingCache()
        embedding = [0.1, 0.2, 0.3]
        cache.set("hello", "model-a", embedding)

        generate_fn = MagicMock()
        result, was_cached = cache.get_or_generate("hello", "model-a", generate_fn)

        assert result == embedding
        assert was_cached is True
        generate_fn.assert_not_called()

    def test_miss_calls_generate_fn_and_stores_result(self):
        """On a miss, generate_fn is called once and the result is cached."""
        cache = EmbeddingCache()
        new_embedding = [0.9, 0.8, 0.7]
        generate_fn = MagicMock(return_value=new_embedding)

        result, was_cached = cache.get_or_generate("new text", "model-a", generate_fn)

        assert result == new_embedding
        assert was_cached is False
        generate_fn.assert_called_once_with("new text")

        # Second call must be a hit — generate_fn should not be called again
        _, second_cached = cache.get_or_generate("new text", "model-a", MagicMock())
        assert second_cached is True

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

class TestQueryCacheGetOrRetrieve:
    def test_hit_returns_results_without_calling_retrieve_fn(self):
        """Cached query results are returned without calling retrieve_fn."""
        cache = QueryCache()
        results = _query_results(3)
        cache.set("what is rag?", 5, 0.3, True, results)

        retrieve_fn = MagicMock()
        returned, was_cached = cache.get_or_retrieve(
            "what is rag?", 5, 0.3, True, retrieve_fn
        )

        assert returned == results
        assert was_cached is True
        retrieve_fn.assert_not_called()

    def test_miss_calls_retrieve_fn_and_stores_result(self):
        """On a miss, retrieve_fn is called and its result is persisted."""
        cache = QueryCache()
        results = _query_results(2)
        retrieve_fn = MagicMock(return_value=results)

        returned, was_cached = cache.get_or_retrieve(
            "new query", 5, 0.3, True, retrieve_fn
        )

        assert returned == results
        assert was_cached is False
        retrieve_fn.assert_called_once()

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

    def test_invalidate_pattern_clears_all_entries(self):
        """After invalidate_pattern, all cached results are gone."""
        cache = QueryCache()
        cache.set("what is rag?", 5, 0.3, True, _query_results())
        cache.set("explain chunking", 5, 0.3, True, _query_results())

        cache.invalidate_pattern("*")

        assert cache.get("what is rag?", 5, 0.3, True) is None
        assert cache.get("explain chunking", 5, 0.3, True) is None

    def test_clear_removes_all_entries(self):
        """After clear(), no previously cached results remain."""
        cache = QueryCache()
        cache.set("q", 5, 0.3, True, _query_results())
        cache.clear()

        assert cache.get("q", 5, 0.3, True) is None
