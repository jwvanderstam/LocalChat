"""
Cache Backend Base Classes
==========================

Defines the ``CacheStats`` dataclass and the ``CacheBackend`` abstract
base class that all concrete backends must implement.
"""

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ...utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class CacheStats:
    """Cache operation statistics."""

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
            'usage': f"{self.usage_percent:.2f}%",
        }


class CacheBackend(ABC):
    """Abstract base class that all cache backends must implement."""

    def __init__(self, namespace: str = "localchat") -> None:
        self.namespace = namespace
        self.stats = CacheStats()

    @abstractmethod
    def get(self, key: str) -> Any | None:
        """Return a cached value, or ``None`` if absent / expired."""

    @abstractmethod
    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Store ``value`` under ``key`` with an optional TTL in seconds."""

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Remove ``key`` from the cache. Returns ``True`` if it existed."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Return ``True`` if ``key`` is present and not expired."""

    @abstractmethod
    def clear(self) -> bool:
        """Remove all keys belonging to this namespace."""

    @abstractmethod
    def get_stats(self) -> CacheStats:
        """Return current cache statistics."""

    def make_key(self, *parts: str) -> str:
        """Build a namespaced cache key from one or more parts."""
        return f"{self.namespace}:{':'.join(parts)}"

    def hash_key(self, data: str) -> str:
        """Return a SHA-256 hex digest of ``data`` for use as a cache key."""
        return hashlib.sha256(data.encode()).hexdigest()
