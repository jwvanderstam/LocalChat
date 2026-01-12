# -*- coding: utf-8 -*-

"""
Cache Backends Module
====================

Provides various caching backend implementations:
- Memory: Fast, in-process cache (L1)
- Redis: Distributed cache (L2)
- Database: Persistent cache (L3)

Author: LocalChat Team
Created: January 2025
"""

from .database_cache import DatabaseCache, create_db_cache

__all__ = ['DatabaseCache', 'create_db_cache']
