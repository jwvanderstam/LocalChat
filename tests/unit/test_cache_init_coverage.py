# -*- coding: utf-8 -*-
"""Coverage for src/cache/__init__.py (separate from src/cache/backends/)."""

import time
import pickle
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# CacheBackend.hash_key (line 141)
# ---------------------------------------------------------------------------

class TestCacheInitHashKey:
    def test_hash_key_returns_64_char_hex(self):
        from src.cache import MemoryCache
        c = MemoryCache()
        h = c.hash_key("hello world")
        assert len(h) == 64
        int(h, 16)  # must be valid hex

    def test_hash_key_is_deterministic(self):
        from src.cache import MemoryCache
        c = MemoryCache()
        assert c.hash_key("same") == c.hash_key("same")

    def test_hash_key_differs_for_different_inputs(self):
        from src.cache import MemoryCache
        c = MemoryCache()
        assert c.hash_key("a") != c.hash_key("b")


# ---------------------------------------------------------------------------
# MemoryCache (src/cache/__init__.py version) — TTL, delete, exists
# ---------------------------------------------------------------------------

class TestCacheInitMemoryCache:
    def setup_method(self):
        from src.cache import MemoryCache
        self.cache = MemoryCache(namespace="ci_test", max_size=10)

    def test_set_with_ttl_stores_value(self):
        assert self.cache.set("k", "v", ttl=60) is True
        assert self.cache.get("k") == "v"

    def test_ttl_expiry_returns_none(self):
        self.cache.set("exp", "data", ttl=1)
        time.sleep(1.1)
        assert self.cache.get("exp") is None

    def test_delete_removes_key(self):
        self.cache.set("del", 42)
        assert self.cache.delete("del") is True
        assert self.cache.get("del") is None

    def test_delete_updates_stats(self):
        self.cache.set("d2", "v")
        self.cache.delete("d2")
        assert self.cache.stats.deletes == 1
        assert self.cache.stats.size == 0

    def test_exists_expired_returns_false(self):
        self.cache.set("ex", "v", ttl=1)
        time.sleep(1.1)
        assert self.cache.exists("ex") is False

    def test_exists_valid_returns_true(self):
        self.cache.set("ev", "v")
        assert self.cache.exists("ev") is True


# ---------------------------------------------------------------------------
# create_cache_backend factory
# ---------------------------------------------------------------------------

class TestCreateCacheBackend:
    def test_memory_backend_returns_memory_cache(self):
        from src.cache import create_cache_backend, MemoryCache
        cache = create_cache_backend("memory", namespace="test")
        assert isinstance(cache, MemoryCache)

    def test_memory_backend_with_max_size(self):
        from src.cache import create_cache_backend, MemoryCache
        cache = create_cache_backend("memory", max_size=50)
        assert cache.max_size == 50

    def test_unknown_backend_raises_value_error(self):
        from src.cache import create_cache_backend
        with pytest.raises(ValueError):
            create_cache_backend("nonexistent_backend")

    def test_redis_fallback_to_memory_on_failure(self):
        from src.cache import create_cache_backend, MemoryCache
        with patch('src.cache.RedisCache', side_effect=Exception("redis down")):
            cache = create_cache_backend("redis", namespace="test")
        assert isinstance(cache, MemoryCache)


# ---------------------------------------------------------------------------
# RedisCache (src/cache/__init__.py version) — mocked
# ---------------------------------------------------------------------------

class TestCacheInitRedisCache:
    def _make_redis_cache(self):
        mock_redis_mod = MagicMock()
        mock_client = MagicMock()
        mock_redis_mod.Redis.return_value = mock_client
        mock_client.ping.return_value = True

        with patch.dict('sys.modules', {'redis': mock_redis_mod}):
            from importlib import reload
            import src.cache as cache_mod
            reload(cache_mod)
            cache = cache_mod.RedisCache(namespace="rt")
            return cache, mock_client

    def test_get_hit(self):
        cache, client = self._make_redis_cache()
        client.get.return_value = pickle.dumps("value")
        assert cache.get("k") == "value"
        assert cache.stats.hits == 1

    def test_get_miss(self):
        cache, client = self._make_redis_cache()
        client.get.return_value = None
        assert cache.get("k") is None
        assert cache.stats.misses == 1

    def test_get_error_returns_none(self):
        cache, client = self._make_redis_cache()
        client.get.side_effect = Exception("err")
        assert cache.get("k") is None

    def test_set_with_ttl(self):
        cache, client = self._make_redis_cache()
        cache.set("k", "v", ttl=60)
        client.setex.assert_called_once()
        assert cache.stats.sets == 1

    def test_set_without_ttl(self):
        cache, client = self._make_redis_cache()
        cache.set("k", "v")
        client.set.assert_called_once()

    def test_set_error_returns_false(self):
        cache, client = self._make_redis_cache()
        client.set.side_effect = Exception("err")
        assert cache.set("k", "v") is False

    def test_delete_found(self):
        cache, client = self._make_redis_cache()
        client.delete.return_value = 1
        assert cache.delete("k") is True

    def test_delete_not_found(self):
        cache, client = self._make_redis_cache()
        client.delete.return_value = 0
        assert cache.delete("k") is False

    def test_delete_error_returns_false(self):
        cache, client = self._make_redis_cache()
        client.delete.side_effect = Exception("err")
        assert cache.delete("k") is False

    def test_exists_true(self):
        cache, client = self._make_redis_cache()
        client.exists.return_value = 1
        assert cache.exists("k") is True

    def test_exists_error_returns_false(self):
        cache, client = self._make_redis_cache()
        client.exists.side_effect = Exception("err")
        assert cache.exists("k") is False

    def test_clear_removes_keys(self):
        cache, client = self._make_redis_cache()
        client.scan_iter.return_value = [b"rt:k1"]
        assert cache.clear() is True
        client.delete.assert_called_once()

    def test_clear_error_returns_false(self):
        cache, client = self._make_redis_cache()
        client.scan_iter.side_effect = Exception("err")
        assert cache.clear() is False

    def test_get_stats_counts_keys(self):
        cache, client = self._make_redis_cache()
        client.info.return_value = {}
        client.scan_iter.return_value = ["k1", "k2"]
        stats = cache.get_stats()
        assert stats.size == 2

    def test_get_stats_error_still_returns_stats(self):
        cache, client = self._make_redis_cache()
        client.info.side_effect = Exception("err")
        client.scan_iter.side_effect = Exception("err")
        from src.cache import CacheStats
        stats = cache.get_stats()
        assert isinstance(stats, CacheStats)
