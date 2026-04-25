"""Tests for RedisCache and DatabaseCache backends (fully mocked)."""

import pickle
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

# ---------------------------------------------------------------------------
# RedisCache
# ---------------------------------------------------------------------------

class TestRedisCacheInit:
    def test_init_success(self):
        mock_redis_mod = MagicMock()
        mock_client = MagicMock()
        mock_redis_mod.Redis.return_value = mock_client
        mock_client.ping.return_value = True

        with patch.dict("sys.modules", {"redis": mock_redis_mod}):
            from importlib import reload

            import src.cache.backends.redis_cache as rc_mod
            reload(rc_mod)
            cache = rc_mod.RedisCache(namespace="test")
            assert cache.namespace == "test"

    def test_init_import_error_raises(self):
        with patch.dict("sys.modules", {"redis": None}):
            from importlib import reload

            import src.cache.backends.redis_cache as rc_mod
            reload(rc_mod)
            with pytest.raises((ImportError, Exception)):
                rc_mod.RedisCache()

    def test_init_connection_failure_raises(self):
        mock_redis_mod = MagicMock()
        mock_client = MagicMock()
        mock_redis_mod.Redis.return_value = mock_client
        mock_client.ping.side_effect = ConnectionError("refused")

        with patch.dict("sys.modules", {"redis": mock_redis_mod}):
            from importlib import reload

            import src.cache.backends.redis_cache as rc_mod
            reload(rc_mod)
            with pytest.raises(Exception):
                rc_mod.RedisCache()


class TestRedisCacheOperations:
    """Test RedisCache operations using a pre-built mock client."""

    def _make_cache(self):
        mock_redis_mod = MagicMock()
        mock_client = MagicMock()
        mock_redis_mod.Redis.return_value = mock_client
        mock_client.ping.return_value = True

        with patch.dict("sys.modules", {"redis": mock_redis_mod}):
            from importlib import reload

            import src.cache.backends.redis_cache as rc_mod
            reload(rc_mod)
            cache = rc_mod.RedisCache(namespace="op_test")
            return cache, mock_client

    def test_set_calls_redis_set(self):
        cache, client = self._make_cache()
        client.set.return_value = True
        result = cache.set("k", "v")
        assert result is True
        assert cache.stats.sets == 1

    def test_set_with_ttl_calls_setex(self):
        cache, client = self._make_cache()
        cache.set("k", "v", ttl=60)
        client.setex.assert_called_once()

    def test_get_hit(self):
        cache, client = self._make_cache()
        client.get.return_value = pickle.dumps("cached_value")
        assert cache.get("k") == "cached_value"
        assert cache.stats.hits == 1

    def test_get_miss(self):
        cache, client = self._make_cache()
        client.get.return_value = None
        assert cache.get("k") is None
        assert cache.stats.misses == 1

    def test_get_error_returns_none(self):
        cache, client = self._make_cache()
        client.get.side_effect = Exception("conn lost")
        assert cache.get("k") is None

    def test_delete_existing_key(self):
        cache, client = self._make_cache()
        client.delete.return_value = 1
        assert cache.delete("k") is True
        assert cache.stats.deletes == 1

    def test_delete_nonexistent_key(self):
        cache, client = self._make_cache()
        client.delete.return_value = 0
        assert cache.delete("ghost") is False

    def test_delete_error_returns_false(self):
        cache, client = self._make_cache()
        client.delete.side_effect = Exception("boom")
        assert cache.delete("k") is False

    def test_exists_true(self):
        cache, client = self._make_cache()
        client.exists.return_value = 1
        assert cache.exists("k") is True

    def test_exists_false(self):
        cache, client = self._make_cache()
        client.exists.return_value = 0
        assert cache.exists("k") is False

    def test_exists_error_returns_false(self):
        cache, client = self._make_cache()
        client.exists.side_effect = Exception("err")
        assert cache.exists("k") is False

    def test_clear_removes_keys(self):
        cache, client = self._make_cache()
        client.scan_iter.return_value = [b"op_test:k1", b"op_test:k2"]
        assert cache.clear() is True
        client.delete.assert_called_once()

    def test_clear_no_keys(self):
        cache, client = self._make_cache()
        client.scan_iter.return_value = []
        assert cache.clear() is True

    def test_clear_error_returns_false(self):
        cache, client = self._make_cache()
        client.scan_iter.side_effect = Exception("boom")
        assert cache.clear() is False

    def test_get_stats_counts_keys(self):
        cache, client = self._make_cache()
        client.scan_iter.return_value = ["k1", "k2"]
        stats = cache.get_stats()
        assert stats.size == 2

    def test_get_stats_error_still_returns_stats(self):
        cache, client = self._make_cache()
        client.scan_iter.side_effect = Exception("err")
        stats = cache.get_stats()
        from src.cache.backends.base import CacheStats
        assert isinstance(stats, CacheStats)

    def test_set_error_returns_false(self):
        cache, client = self._make_cache()
        client.set.side_effect = Exception("conn err")
        assert cache.set("k", "v") is False


# ---------------------------------------------------------------------------
# DatabaseCache
# ---------------------------------------------------------------------------

