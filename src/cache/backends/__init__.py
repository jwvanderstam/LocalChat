# -*- coding: utf-8 -*-

"""
Cache Backends
==============

Provides all cache backend implementations:
- base        — CacheStats dataclass + CacheBackend ABC
- memory      — MemoryCache  (in-process LRU, zero-dependency)
- redis_cache — RedisCache   (distributed, requires redis package)
- database_cache — DatabaseCache (persistent, uses PostgreSQL)
"""

from .base import CacheStats, CacheBackend
from .memory import MemoryCache
from .redis_cache import RedisCache
from .database_cache import DatabaseCache, create_db_cache

__all__ = [
    'CacheStats',
    'CacheBackend',
    'MemoryCache',
    'RedisCache',
    'DatabaseCache',
    'create_db_cache',
]
