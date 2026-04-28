"""
Embedding Cache
===============

LRU cache for query embeddings to avoid redundant API calls.
"""

import hashlib
from collections import OrderedDict
from typing import Any


class EmbeddingCache:
    """
    LRU cache for query embeddings to avoid redundant API calls.

    Caches embeddings based on text hash for fast lookup.
    """

    def __init__(self, max_size: int = 1000) -> None:
        """
        Initialize embedding cache.

        Args:
            max_size: Maximum number of embeddings to cache
        """
        self.max_size = max_size
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._hits = 0
        self._misses = 0

    def _hash_text(self, text: str, model: str) -> str:
        """Create hash key for text + model combination."""
        return hashlib.sha256(f"{model}:{text}".encode()).hexdigest()

    def get(self, text: str, model: str) -> list[float] | None:
        """
        Get cached embedding if available.

        Args:
            text: Text that was embedded
            model: Model used for embedding

        Returns:
            Cached embedding or None
        """
        key = self._hash_text(text, model)
        if key in self._cache:
            self._cache.move_to_end(key)  # O(1)
            self._hits += 1
            return self._cache[key]
        self._misses += 1
        return None

    def put(self, text: str, model: str, embedding: list[float]) -> None:
        """
        Cache an embedding.

        Args:
            text: Text that was embedded
            model: Model used for embedding
            embedding: The embedding vector
        """
        key = self._hash_text(text, model)
        if key in self._cache:
            self._cache.move_to_end(key)  # O(1)
        else:
            if len(self._cache) >= self.max_size:
                self._cache.popitem(last=False)  # O(1) evict LRU
        self._cache[key] = embedding

    def stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0.0
        return {
            'size': len(self._cache),
            'max_size': self.max_size,
            'hits': self._hits,
            'misses': self._misses,
            'hit_rate': f"{hit_rate:.1%}"
        }


# Global embedding cache
embedding_cache = EmbeddingCache(max_size=500)
