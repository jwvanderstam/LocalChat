"""Unit tests for DatabaseCache (L3 persistent cache tier) with mocked db_client."""

from unittest.mock import MagicMock


def _make_cache():
    """Return (cache, mock_db, mock_conn, mock_cur) with no real DB connections."""
    mock_cur = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    mock_db = MagicMock()
    mock_db.get_connection.return_value.__enter__.return_value = mock_conn

    from src.cache.backends.database_cache import DatabaseCache

    cache = DatabaseCache(mock_db, table_name="test_cache", default_ttl=3600)

    # Reset call history accumulated by __init__ so test assertions start clean
    mock_cur.reset_mock()
    mock_conn.reset_mock()
    return cache, mock_db, mock_conn, mock_cur


class TestDatabaseCacheInit:
    def test_table_name_stored(self):
        cache, _, _, _ = _make_cache()
        assert cache.table_name == "test_cache"

    def test_default_ttl_stored(self):
        cache, _, _, _ = _make_cache()
        assert cache.default_ttl == 3600

    def test_init_calls_get_connection_to_ensure_table(self):
        mock_cur = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_db = MagicMock()
        mock_db.get_connection.return_value.__enter__.return_value = mock_conn

        from src.cache.backends.database_cache import DatabaseCache

        DatabaseCache(mock_db, table_name="t")
        assert mock_db.get_connection.called


class TestMakeCacheKey:
    def test_key_is_64_chars(self):
        cache, _, _, _ = _make_cache()
        assert len(cache._make_cache_key("hello world")) == 64

    def test_same_query_same_key(self):
        cache, _, _, _ = _make_cache()
        assert cache._make_cache_key("foo") == cache._make_cache_key("foo")

    def test_different_queries_different_keys(self):
        cache, _, _, _ = _make_cache()
        assert cache._make_cache_key("foo") != cache._make_cache_key("bar")

    def test_params_affect_key(self):
        cache, _, _, _ = _make_cache()
        k1 = cache._make_cache_key("q", {"k": "v1"})
        k2 = cache._make_cache_key("q", {"k": "v2"})
        assert k1 != k2

    def test_query_case_normalised(self):
        cache, _, _, _ = _make_cache()
        assert cache._make_cache_key("HELLO") == cache._make_cache_key("hello")


class TestDatabaseCacheGet:
    def test_returns_none_on_miss(self):
        cache, _, _, mock_cur = _make_cache()
        mock_cur.fetchone.return_value = None
        assert cache.get("query text") is None

    def test_returns_deserialized_value_on_hit(self):
        import json
        cache, _, _, mock_cur = _make_cache()
        payload = {"answer": 42}
        mock_cur.fetchone.return_value = (json.dumps(payload).encode("utf-8"), 5)
        assert cache.get("query text") == payload

    def test_returns_none_on_db_exception(self):
        cache, _, _, mock_cur = _make_cache()
        mock_cur.execute.side_effect = RuntimeError("db down")
        assert cache.get("query text") is None


class TestDatabaseCacheSet:
    def test_returns_true_on_success(self):
        cache, _, _, _ = _make_cache()
        assert cache.set("q", {"data": 1}) is True

    def test_returns_false_on_db_exception(self):
        cache, _, _, mock_cur = _make_cache()
        mock_cur.execute.side_effect = RuntimeError("disk full")
        assert cache.set("q", {"data": 1}) is False

    def test_custom_ttl_accepted(self):
        cache, _, _, _ = _make_cache()
        assert cache.set("q", "value", ttl=7200) is True


class TestDatabaseCacheDelete:
    def test_returns_true_when_row_deleted(self):
        cache, _, _, mock_cur = _make_cache()
        mock_cur.rowcount = 1
        assert cache.delete("query text") is True

    def test_returns_false_when_no_rows_deleted(self):
        cache, _, _, mock_cur = _make_cache()
        mock_cur.rowcount = 0
        assert cache.delete("query text") is False


class TestDatabaseCacheClearExpired:
    def test_returns_count_of_deleted_rows(self):
        cache, _, _, mock_cur = _make_cache()
        mock_cur.rowcount = 7
        assert cache.clear_expired() == 7

    def test_returns_zero_on_exception(self):
        cache, _, _, mock_cur = _make_cache()
        mock_cur.execute.side_effect = RuntimeError("timeout")
        assert cache.clear_expired() == 0


class TestDatabaseCacheWarmCache:
    def test_warms_all_valid_queries(self):
        cache, _, _, _ = _make_cache()
        queries = [("q1", "r1"), ("q2", "r2"), ("q3", "r3")]
        assert cache.warm_cache(queries) == 3


class TestCreateDbCache:
    def test_factory_creates_instance_with_correct_ttl(self):
        mock_cur = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_db = MagicMock()
        mock_db.get_connection.return_value.__enter__.return_value = mock_conn

        from src.cache.backends.database_cache import DatabaseCache, create_db_cache

        cache = create_db_cache(mock_db, ttl=1800)
        assert isinstance(cache, DatabaseCache)
        assert cache.default_ttl == 1800
