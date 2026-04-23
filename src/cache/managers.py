
"""
Embedding Cache Manager
=======================

Specialized cache for embedding vectors with intelligent key generation
and size management.

"""

import hashlib
from typing import List, Optional, Tuple

from ..utils.logging_config import get_logger
from . import CacheBackend, create_cache_backend

logger = get_logger(__name__)


class EmbeddingCache:
    """
    Cache manager for embedding vectors.

    Caches embedding generation results to avoid redundant API calls.
    Uses content hashing for reliable cache keys.
    """

    def __init__(
        self,
        backend: CacheBackend | None = None,
        ttl: int = 3600 * 24 * 7  # 7 days default
    ):
        """
        Initialize embedding cache.

        Args:
            backend: Cache backend (creates memory cache if None)
            ttl: Time-to-live in seconds (default: 7 days)
        """
        self.backend = backend or create_cache_backend('memory', namespace='embeddings', max_size=5000)
        self.ttl = ttl

        logger.info(f"EmbeddingCache initialized (ttl={ttl}s)")

    def _make_cache_key(self, text: str, model: str) -> str:
        """
        Create cache key for embedding.

        Args:
            text: Text content
            model: Model name

        Returns:
            Cache key
        """
        # Hash content for reliable key
        content_hash = hashlib.sha256(f"{model}:{text}".encode()).hexdigest()
        return f"emb:{content_hash}"

    def get(self, text: str, model: str) -> list[float] | None:
        """
        Get cached embedding.

        Args:
            text: Text content
            model: Model name

        Returns:
            Embedding vector or None if not cached
        """
        key = self._make_cache_key(text, model)
        return self.backend.get(key)

    def set(self, text: str, model: str, embedding: list[float]) -> bool:
        """
        Cache embedding.

        Args:
            text: Text content
            model: Model name
            embedding: Embedding vector

        Returns:
            True if cached successfully
        """
        key = self._make_cache_key(text, model)
        return self.backend.set(key, embedding, ttl=self.ttl)

    def get_or_generate(
        self,
        text: str,
        model: str,
        generate_fn: callable
    ) -> tuple[list[float], bool]:
        """
        Get cached embedding or generate new one.

        Args:
            text: Text content
            model: Model name
            generate_fn: Function to generate embedding if not cached

        Returns:
            Tuple of (embedding, was_cached)
        """
        # Try cache first
        embedding = self.get(text, model)
        if embedding is not None:
            logger.debug(f"Embedding cache HIT for {len(text)} chars")
            return embedding, True

        # Generate and cache
        logger.debug(f"Embedding cache MISS for {len(text)} chars - generating")
        embedding = generate_fn(text)
        self.set(text, model, embedding)

        return embedding, False

    def clear(self) -> bool:
        """Clear all cached embeddings."""
        return self.backend.clear()

    def get_stats(self):
        """Get cache statistics."""
        return self.backend.get_stats()


