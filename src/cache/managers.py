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


