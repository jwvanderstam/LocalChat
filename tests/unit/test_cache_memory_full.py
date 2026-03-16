# -*- coding: utf-8 -*-
"""Tests for in-memory cache backend and base classes."""

import time
import pytest
from src.cache.backends.base import CacheStats, CacheBackend
from src.cache.backends.memory import MemoryCache


# ---------------------------------------------------------------------------
# CacheStats
# ---------------------------------------------------------------------------

class TestCacheStats:
    def test_hit_rate_zero_when_no_ops(self):
        s = CacheStats()
        assert s.hit_rate == 0.0

    def test_hit_rate_calculation(self):
        s = CacheStats(hits=3, misses=1)
        assert s.hit_rate == 75.0

    def test_usage_percent_zero_max_size(self):
        s = CacheStats(size=5, max_size=0)
        assert s.usage_percent == 0.0

    def test_usage_percent_calculation(self):
        s = CacheStats(size=50, max_size=100)
        assert s.usage_percent == 50.0

    def test_to_dict_has_all_keys(self):
        s = CacheStats(hits=2, misses=1, sets=3, deletes=1, evictions=0, size=2, max_size=10)
        d = s.to_dict()
        for key in ('hits', 'misses', 'sets', 'deletes', 'evictions', 'size', 'max_size', 'hit_rate', 'usage'):
            assert key in d

    def test_to_dict_formats_rates_as_strings(self):
        s = CacheStats(hits=1, misses=1)
        d = s.to_dict()
        assert '%' in d['hit_rate']
        assert '%' in d['usage']


# ---------------------------------------------------------------------------
# CacheBackend (make_key / hash_key via MemoryCache)
# ---------------------------------------------------------------------------

class TestCacheBackend:
    def setup_method(self):
        self.cache = MemoryCache(namespace="test")

    def test_make_key_includes_namespace(self):
        key = self.cache.make_key("foo")
        assert key.startswith("test:")

    def test_make_key_multiple_parts(self):
        key = self.cache.make_key("a", "b", "c")
        assert key == "test:a:b:c"

    def test_hash_key_is_hex_string(self):
        h = self.cache.hash_key("hello world")
        assert len(h) == 64
        int(h, 16)  # must be valid hex


# ---------------------------------------------------------------------------
# MemoryCache – basic operations
# ---------------------------------------------------------------------------

class TestMemoryCacheBasic:
    def setup_method(self):
        self.cache = MemoryCache(namespace="tests", max_size=5)

    def test_set_and_get(self):
        assert self.cache.set("key1", "value1") is True
        assert self.cache.get("key1") == "value1"

    def test_get_missing_key_returns_none(self):
        assert self.cache.get("nonexistent") is None

    def test_delete_existing_key(self):
        self.cache.set("del_me", 42)
        assert self.cache.delete("del_me") is True
        assert self.cache.get("del_me") is None

    def test_delete_nonexistent_key_returns_false(self):
        assert self.cache.delete("ghost") is False

    def test_exists_returns_true_for_present_key(self):
        self.cache.set("present", "yes")
        assert self.cache.exists("present") is True

    def test_exists_returns_false_for_absent_key(self):
        assert self.cache.exists("absent") is False

    def test_clear_removes_all_namespace_keys(self):
        self.cache.set("a", 1)
        self.cache.set("b", 2)
        assert self.cache.clear() is True
        assert self.cache.get("a") is None
        assert self.cache.get("b") is None

    def test_set_various_value_types(self):
        self.cache.set("list", [1, 2, 3])
        self.cache.set("dict", {"x": 1})
        self.cache.set("none_val", None)
        assert self.cache.get("list") == [1, 2, 3]
        assert self.cache.get("dict") == {"x": 1}
        assert self.cache.get("none_val") is None


class TestMemoryCacheTTL:
    def test_ttl_expiry(self):
        cache = MemoryCache(namespace="ttl_test")
        cache.set("temp", "data", ttl=1)
        assert cache.get("temp") == "data"
        time.sleep(1.1)
        assert cache.get("temp") is None

    def test_ttl_expiry_in_exists(self):
        cache = MemoryCache(namespace="ttl_exists")
        cache.set("temp2", "data", ttl=1)
        assert cache.exists("temp2") is True
        time.sleep(1.1)
        assert cache.exists("temp2") is False

    def test_no_ttl_does_not_expire_quickly(self):
        cache = MemoryCache(namespace="no_ttl")
        cache.set("persist", "value")
        time.sleep(0.1)
        assert cache.get("persist") == "value"


class TestMemoryCacheEviction:
    def test_lru_eviction_at_max_size(self):
        cache = MemoryCache(namespace="evict_test", max_size=3)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        # Access "a" to make it recently used
        cache.get("a")
        # Adding "d" should evict "b" (LRU)
        cache.set("d", 4)
        assert cache.get("d") == 4
        stats = cache.get_stats()
        assert stats.evictions >= 1

    def test_eviction_increments_eviction_counter(self):
        cache = MemoryCache(namespace="evict_counter", max_size=2)
        cache.set("x", 1)
        cache.set("y", 2)
        cache.set("z", 3)
        assert cache.get_stats().evictions >= 1


class TestMemoryCacheStats:
    def setup_method(self):
        self.cache = MemoryCache(namespace="stats_test")

    def test_get_stats_returns_cache_stats(self):
        stats = self.cache.get_stats()
        assert isinstance(stats, CacheStats)

    def test_hits_incremented_on_get(self):
        self.cache.set("k", "v")
        self.cache.get("k")
        assert self.cache.get_stats().hits == 1

    def test_misses_incremented_on_missing_get(self):
        self.cache.get("missing")
        assert self.cache.get_stats().misses == 1

    def test_sets_incremented_on_set(self):
        self.cache.set("k2", "v2")
        assert self.cache.get_stats().sets == 1

    def test_deletes_incremented_on_delete(self):
        self.cache.set("k3", "v3")
        self.cache.delete("k3")
        assert self.cache.get_stats().deletes == 1

    def test_stats_size_reflects_cache_contents(self):
        self.cache.set("s1", 1)
        self.cache.set("s2", 2)
        assert self.cache.get_stats().size == 2

    def test_max_size_stored_in_stats(self):
        c = MemoryCache(namespace="ms", max_size=50)
        assert c.get_stats().max_size == 50

    def test_overwrite_existing_key_does_not_evict(self):
        cache = MemoryCache(namespace="overwrite", max_size=2)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("a", 99)  # overwrite, no new slot needed
        assert cache.get("a") == 99
        assert cache.get_stats().evictions == 0
