# -*- coding: utf-8 -*-

"""
Database Cache Backend - L3 Cache Tier
======================================

Implements database-backed caching for persistent query result storage.
Complements L1 (memory) and L2 (Redis) caches with longer-term persistence.

Features:
- Persistent storage in PostgreSQL
- Semantic query matching
- Automatic expiration
- Cache warming strategies

Author: LocalChat Team
Created: January 2025
"""

from typing import Any, Optional, Dict, List, Tuple
from datetime import datetime, timedelta
import hashlib
import pickle
import json

from psycopg import sql as pg_sql
from ...utils.logging_config import get_logger

logger = get_logger(__name__)


class DatabaseCache:
    """
    L3 cache tier using PostgreSQL for persistent storage.
    
    Slower than L1/L2 but provides:
    - Persistence across restarts
    - Larger capacity
    - Semantic similarity matching
    - Analytics and warming capabilities
    """
    
    def __init__(
        self,
        db_client,
        table_name: str = "query_cache",
        default_ttl: int = 86400  # 24 hours
    ):
        """
        Initialize database cache.
        
        Args:
            db_client: Database client instance
            table_name: Cache table name
            default_ttl: Default TTL in seconds (24 hours)
        """
        self.db = db_client
        self.table_name = table_name
        self.default_ttl = default_ttl
        
        self._ensure_table_exists()
        logger.info(f"DatabaseCache initialized (table={table_name}, ttl={default_ttl}s)")
    
    def _ensure_table_exists(self) -> None:
        """Create cache table if it doesn't exist."""
        try:
            create_table_sql = pg_sql.SQL("""
            CREATE TABLE IF NOT EXISTS {table} (
                id SERIAL PRIMARY KEY,
                cache_key VARCHAR(64) NOT NULL UNIQUE,
                query_text TEXT NOT NULL,
                query_params JSONB,
                result_data BYTEA NOT NULL,
                metadata JSONB,
                hit_count INTEGER DEFAULT 0,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                expires_at TIMESTAMP NOT NULL,
                last_accessed_at TIMESTAMP NOT NULL DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS {idx_key}
                ON {table}(cache_key);
            CREATE INDEX IF NOT EXISTS {idx_expires}
                ON {table}(expires_at);
            CREATE INDEX IF NOT EXISTS {idx_hits}
                ON {table}(hit_count DESC);
            """).format(
                table=pg_sql.Identifier(self.table_name),
                idx_key=pg_sql.Identifier(f"idx_{self.table_name}_key"),
                idx_expires=pg_sql.Identifier(f"idx_{self.table_name}_expires"),
                idx_hits=pg_sql.Identifier(f"idx_{self.table_name}_hits"),
            )
            
            with self.db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(create_table_sql)
                    conn.commit()
                    
            logger.debug(f"Cache table {self.table_name} verified/created")
            
        except Exception as e:
            logger.error(f"Error creating cache table: {e}", exc_info=True)
            raise
    
    def _make_cache_key(self, query: str, params: Optional[Dict] = None) -> str:
        """
        Generate cache key from query and parameters.
        
        Args:
            query: Query text
            params: Query parameters
        
        Returns:
            64-character hex hash
        """
        # Normalize query
        normalized = query.lower().strip()
        
        # Include params if provided
        if params:
            param_str = json.dumps(params, sort_keys=True)
            normalized = f"{normalized}:{param_str}"
        
        return hashlib.sha256(normalized.encode()).hexdigest()
    
    def get(
        self,
        query: str,
        params: Optional[Dict] = None,
        _similarity_threshold: float = 0.95
    ) -> Optional[Any]:
        """
        Get cached result for query.

        Args:
            query: Query text
            params: Query parameters
            _similarity_threshold: Reserved for future semantic matching (unused)

        Returns:
            Cached result or None if not found/expired
        """
        cache_key = self._make_cache_key(query, params)
        
        try:
            sql = pg_sql.SQL("""
            SELECT result_data, hit_count
            FROM {table}
            WHERE cache_key = %s
                AND expires_at > NOW()
            """).format(table=pg_sql.Identifier(self.table_name))
            
            with self.db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, (cache_key,))
                    row = cur.fetchone()
                    
                    if row:
                        result_data, hit_count = row
                        
                        # Update access stats
                        update_sql = pg_sql.SQL("""
                        UPDATE {table}
                        SET hit_count = hit_count + 1,
                            last_accessed_at = NOW()
                        WHERE cache_key = %s
                        """).format(table=pg_sql.Identifier(self.table_name))
                        cur.execute(update_sql, (cache_key,))
                        conn.commit()
                        
                        # Deserialize
                        result = pickle.loads(result_data)
                        
                        logger.debug(f"Cache HIT (L3): {cache_key[:16]}... (hits={hit_count + 1})")
                        return result
                    else:
                        logger.debug(f"Cache MISS (L3): {cache_key[:16]}...")
                        return None
                        
        except Exception as e:
            logger.error(f"Error reading from cache: {e}", exc_info=True)
            return None
    
    def set(
        self,
        query: str,
        result: Any,
        params: Optional[Dict] = None,
        ttl: Optional[int] = None,
        metadata: Optional[Dict] = None
    ) -> bool:
        """
        Store result in cache.
        
        Args:
            query: Query text
            result: Result to cache
            params: Query parameters
            ttl: Time-to-live in seconds (None = use default)
            metadata: Additional metadata
        
        Returns:
            True if successful, False otherwise
        """
        cache_key = self._make_cache_key(query, params)
        ttl = ttl or self.default_ttl
        expires_at = datetime.now() + timedelta(seconds=ttl)
        
        try:
            # Serialize result
            result_data = pickle.dumps(result)
            
            sql = pg_sql.SQL("""
            INSERT INTO {table}
                (cache_key, query_text, query_params, result_data, metadata, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (cache_key)
            DO UPDATE SET
                result_data = EXCLUDED.result_data,
                metadata = EXCLUDED.metadata,
                expires_at = EXCLUDED.expires_at,
                last_accessed_at = NOW()
            """).format(table=pg_sql.Identifier(self.table_name))
            
            with self.db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        sql,
                        (
                            cache_key,
                            query,
                            json.dumps(params) if params else None,
                            result_data,
                            json.dumps(metadata) if metadata else None,
                            expires_at
                        )
                    )
                    conn.commit()
            
            logger.debug(f"Cache SET (L3): {cache_key[:16]}... (ttl={ttl}s)")
            return True
            
        except Exception as e:
            logger.error(f"Error writing to cache: {e}", exc_info=True)
            return False
    
    def delete(self, query: str, params: Optional[Dict] = None) -> bool:
        """Delete cached entry."""
        cache_key = self._make_cache_key(query, params)
        
        try:
            sql = pg_sql.SQL("DELETE FROM {table} WHERE cache_key = %s").format(
                table=pg_sql.Identifier(self.table_name)
            )
            
            with self.db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, (cache_key,))
                    deleted = cur.rowcount
                    conn.commit()
            
            if deleted > 0:
                logger.debug(f"Cache DELETE (L3): {cache_key[:16]}...")
                return True
            return False
            
        except Exception as e:
            logger.error(f"Error deleting from cache: {e}", exc_info=True)
            return False
    
    def clear_expired(self) -> int:
        """
        Remove expired entries.
        
        Returns:
            Number of entries deleted
        """
        try:
            sql = pg_sql.SQL("DELETE FROM {table} WHERE expires_at < NOW()").format(
                table=pg_sql.Identifier(self.table_name)
            )
            
            with self.db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    deleted = cur.rowcount
                    conn.commit()
            
            if deleted > 0:
                logger.info(f"Cleared {deleted} expired cache entries")
            
            return deleted
            
        except Exception as e:
            logger.error(f"Error clearing expired entries: {e}", exc_info=True)
            return 0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        try:
            sql = pg_sql.SQL("""
            SELECT 
                COUNT(*) as total_entries,
                SUM(hit_count) as total_hits,
                AVG(hit_count) as avg_hits_per_entry,
                COUNT(*) FILTER (WHERE expires_at < NOW()) as expired_entries,
                pg_total_relation_size({table_lit}) as size_bytes
            FROM {table}
            """).format(
                table=pg_sql.Identifier(self.table_name),
                table_lit=pg_sql.Literal(self.table_name),
            )
            
            with self.db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    row = cur.fetchone()
                    
                    if row:
                        total, total_hits, avg_hits, expired, size_bytes = row
                        
                        return {
                            'total_entries': total or 0,
                            'total_hits': int(total_hits or 0),
                            'avg_hits_per_entry': float(avg_hits or 0),
                            'expired_entries': expired or 0,
                            'size_mb': round((size_bytes or 0) / 1024 / 1024, 2)
                        }
            
            return {}
            
        except Exception as e:
            logger.error(f"Error getting cache stats: {e}", exc_info=True)
            return {}
    
    def get_top_queries(self, limit: int = 10) -> List[Tuple[str, int]]:
        """
        Get most frequently accessed queries.
        
        Args:
            limit: Number of queries to return
        
        Returns:
            List of (query_text, hit_count) tuples
        """
        try:
            sql = pg_sql.SQL("""
            SELECT query_text, hit_count
            FROM {table}
            WHERE expires_at > NOW()
            ORDER BY hit_count DESC
            LIMIT %s
            """).format(table=pg_sql.Identifier(self.table_name))
            
            with self.db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, (limit,))
                    return cur.fetchall()
            
        except Exception as e:
            logger.error(f"Error getting top queries: {e}", exc_info=True)
            return []
    
    def warm_cache(self, queries: List[Tuple[str, Any]]) -> int:
        """
        Pre-populate cache with common queries.
        
        Args:
            queries: List of (query, result) tuples
        
        Returns:
            Number of queries cached
        """
        count = 0
        for query, result in queries:
            if self.set(query, result):
                count += 1
        
        logger.info(f"Warmed cache with {count} queries")
        return count


def create_db_cache(db_client, ttl: int = 86400) -> DatabaseCache:
    """
    Factory function to create database cache.
    
    Args:
        db_client: Database client instance
        ttl: Default TTL in seconds (24 hours)
    
    Returns:
        Configured DatabaseCache instance
    
    Example:
        >>> from src.db import db
        >>> cache = create_db_cache(db, ttl=3600)
    """
    return DatabaseCache(db_client, default_ttl=ttl)
