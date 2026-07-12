import hashlib
import json
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ..utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class CacheStats:
    """Cache statistics."""
    hits: int = 0
    misses: int = 0
    sets: int = 0
    deletes: int = 0
    evictions: int = 0
    size: int = 0
    max_size: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return (self.hits / total * 100) if total > 0 else 0.0

    @property
    def usage_percent(self) -> float:
        return (self.size / self.max_size * 100) if self.max_size > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            'hits': self.hits,
            'misses': self.misses,
            'sets': self.sets,
            'deletes': self.deletes,
            'evictions': self.evictions,
            'size': self.size,
            'max_size': self.max_size,
            'hit_rate': f"{self.hit_rate:.2f}%",
            'usage': f"{self.usage_percent:.2f}%"
        }


class CacheBackend(ABC):
    """ABC defining the interface all cache backends must implement."""

    def __init__(self, namespace: str = "localchat"):
        self.namespace = namespace
        self.stats = CacheStats()

    @abstractmethod
    def get(self, key: str) -> Any | None:
        """Get value from cache."""
        pass

    @abstractmethod
    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Set value in cache with optional TTL."""
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete key from cache."""
        pass

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if key exists in cache."""
        pass

    @abstractmethod
    def clear(self) -> bool:
        """Clear all keys in namespace."""
        pass

    @abstractmethod
    def get_stats(self) -> CacheStats:
        """Get cache statistics."""
        pass

    def make_key(self, *parts: str) -> str:
        return f"{self.namespace}:{':'.join(parts)}"

    def hash_key(self, data: str) -> str:
        return hashlib.sha256(data.encode()).hexdigest()


class MemoryCache(CacheBackend):
    """LRU in-memory cache. No persistence; used for testing and Redis fallback."""

    def __init__(self, namespace: str = "localchat", max_size: int = 1000):
        super().__init__(namespace)
        self.max_size = max_size
        self.stats.max_size = max_size
        self._cache: OrderedDict[str, tuple[Any, datetime | None]] = OrderedDict()

        logger.info("MemoryCache initialized")

    def get(self, key: str) -> Any | None:
        """Get value from cache."""
        full_key = self.make_key(key)

        if full_key not in self._cache:
            self.stats.misses += 1
            return None

        value, expiry = self._cache[full_key]

        # Check expiry
        if expiry and datetime.now() > expiry:
            self.delete(key)
            self.stats.misses += 1
            return None

        # Move to end to mark as most-recently used (O(1))
        self._cache.move_to_end(full_key)

        self.stats.hits += 1
        return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Set value in cache with optional TTL."""
        full_key = self.make_key(key)

        # Calculate expiry
        expiry = None
        if ttl:
            expiry = datetime.now() + timedelta(seconds=ttl)

        # Evict least-recently used entry if at capacity (O(1))
        if len(self._cache) >= self.max_size and full_key not in self._cache:
            self._cache.popitem(last=False)
            self.stats.evictions += 1

        self._cache[full_key] = (value, expiry)
        self._cache.move_to_end(full_key)

        self.stats.sets += 1
        self.stats.size = len(self._cache)

        return True

    def delete(self, key: str) -> bool:
        """Delete key from cache."""
        full_key = self.make_key(key)

        if full_key in self._cache:
            del self._cache[full_key]
            self.stats.deletes += 1
            self.stats.size = len(self._cache)
            return True

        return False

    def exists(self, key: str) -> bool:
        """Check if key exists in cache."""
        full_key = self.make_key(key)

        if full_key not in self._cache:
            return False

        _, expiry = self._cache[full_key]
        if expiry and datetime.now() > expiry:
            self.delete(key)
            return False

        return True

    def clear(self) -> bool:
        """Clear all keys in namespace."""
        prefix = f"{self.namespace}:"
        keys_to_delete = [k for k in self._cache if k.startswith(prefix)]

        for key in keys_to_delete:
            del self._cache[key]

        self.stats.size = len(self._cache)
        logger.info(f"Cleared {len(keys_to_delete)} keys from MemoryCache")

        return True

    def get_stats(self) -> CacheStats:
        """Get cache statistics."""
        self.stats.size = len(self._cache)
        return self.stats


class RedisCache(CacheBackend):
    """Production cache with persistence, atomic operations, and distributed support."""

    def __init__(
        self,
        namespace: str = "localchat",
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str | None = None,
        socket_timeout: float = 5.0
    ):
        super().__init__(namespace)

        try:
            import redis
            self.redis = redis

            self.client = redis.Redis(
                host=host,
                port=port,
                db=db,
                password=password,
                socket_timeout=socket_timeout,
                decode_responses=False,  # We'll handle encoding
                socket_connect_timeout=socket_timeout
            )

            # Test connection
            self.client.ping()

            logger.info(f"RedisCache initialized (host={host}:{port}, db={db})")

        except ImportError:
            logger.error("Redis library not installed. Install: pip install redis")
            raise
        except Exception:
            logger.exception("Failed to connect to Redis")
            raise

    def get(self, key: str) -> Any | None:
        """Get value from cache."""
        full_key = self.make_key(key)

        try:
            data = self.client.get(full_key)

            if data is None:
                self.stats.misses += 1
                return None

            # Deserialize — json.loads accepts str or bytes directly
            value = json.loads(data)
            self.stats.hits += 1
            return value

        except Exception:
            logger.exception("Redis get error")
            self.stats.misses += 1
            return None

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Set value in cache with optional TTL."""
        full_key = self.make_key(key)

        try:
            # Serialize
            data = json.dumps(value).encode("utf-8")

            # Set with TTL
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
        """Delete key from cache."""
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
        """Check if key exists in cache."""
        full_key = self.make_key(key)

        try:
            return bool(self.client.exists(full_key))
        except Exception:
            logger.exception("Redis exists error")
            return False

    def clear(self) -> bool:
        """Clear all keys in namespace."""
        try:
            # Find all keys in namespace
            pattern = f"{self.namespace}:*"
            keys = []

            for key in self.client.scan_iter(match=pattern, count=100):
                keys.append(key)

            if keys:
                self.client.delete(*keys)
                logger.info(f"Cleared {len(keys)} keys from RedisCache")

            return True

        except Exception:
            logger.exception("Redis clear error")
            return False

    def get_stats(self) -> CacheStats:
        """Get cache statistics."""
        try:
            info: dict = self.client.info('stats')  # type: ignore[assignment]
            self.stats.size = info.get('keyspace_hits', 0) + info.get('keyspace_misses', 0)

            # Get namespace key count
            pattern = f"{self.namespace}:*"
            count = sum(1 for _ in self.client.scan_iter(match=pattern, count=100))
            self.stats.size = count

        except Exception:
            logger.exception("Redis stats error")

        return self.stats


def create_cache_backend(
    backend: str = "memory",
    namespace: str = "localchat",
    **kwargs
) -> CacheBackend:
    """Factory: 'memory' (default) or 'redis'."""
    if backend == "redis":
        # No silent fallback — caller decides what to do on failure.
        # Set REDIS_STRICT=false in config to opt into soft fallback at the bootstrap level.
        redis_kwargs = {k: v for k, v in kwargs.items() if k != 'max_size' and v is not None}
        return RedisCache(namespace=namespace, **redis_kwargs)

    elif backend == "memory":
        return MemoryCache(namespace=namespace, **kwargs)

    else:
        raise ValueError(f"Unknown cache backend: {backend}")
