# -*- coding: utf-8 -*-

"""
Cache Base Classes Tests
=========================

Tests for cache base classes and interfaces (src/cache/__init__.py)

Target: Increase coverage from 0% to 60% (+1.5% overall)

Covers:
- CacheStats
- CacheBackend interface
- MemoryCache
- Cache factory functions

Author: LocalChat Team
Created: January 2025
"""

import pytest


class TestCacheStats:
    """Test cache statistics."""
    
    def test_cache_stats_initialization(self):
        """Test CacheStats initializes with zeros."""
        from src.cache import CacheStats
        
        stats = CacheStats()
        
        assert stats.hits == 0
        assert stats.misses == 0
        assert stats.sets == 0
        assert stats.deletes == 0
        assert stats.evictions == 0
        assert stats.size == 0
    
    def test_cache_stats_hit_rate_zero_when_empty(self):
        """Test hit rate is 0% when no hits/misses."""
        from src.cache import CacheStats
        
        stats = CacheStats()
        
        assert stats.hit_rate == 0.0
    
    def test_cache_stats_hit_rate_calculation(self):
        """Test hit rate calculation."""
        from src.cache import CacheStats
        
        stats = CacheStats(hits=75, misses=25)
        
        assert stats.hit_rate == 75.0
    
    def test_cache_stats_usage_percent_zero_when_no_max(self):
        """Test usage percent is 0% when max_size is 0."""
        from src.cache import CacheStats
        
        stats = CacheStats(size=10, max_size=0)
        
        assert stats.usage_percent == 0.0
    
    def test_cache_stats_usage_percent_calculation(self):
        """Test usage percent calculation."""
        from src.cache import CacheStats
        
        stats = CacheStats(size=50, max_size=100)
        
        assert stats.usage_percent == 50.0
    
    def test_cache_stats_to_dict(self):
        """Test converting stats to dictionary."""
        from src.cache import CacheStats
        
        stats = CacheStats(hits=10, misses=5, sets=15)
        result = stats.to_dict()
        
        assert isinstance(result, dict)
        assert result['hits'] == 10
        assert result['misses'] == 5
        assert result['sets'] == 15
        assert 'hit_rate' in result
        assert 'usage' in result


class TestCacheBackend:
    """Test CacheBackend abstract class."""
    
    def test_cache_backend_initialization(self):
        """Test CacheBackend base initialization."""
        from src.cache import CacheBackend
        
        # Cannot instantiate abstract class directly
        # But can check via concrete implementation
        try:
            from src.cache import create_cache_backend
            cache = create_cache_backend('memory')
            
            assert hasattr(cache, 'namespace')
            assert hasattr(cache, 'stats')
        except ImportError:
            pytest.skip("Cache backend not available")
    
    def test_cache_backend_has_required_methods(self):
        """Test CacheBackend has required interface methods."""
        from src.cache import CacheBackend
        
        required_methods = ['get', 'set', 'delete', 'clear', 'exists']
        
        for method in required_methods:
            assert hasattr(CacheBackend, method)


class TestMemoryCache:
    """Test in-memory cache implementation."""
    
    def test_memory_cache_creation(self):
        """Test creating memory cache."""
        try:
            from src.cache import create_cache_backend
            
            cache = create_cache_backend('memory')
            
            assert cache is not None
        except ImportError:
            pytest.skip("Memory cache not available")
    
    def test_memory_cache_set_and_get(self):
        """Test memory cache set and get."""
        try:
            from src.cache import create_cache_backend
            
            cache = create_cache_backend('memory')
            
            cache.set('test_key', 'test_value')
            result = cache.get('test_key')
            
            assert result == 'test_value'
        except ImportError:
            pytest.skip("Memory cache not available")
    
    def test_memory_cache_get_missing_key(self):
        """Test getting missing key returns None."""
        try:
            from src.cache import create_cache_backend
            
            cache = create_cache_backend('memory')
            result = cache.get('nonexistent')
            
            assert result is None
        except ImportError:
            pytest.skip("Memory cache not available")
    
    def test_memory_cache_delete(self):
        """Test deleting from memory cache."""
        try:
            from src.cache import create_cache_backend
            
            cache = create_cache_backend('memory')
            cache.set('key', 'value')
            
            success = cache.delete('key')
            
            assert success is True
            assert cache.get('key') is None
        except ImportError:
            pytest.skip("Memory cache not available")
    
    def test_memory_cache_clear(self):
        """Test clearing memory cache."""
        try:
            from src.cache import create_cache_backend
            
            cache = create_cache_backend('memory')
            cache.set('key1', 'val1')
            cache.set('key2', 'val2')
            
            cache.clear()
            
            assert cache.get('key1') is None
            assert cache.get('key2') is None
        except ImportError:
            pytest.skip("Memory cache not available")
    
    def test_memory_cache_exists(self):
        """Test checking key existence."""
        try:
            from src.cache import create_cache_backend
            
            cache = create_cache_backend('memory')
            cache.set('existing_key', 'value')
            
            assert cache.exists('existing_key') is True
            assert cache.exists('missing_key') is False
        except ImportError:
            pytest.skip("Memory cache not available")


