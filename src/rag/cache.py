"""
Embedding Cache
===============

LRU cache for query embeddings to avoid redundant API calls.
"""

import hashlib
from typing import List, Optional, Dict, Any


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
        self._cache: Dict[str, List[float]] = {}
        self._access_order: List[str] = []
        self._hits = 0
        self._misses = 0
    
    def _hash_text(self, text: str, model: str) -> str:
        """Create hash key for text + model combination."""
        return hashlib.md5(f"{model}:{text}".encode()).hexdigest()
    
    def get(self, text: str, model: str) -> Optional[List[float]]:
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
            # Move to end (most recently used)
            self._access_order.remove(key)
            self._access_order.append(key)
            self._hits += 1
            return self._cache[key]
        self._misses += 1
        return None
    
    def put(self, text: str, model: str, embedding: List[float]) -> None:
        """
        Cache an embedding.
        
        Args:
            text: Text that was embedded
            model: Model used for embedding
            embedding: The embedding vector
        """
        key = self._hash_text(text, model)
        
        # Evict oldest if at capacity
        if len(self._cache) >= self.max_size and key not in self._cache:
            oldest_key = self._access_order.pop(0)
            del self._cache[oldest_key]
        
        self._cache[key] = embedding
        if key in self._access_order:
            self._access_order.remove(key)
        self._access_order.append(key)
    
    def stats(self) -> Dict[str, Any]:
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
