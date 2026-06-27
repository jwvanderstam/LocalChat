import hashlib
from typing import Any

from ..utils.logging_config import get_logger
from . import CacheBackend, CacheStats, create_cache_backend

logger = get_logger(__name__)


class EmbeddingCache:
    """Content-hashed embedding cache; avoids redundant Ollama embed calls."""

    def __init__(
        self,
        backend: CacheBackend | None = None,
        ttl: int = 3600 * 24 * 7  # 7 days default
    ):
        self.backend = backend or create_cache_backend('memory', namespace='embeddings', max_size=5000)
        self.ttl = ttl
        logger.info(f"EmbeddingCache initialized (ttl={ttl}s)")

    def _make_cache_key(self, text: str, model: str) -> str:
        content_hash = hashlib.sha256(f"{model}:{text}".encode()).hexdigest()
        return f"emb:{content_hash}"

    def get(self, text: str, model: str) -> list[float] | None:
        return self.backend.get(self._make_cache_key(text, model))

    def set(self, text: str, model: str, embedding: list[float]) -> bool:
        return self.backend.set(self._make_cache_key(text, model), embedding, ttl=self.ttl)

    def get_or_generate(
        self,
        text: str,
        model: str,
        generate_fn: callable
    ) -> tuple[list[float], bool]:
        embedding = self.get(text, model)
        if embedding is not None:
            logger.debug(f"Embedding cache HIT for {len(text)} chars")
            return embedding, True
        logger.debug(f"Embedding cache MISS for {len(text)} chars - generating")
        embedding = generate_fn(text)
        self.set(text, model, embedding)
        return embedding, False

    def clear(self) -> bool:
        return self.backend.clear()

    def get_stats(self) -> CacheStats | dict[str, Any]:
        return self.backend.get_stats()


class QueryCache:
    """Parameter-hashed cache for RAG retrieval results."""

    def __init__(
        self,
        backend: CacheBackend | None = None,
        ttl: int = 3600  # 1 hour default
    ):
        self.backend = backend or create_cache_backend('memory', namespace='queries', max_size=1000)
        self.ttl = ttl
        logger.info(f"QueryCache initialized (ttl={ttl}s)")

    def _make_cache_key(self, query: str, top_k: int, min_similarity: float, use_hybrid: bool) -> str:
        params = f"{query}:{top_k}:{min_similarity}:{use_hybrid}"
        return f"query:{hashlib.sha256(params.encode()).hexdigest()}"

    def get(self, query: str, top_k: int, min_similarity: float, use_hybrid: bool) -> list[tuple] | None:
        return self.backend.get(self._make_cache_key(query, top_k, min_similarity, use_hybrid))

    def set(self, query: str, top_k: int, min_similarity: float, use_hybrid: bool, results: list[tuple]) -> bool:
        return self.backend.set(self._make_cache_key(query, top_k, min_similarity, use_hybrid), results, ttl=self.ttl)

    def get_or_retrieve(
        self,
        query: str,
        top_k: int,
        min_similarity: float,
        use_hybrid: bool,
        retrieve_fn: callable
    ) -> tuple[list[tuple], bool]:
        results = self.get(query, top_k, min_similarity, use_hybrid)
        if results is not None:
            logger.info("Query cache HIT for: %s...", str(query)[:50].replace('\r', '').replace('\n', ' '))
            return results, True
        logger.info("Query cache MISS for: %s...", str(query)[:50].replace('\r', '').replace('\n', ' '))
        results = retrieve_fn()
        self.set(query, top_k, min_similarity, use_hybrid, results)
        return results, False

    def invalidate_pattern(self, pattern: str) -> bool:
        """Pattern-based invalidation is not yet implemented; clears all entries."""
        logger.info(f"Invalidating query cache (pattern: {pattern})")
        return self.backend.clear()

    def clear(self) -> bool:
        return self.backend.clear()

    def get_stats(self) -> CacheStats | dict[str, Any]:
        return self.backend.get_stats()


# Global instances — initialised once by init_caches() in app_bootstrap.py.
_embedding_cache: EmbeddingCache | None = None
_query_cache: QueryCache | None = None


def init_caches(
    embedding_backend: CacheBackend | None = None,
    query_backend: CacheBackend | None = None,
    embedding_ttl: int = 3600 * 24 * 7,
    query_ttl: int = 3600
) -> tuple[EmbeddingCache, QueryCache]:
    global _embedding_cache, _query_cache
    _embedding_cache = EmbeddingCache(embedding_backend, ttl=embedding_ttl)
    _query_cache = QueryCache(query_backend, ttl=query_ttl)
    logger.info("Global caches initialized")
    return _embedding_cache, _query_cache


def get_embedding_cache() -> EmbeddingCache | None:
    return _embedding_cache


def get_query_cache() -> QueryCache | None:
    return _query_cache
