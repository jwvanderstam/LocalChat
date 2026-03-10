"""
Redis Cache Backend
===================

Production-grade distributed cache using Redis.
Falls back gracefully to ``MemoryCache`` when Redis is unavailable.
"""

import pickle
from typing import Any, Optional

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
        password: Optional[str] = None,
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
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    def get(self, key: str) -> Optional[Any]:
        full_key = self.make_key(key)
        try:
            data = self.client.get(full_key)
            if data is None:
                self.stats.misses += 1
                return None
            self.stats.hits += 1
            return pickle.loads(data)
        except Exception as e:
            logger.error(f"Redis get error: {e}")
            self.stats.misses += 1
            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        full_key = self.make_key(key)
        try:
            data = pickle.dumps(value)
            if ttl:
                self.client.setex(full_key, ttl, data)
            else:
                self.client.set(full_key, data)
            self.stats.sets += 1
            return True
        except Exception as e:
            logger.error(f"Redis set error: {e}")
            return False

    def delete(self, key: str) -> bool:
        full_key = self.make_key(key)
        try:
            result = self.client.delete(full_key)
            if int(result) > 0:  # type: ignore[arg-type]
                self.stats.deletes += 1
                return True
            return False
        except Exception as e:
            logger.error(f"Redis delete error: {e}")
            return False

    def exists(self, key: str) -> bool:
        full_key = self.make_key(key)
        try:
            return bool(self.client.exists(full_key))
        except Exception as e:
            logger.error(f"Redis exists error: {e}")
            return False

    def clear(self) -> bool:
        try:
            pattern = f"{self.namespace}:*"
            keys = list(self.client.scan_iter(match=pattern, count=100))
            if keys:
                self.client.delete(*keys)
                logger.info(f"Cleared {len(keys)} keys from RedisCache")
            return True
        except Exception as e:
            logger.error(f"Redis clear error: {e}")
            return False

    def get_stats(self) -> CacheStats:
        try:
            pattern = f"{self.namespace}:*"
            self.stats.size = sum(1 for _ in self.client.scan_iter(match=pattern, count=100))
        except Exception as e:
            logger.error(f"Redis stats error: {e}")
        return self.stats
