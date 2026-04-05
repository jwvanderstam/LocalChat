"""
In-Memory Cache Backend
=======================

LRU cache backed by ``collections.OrderedDict``.
Fast and zero-dependency; suitable for single-process use and testing.
"""

from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Any, Optional

from ...utils.logging_config import get_logger
from .base import CacheBackend, CacheStats

logger = get_logger(__name__)


class MemoryCache(CacheBackend):
    """
    In-memory LRU cache.

    Eviction is O(1) thanks to ``OrderedDict``.  No persistence —
    data is lost on process restart.  Suitable as a fallback when
    Redis is unavailable.
    """

    def __init__(self, namespace: str = "localchat", max_size: int = 1000) -> None:
        super().__init__(namespace)
        self.max_size = max_size
        self.stats.max_size = max_size
        self._cache: OrderedDict[str, tuple] = OrderedDict()
        logger.info(f"MemoryCache initialized (max_size={max_size})")

    def get(self, key: str) -> Any | None:
        full_key = self.make_key(key)

        if full_key not in self._cache:
            self.stats.misses += 1
            return None

        value, expiry = self._cache[full_key]

        if expiry and datetime.now() > expiry:
            self.delete(key)
            self.stats.misses += 1
            return None

        # Mark as most-recently used
        self._cache.move_to_end(full_key)
        self.stats.hits += 1
        return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        full_key = self.make_key(key)
        expiry = datetime.now() + timedelta(seconds=ttl) if ttl else None

        # Evict LRU entry if at capacity
        if len(self._cache) >= self.max_size and full_key not in self._cache:
            self._cache.popitem(last=False)
            self.stats.evictions += 1

        self._cache[full_key] = (value, expiry)
        self._cache.move_to_end(full_key)

        self.stats.sets += 1
        self.stats.size = len(self._cache)
        return True

    def delete(self, key: str) -> bool:
        full_key = self.make_key(key)
        if full_key in self._cache:
            del self._cache[full_key]
            self.stats.deletes += 1
            self.stats.size = len(self._cache)
            return True
        return False

    def exists(self, key: str) -> bool:
        full_key = self.make_key(key)
        if full_key not in self._cache:
            return False
        _, expiry = self._cache[full_key]
        if expiry and datetime.now() > expiry:
            self.delete(key)
            return False
        return True

    def clear(self) -> bool:
        prefix = f"{self.namespace}:"
        keys_to_delete = [k for k in self._cache if k.startswith(prefix)]
        for k in keys_to_delete:
            del self._cache[k]
        self.stats.size = len(self._cache)
        logger.info(f"Cleared {len(keys_to_delete)} keys from MemoryCache")
        return True

    def get_stats(self) -> CacheStats:
        self.stats.size = len(self._cache)
        return self.stats