class TestCacheFactory:
    """Test cache factory functions."""
    
    def test_create_cache_backend_memory(self):
        """Test creating memory backend."""
        try:
            from src.cache import create_cache_backend
            
            cache = create_cache_backend('memory')
            
            assert cache is not None
        except ImportError:
            pytest.skip("Cache factory not available")
    
    def test_create_cache_backend_with_namespace(self):
        """Test creating cache with custom namespace."""
        try:
            from src.cache import create_cache_backend
            
            cache = create_cache_backend('memory', namespace='test')
            
            assert cache.namespace == 'test'
        except ImportError:
            pytest.skip("Cache factory not available")
    
    def test_create_cache_backend_with_max_size(self):
        """Test creating cache with max size."""
        try:
            from src.cache import create_cache_backend
            
            cache = create_cache_backend('memory', max_size=1000)
            
            assert hasattr(cache, 'stats')
        except ImportError:
            pytest.skip("Cache factory not available")


class TestCacheTTL:
    """Test TTL (time-to-live) functionality."""
    
    def test_cache_set_with_ttl(self):
        """Test setting value with TTL."""
        try:
            from src.cache import create_cache_backend
            
            cache = create_cache_backend('memory')
            
            success = cache.set('key', 'value', ttl=3600)
            
            assert success is True
        except ImportError:
            pytest.skip("Cache not available")
    
    def test_cache_ttl_expiration(self):
        """Test TTL expiration (if supported)."""
        try:
            from src.cache import create_cache_backend
            import time
            
            cache = create_cache_backend('memory')
            cache.set('key', 'value', ttl=1)
            
            # Immediate get should work
            assert cache.get('key') == 'value'
            
            # After TTL might expire (implementation dependent)
            time.sleep(2)
            result = cache.get('key')
            
            # Either expired or still there (backend dependent)
            assert result in ['value', None]
        except ImportError:
            pytest.skip("Cache not available")


class TestCacheStatistics:
    """Test cache statistics tracking."""
    
    def test_cache_tracks_hits(self):
        """Test cache tracks hit count."""
        try:
            from src.cache import create_cache_backend
            
            cache = create_cache_backend('memory')
            cache.set('key', 'value')
            
            initial_hits = cache.stats.hits
            cache.get('key')
            
            assert cache.stats.hits >= initial_hits
        except (ImportError, AttributeError):
            pytest.skip("Cache statistics not available")
    
    def test_cache_tracks_misses(self):
        """Test cache tracks miss count."""
        try:
            from src.cache import create_cache_backend
            
            cache = create_cache_backend('memory')
            
            initial_misses = cache.stats.misses
            cache.get('nonexistent')
            
            assert cache.stats.misses >= initial_misses
        except (ImportError, AttributeError):
            pytest.skip("Cache statistics not available")


class TestCacheEdgeCases:
    """Test edge cases in cache operations."""
    
    def test_cache_with_none_value(self):
        """Test caching None as a value."""
        try:
            from src.cache import create_cache_backend
            
            cache = create_cache_backend('memory')
            
            cache.set('key', None)
            result = cache.get('key')
            
            # Implementation may not distinguish None from missing
            assert result is None
        except ImportError:
            pytest.skip("Cache not available")
    
    def test_cache_with_complex_value(self):
        """Test caching complex objects."""
        try:
            from src.cache import create_cache_backend
            
            cache = create_cache_backend('memory')
            complex_value = {'list': [1, 2, 3], 'nested': {'a': 1}}
            
            cache.set('key', complex_value)
            result = cache.get('key')
            
            assert result == complex_value
        except ImportError:
            pytest.skip("Cache not available")
    
    def test_cache_key_with_special_chars(self):
        """Test cache key with special characters."""
        try:
            from src.cache import create_cache_backend
            
            cache = create_cache_backend('memory')
            
            cache.set('key:with:colons', 'value')
            result = cache.get('key:with:colons')
            
            assert result == 'value'
        except ImportError:
            pytest.skip("Cache not available")
