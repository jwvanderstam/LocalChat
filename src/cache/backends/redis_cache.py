"""
Redis Cache Backend
===================

Production-grade distributed cache using Redis.
Falls back gracefully to ``MemoryCache`` when Redis is unavailable.
"""

import pickle
from typing import Any

from ...utils.logging_config import get_logger
from .base import CacheBackend, CacheStats

logger = get_logger(__name__)


class RedisCache(CacheBackend):
    """
    Redis-backed cache.

    Provides persistence, atomic operations, and distributed support.
    Requires the ``redis`` package (``pip install redis``).
    """

    def __init__(
        self,
        namespace: str = "localchat",
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str | None = None,
        socket_timeout: float = 5.0,
    ) -> None:
        super().__init__(namespace)
        try:
            import redis

            self.client = redis.Redis(
                host=host,
                port=port,
                db=db,
                password=password,
                socket_timeout=socket_timeout,
                decode_responses=False,
                socket_connect_timeout=socket_timeout,
            )
            self.client.ping()
            logger.info(f"RedisCache initialized (host={host}:{port}, db={db})")
        except ImportError:
            logger.error("Redis library not installed. Run: pip install redis")
            raise
        except Exception:
            logger.exception("Failed to connect to Redis")
            raise

    def get(self, key: str) -> Any | None:
        full_key = self.make_key(key)
        try:
            data = self.client.get(full_key)
            if data is None:
                self.stats.misses += 1
                return None
            self.stats.hits += 1
            # decode_responses=False guarantees bytes at runtime; narrow for pickle's typed signature
            if isinstance(data, str):
                data = data.encode()
            return pickle.loads(data)  # nosec B301
        except Exception:
            logger.exception("Redis get error")
            self.stats.misses += 1
            return None

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        full_key = self.make_key(key)
        try:
            data = pickle.dumps(value)
            if ttl:
                self.client.setex(full_key, ttl, data)
            else:
                self.client.set(full_key, data)
            self.stats.sets += 1
            return True
        except Exception:
            logger.exception("Redis set error")
            return False

    def delete(self, key: str) -> bool:
        full_key = self.make_key(key)
        try:
            result = self.client.delete(full_key)
            if int(result) > 0:  # type: ignore[arg-type]
                self.stats.deletes += 1
                return True
            return False
        except Exception:
            logger.exception("Redis delete error")
            return False

    def exists(self, key: str) -> bool:
        full_key = self.make_key(key)
        try:
            return bool(self.client.exists(full_key))
        except Exception:
            logger.exception("Redis exists error")
            return False

    def clear(self) -> bool:
        try:
            pattern = f"{self.namespace}:*"
            keys = list(self.client.scan_iter(match=pattern, count=100))
            if keys:
                self.client.delete(*keys)
                logger.info(f"Cleared {len(keys)} keys from RedisCache")
            return True
        except Exception:
            logger.exception("Redis clear error")
            return False

    def get_stats(self) -> CacheStats:
        try:
            pattern = f"{self.namespace}:*"
            self.stats.size = sum(1 for _ in self.client.scan_iter(match=pattern, count=100))
        except Exception:
            logger.exception("Redis stats error")
        return self.stats