class TestDatabaseCache:
    def _make_db(self):
        db = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        db.get_connection.return_value.__enter__ = MagicMock(return_value=conn)
        db.get_connection.return_value.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = None
        return db, conn, cursor

    def test_init_creates_cache(self):
        db, conn, cursor = self._make_db()
        from src.cache.backends.database_cache import DatabaseCache
        cache = DatabaseCache(db, table_name="test_cache")
        assert cache.table_name == "test_cache"

    def test_get_miss(self):
        db, conn, cursor = self._make_db()
        cursor.fetchone.return_value = None
        from src.cache.backends.database_cache import DatabaseCache
        cache = DatabaseCache(db)
        result = cache.get("missing query")
        assert result is None

    def test_get_hit(self):
        import json
        db, conn, cursor = self._make_db()
        cursor.fetchone.return_value = (json.dumps({"answer": 42}).encode("utf-8"), 0)
        from src.cache.backends.database_cache import DatabaseCache
        cache = DatabaseCache(db)
        result = cache.get("my query")
        assert result == {"answer": 42}

    def test_get_error_returns_none(self):
        db, conn, cursor = self._make_db()
        from src.cache.backends.database_cache import DatabaseCache
        cache = DatabaseCache(db)
        # Now make the cursor raise on execute to simulate a query error
        cursor.execute.side_effect = Exception("query error")
        result = cache.get("query that fails")
        assert result is None

    def test_set_success(self):
        db, conn, cursor = self._make_db()
        from src.cache.backends.database_cache import DatabaseCache
        cache = DatabaseCache(db)
        result = cache.set("q", {"data": 1})
        assert result is True

    def test_set_with_params_and_metadata(self):
        db, conn, cursor = self._make_db()
        from src.cache.backends.database_cache import DatabaseCache
        cache = DatabaseCache(db)
        result = cache.set("q", "result", params={"k": "v"}, ttl=300, metadata={"src": "test"})
        assert result is True

    def test_set_error_returns_false(self):
        db, conn, cursor = self._make_db()
        from src.cache.backends.database_cache import DatabaseCache
        cache = DatabaseCache(db)
        cursor.execute.side_effect = Exception("conn err")
        assert cache.set("k", "v") is False

    def test_delete_found(self):
        db, conn, cursor = self._make_db()
        cursor.rowcount = 1
        from src.cache.backends.database_cache import DatabaseCache
        cache = DatabaseCache(db)
        result = cache.delete("q")
        assert result is True

    def test_delete_not_found(self):
        db, conn, cursor = self._make_db()
        cursor.rowcount = 0
        from src.cache.backends.database_cache import DatabaseCache
        cache = DatabaseCache(db)
        result = cache.delete("q")
        assert result is False

    def test_delete_error_returns_false(self):
        db, conn, cursor = self._make_db()
        from src.cache.backends.database_cache import DatabaseCache
        cache = DatabaseCache(db)
        cursor.execute.side_effect = Exception("delete error")
        assert cache.delete("q") is False

    def test_clear_expired_success(self):
        db, conn, cursor = self._make_db()
        cursor.rowcount = 3
        from src.cache.backends.database_cache import DatabaseCache
        cache = DatabaseCache(db)
        result = cache.clear_expired()
        assert result == 3

    def test_clear_expired_error_returns_zero(self):
        db, conn, cursor = self._make_db()
        from src.cache.backends.database_cache import DatabaseCache
        cache = DatabaseCache(db)
        cursor.execute.side_effect = Exception("err")
        assert cache.clear_expired() == 0

    def test_make_cache_key_is_deterministic(self):
        db, conn, cursor = self._make_db()
        from src.cache.backends.database_cache import DatabaseCache
        cache = DatabaseCache(db)
        k1 = cache._make_cache_key("hello", {"a": 1})
        k2 = cache._make_cache_key("hello", {"a": 1})
        assert k1 == k2
        assert len(k1) == 64

    def test_make_cache_key_different_queries_differ(self):
        db, conn, cursor = self._make_db()
        from src.cache.backends.database_cache import DatabaseCache
        cache = DatabaseCache(db)
        k1 = cache._make_cache_key("query one")
        k2 = cache._make_cache_key("query two")
        assert k1 != k2


# ---------------------------------------------------------------------------
# src/cache/__init__.py RedisCache (JSON serialization)
# ---------------------------------------------------------------------------

class TestCacheInitRedisCache:
    """Tests for the RedisCache in src/cache/__init__.py, which uses JSON."""

    def _make_cache(self):
        mock_redis_mod = MagicMock()
        mock_client = MagicMock()
        mock_redis_mod.Redis.return_value = mock_client
        mock_client.ping.return_value = True

        with patch.dict("sys.modules", {"redis": mock_redis_mod}):
            from importlib import reload
            import src.cache as cache_mod
            reload(cache_mod)
            cache = cache_mod.RedisCache(namespace="init_test")
            return cache, mock_client

    def test_set_serializes_as_json(self):
        import json
        cache, client = self._make_cache()
        client.set.return_value = True
        result = cache.set("key", {"val": 42})
        assert result is True
        call_args = client.set.call_args[0]
        assert json.loads(call_args[1].decode("utf-8")) == {"val": 42}

    def test_get_deserializes_from_json(self):
        import json
        cache, client = self._make_cache()
        client.get.return_value = json.dumps("hello").encode("utf-8")
        result = cache.get("key")
        assert result == "hello"
        assert cache.stats.hits == 1