class QueryCache:
    """
    Cache manager for RAG query results.

    Caches retrieval results to speed up repeated queries.
    """

    def __init__(
        self,
        backend: CacheBackend | None = None,
        ttl: int = 3600  # 1 hour default
    ):
        """
        Initialize query cache.

        Args:
            backend: Cache backend (creates memory cache if None)
            ttl: Time-to-live in seconds (default: 1 hour)
        """
        self.backend = backend or create_cache_backend('memory', namespace='queries', max_size=1000)
        self.ttl = ttl

        logger.info(f"QueryCache initialized (ttl={ttl}s)")

    def _make_cache_key(
        self,
        query: str,
        top_k: int,
        min_similarity: float,
        use_hybrid: bool
    ) -> str:
        """
        Create cache key for query.

        Args:
            query: Query text
            top_k: Number of results
            min_similarity: Minimum similarity threshold
            use_hybrid: Whether using hybrid search

        Returns:
            Cache key
        """
        # Hash query parameters
        params = f"{query}:{top_k}:{min_similarity}:{use_hybrid}"
        query_hash = hashlib.sha256(params.encode()).hexdigest()
        return f"query:{query_hash}"

    def get(
        self,
        query: str,
        top_k: int,
        min_similarity: float,
        use_hybrid: bool
    ) -> list[tuple] | None:
        """
        Get cached query results.

        Args:
            query: Query text
            top_k: Number of results
            min_similarity: Minimum similarity threshold
            use_hybrid: Whether using hybrid search

        Returns:
            Cached results or None
        """
        key = self._make_cache_key(query, top_k, min_similarity, use_hybrid)
        return self.backend.get(key)

    def set(
        self,
        query: str,
        top_k: int,
        min_similarity: float,
        use_hybrid: bool,
        results: list[tuple]
    ) -> bool:
        """
        Cache query results.

        Args:
            query: Query text
            top_k: Number of results
            min_similarity: Minimum similarity threshold
            use_hybrid: Whether using hybrid search
            results: Query results

        Returns:
            True if cached successfully
        """
        key = self._make_cache_key(query, top_k, min_similarity, use_hybrid)
        return self.backend.set(key, results, ttl=self.ttl)

    def get_or_retrieve(
        self,
        query: str,
        top_k: int,
        min_similarity: float,
        use_hybrid: bool,
        retrieve_fn: callable
    ) -> tuple[list[tuple], bool]:
        """
        Get cached results or retrieve new ones.

        Args:
            query: Query text
            top_k: Number of results
            min_similarity: Minimum similarity threshold
            use_hybrid: Whether using hybrid search
            retrieve_fn: Function to retrieve if not cached

        Returns:
            Tuple of (results, was_cached)
        """
        # Try cache first
        results = self.get(query, top_k, min_similarity, use_hybrid)
        if results is not None:
            logger.info("Query cache HIT for: %s...", str(query)[:50].replace('\r', '').replace('\n', ' '))
            return results, True

        # Retrieve and cache
        logger.info("Query cache MISS for: %s...", str(query)[:50].replace('\r', '').replace('\n', ' '))
        results = retrieve_fn()
        self.set(query, top_k, min_similarity, use_hybrid, results)

        return results, False

    def invalidate_pattern(self, pattern: str) -> bool:
        """
        Invalidate cache entries matching pattern.

        Useful when documents are added/removed.

        Args:
            pattern: Pattern to match

        Returns:
            True if successful
        """
        # Pattern-based invalidation is not yet implemented; clear all entries.
        logger.info(f"Invalidating query cache (pattern: {pattern})")
        return self.backend.clear()

    def clear(self) -> bool:
        """Clear all cached queries."""
        return self.backend.clear()

    def get_stats(self):
        """Get cache statistics."""
        return self.backend.get_stats()


# Global cache instances (initialized in app factory)
_embedding_cache: EmbeddingCache | None = None
_query_cache: QueryCache | None = None


def init_caches(
    embedding_backend: CacheBackend | None = None,
    query_backend: CacheBackend | None = None,
    embedding_ttl: int = 3600 * 24 * 7,
    query_ttl: int = 3600
) -> tuple[EmbeddingCache, QueryCache]:
    """
    Initialize global cache instances.

    Args:
        embedding_backend: Backend for embedding cache
        query_backend: Backend for query cache
        embedding_ttl: TTL for embeddings (default: 7 days)
        query_ttl: TTL for queries (default: 1 hour)

    Returns:
        Tuple of (embedding_cache, query_cache)
    """
    global _embedding_cache, _query_cache

    _embedding_cache = EmbeddingCache(embedding_backend, ttl=embedding_ttl)
    _query_cache = QueryCache(query_backend, ttl=query_ttl)

    logger.info("Global caches initialized")

    return _embedding_cache, _query_cache


def get_embedding_cache() -> EmbeddingCache | None:
    """Get global embedding cache instance."""
    return _embedding_cache


def get_query_cache() -> QueryCache | None:
    """Get global query cache instance."""
    return _query_cache
