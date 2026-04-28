
"""
Cache Module - Base Classes and Interfaces
==========================================

Provides caching infrastructure for LocalChat with multiple backend support.

Supports:
- Redis backend (production)
- In-memory backend (fallback/testing)
- Embedding caching
- Query result caching
- TTL and eviction policies
- Cache statistics

"""

import hashlib
import json
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

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
        """Calculate hit rate."""
        total = self.hits + self.misses
        return (self.hits / total * 100) if total > 0 else 0.0

    @property
    def usage_percent(self) -> float:
        """Calculate cache usage percentage."""
        return (self.size / self.max_size * 100) if self.max_size > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
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
    """
    Abstract base class for cache backends.

    Defines the interface that all cache backends must implement.
    """

    def __init__(self, namespace: str = "localchat"):
        """
        Initialize cache backend.

        Args:
            namespace: Cache key namespace for isolation
        """
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
        """
        Create namespaced cache key.

        Args:
            *parts: Key components

        Returns:
            Namespaced cache key
        """
        return f"{self.namespace}:{':'.join(parts)}"

    def hash_key(self, data: str) -> str:
        """
        Create hash of data for cache key.

        Args:
            data: Data to hash

        Returns:
            SHA256 hash hex string
        """
        return hashlib.sha256(data.encode()).hexdigest()


class MemoryCache(CacheBackend):
    """
    In-memory cache implementation.

    Fast, simple cache with LRU eviction. No persistence.
    Good for testing and fallback when Redis unavailable.
    """

    def __init__(self, namespace: str = "localchat", max_size: int = 1000):
        """
        Initialize memory cache.

        Args:
            namespace: Cache namespace
            max_size: Maximum number of items
        """
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
    """
    Redis cache implementation.

    Production-grade cache with persistence, atomic operations,
    and distributed support.
    """

    def __init__(
        self,
        namespace: str = "localchat",
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str | None = None,
        socket_timeout: float = 5.0
    ):
        """
        Initialize Redis cache.

        Args:
            namespace: Cache namespace
            host: Redis host
            port: Redis port
            db: Redis database number
            password: Redis password (optional)
            socket_timeout: Socket timeout in seconds
        """
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
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    def get(self, key: str) -> Any | None:
        """Get value from cache."""
        full_key = self.make_key(key)

        try:
            data = self.client.get(full_key)

            if data is None:
                self.stats.misses += 1
                return None

            # Deserialize
            value = json.loads(data.decode("utf-8"))
            self.stats.hits += 1
            return value

        except Exception as e:
            logger.error(f"Redis get error: {e}")
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

        except Exception as e:
            logger.error(f"Redis set error: {e}")
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

        except Exception as e:
            logger.error(f"Redis delete error: {e}")
            return False

    def exists(self, key: str) -> bool:
        """Check if key exists in cache."""
        full_key = self.make_key(key)

        try:
            return bool(self.client.exists(full_key))
        except Exception as e:
            logger.error(f"Redis exists error: {e}")
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

        except Exception as e:
            logger.error(f"Redis clear error: {e}")
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

        except Exception as e:
            logger.error(f"Redis stats error: {e}")

        return self.stats


def create_cache_backend(
    backend: str = "memory",
    namespace: str = "localchat",
    **kwargs
) -> CacheBackend:
    """
    Factory function to create cache backend.

    Args:
        backend: Backend type ('memory' or 'redis')
        namespace: Cache namespace
        **kwargs: Backend-specific arguments

    Returns:
        Configured cache backend

    Example:
        >>> # Memory cache
        >>> cache = create_cache_backend('memory', max_size=1000)
        >>>
        >>> # Redis cache
        >>> cache = create_cache_backend('redis', host='localhost', port=6379)
    """
    if backend == "redis":
        try:
            # Remove max_size from kwargs for Redis (it doesn't use it)
            redis_kwargs = {k: v for k, v in kwargs.items() if k != 'max_size' and v is not None}
            return RedisCache(namespace=namespace, **redis_kwargs)
        except Exception as e:
            logger.warning(f"Redis unavailable, falling back to memory cache: {e}")
            return MemoryCache(namespace=namespace, max_size=kwargs.get('max_size', 1000))

    elif backend == "memory":
        return MemoryCache(namespace=namespace, **kwargs)

    else:
        raise ValueError(f"Unknown cache backend: {backend}")
