"""
Database Connection Module
==========================

Manages PostgreSQL connection pooling, pgvector type adapters,
and database/schema initialisation.
"""

import socket
from contextlib import contextmanager
from typing import Generator, List, Optional, Tuple, Union

import numpy as np
import psycopg
from psycopg import sql
from psycopg.adapt import Dumper, Loader
from psycopg_pool import ConnectionPool

from .. import config
from ..utils.logging_config import get_logger

logger = get_logger(__name__)

_PG_TRANSACTION_IDLE = 0    # psycopg TransactionStatus.IDLE
_PG_TRANSACTION_INTRANS = 2  # psycopg TransactionStatus.INTRANS


# ============================================================================
# CUSTOM EXCEPTIONS
# ============================================================================

class DatabaseUnavailableError(Exception):
    """
    Raised when database operations are attempted without an active connection.

    This occurs when the application is running in degraded mode
    (PostgreSQL unavailable).
    """
    pass


# ============================================================================
# PGVECTOR TYPE ADAPTERS FOR PSYCOPG3
# ============================================================================

class VectorDumper(Dumper):
    """Dumper for pgvector vector type."""

    def dump(self, obj):
        if hasattr(obj, 'tolist'):
            obj = obj.tolist()
        values_str = ','.join(f'{float(v):.6g}' for v in obj)
        return f'[{values_str}]'.encode()


class VectorLoader(Loader):
    """Loader for pgvector vector type."""

    def load(self, data):
        if isinstance(data, memoryview):
            data = bytes(data)
        if isinstance(data, bytes):
            data = data.decode('utf-8')
        data_str = data.strip()
        if data_str.startswith('[') and data_str.endswith(']'):  # type: ignore
            data_str = data_str[1:-1]
            if data_str:
                return [float(x) for x in data_str.split(',')]  # type: ignore
        return []


def register_vector_types(conn) -> None:
    """Register pgvector type adapters for a connection."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT oid FROM pg_type WHERE typname = 'vector'")
            result = cur.fetchone()
            if result:
                vector_oid = result[0]
                conn.adapters.register_dumper(list, VectorDumper)
                conn.adapters.register_dumper(np.ndarray, VectorDumper)
                conn.adapters.register_loader(vector_oid, VectorLoader)
                logger.debug(f"Registered pgvector type adapters (OID: {vector_oid})")
            else:
                logger.warning("pgvector type 'vector' not found in database")
    except Exception as e:
        logger.error(f"Failed to register vector type adapters: {e}", exc_info=True)


# ============================================================================
# DATABASE CONNECTION CLASS
# ============================================================================

class DatabaseConnection:
    """
    Manages the PostgreSQL connection pool and schema initialisation.

    Attributes:
        connection_pool: psycopg connection pool
        is_connected: Connection status flag
    """

    def __init__(self) -> None:
        self.connection_pool: ConnectionPool | None = None
        self.is_connected: bool = False
        logger.info("Database manager initialized")

    @staticmethod
    def check_server_availability(host: str, port: int, timeout: float = 2.0) -> tuple[bool, str]:
        """Fast TCP check that PostgreSQL is reachable before attempting a full connection."""
        logger.debug(f"Checking if PostgreSQL server is available at {host}:{port}")
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            if result == 0:
                logger.debug(f"PostgreSQL server is reachable at {host}:{port}")
                return True, f"PostgreSQL server is reachable at {host}:{port}"
            error_msg = (
                f"PostgreSQL server is NOT reachable at {host}:{port}\n"
                "  Please ensure:\n"
                "     1. PostgreSQL is installed\n"
                "     2. PostgreSQL service is running\n"
                f"     3. Server is listening on {host}:{port}\n"
                "  Quick fix:\n"
                "     - Windows: Start 'postgresql-x64-XX' service in Services\n"
                "     - Linux: sudo systemctl start postgresql\n"
                "     - macOS: brew services start postgresql\n"
                "     - Docker: docker start postgres-container"
            )
            logger.error(error_msg)
            return False, error_msg
        except socket.gaierror:
            error_msg = (
                f"Cannot resolve hostname '{host}'\n"
                "  Check your database configuration in config.py\n"
                f"  Current setting: PG_HOST = '{host}'"
            )
            logger.error(error_msg)
            return False, error_msg
        except TimeoutError:
            error_msg = (
                f"Connection to PostgreSQL at {host}:{port} timed out\n"
                "  Server may be unresponsive or firewalled\n"
                "  Check network connectivity and firewall rules"
            )
            logger.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"Unexpected error checking PostgreSQL availability: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass

    @staticmethod
    def _embedding_to_pg_array(embedding: Union[list[float], 'np.ndarray']) -> str:
        """Convert a Python list/numpy array to a PostgreSQL vector literal."""
        if isinstance(embedding, np.ndarray):
            embedding = embedding.tolist()
        values_str = ','.join(f'{float(v):.6g}' for v in embedding)
        return f'[{values_str}]'

    def initialize(self) -> tuple[bool, str]:
        """
        Initialise the connection pool and create the database/schema if needed.

        Returns:
            Tuple of (success, message)
        """
        try:
            logger.info("Initializing database connection pool")
            logger.info(f"Checking PostgreSQL server availability at {config.PG_HOST}:{config.PG_PORT}...")
            available, availability_msg = self.check_server_availability(
                config.PG_HOST, config.PG_PORT, timeout=3.0
            )
            if not available:
                self.is_connected = False
                logger.error("PostgreSQL server is not available - cannot start application")
                return False, availability_msg

            logger.info("PostgreSQL server is reachable, attempting connection...")

            _conn_kwargs = {
                "host": config.PG_HOST,
                "port": config.PG_PORT,
                "user": config.PG_USER,
                "password": config.PG_PASSWORD,
                "dbname": config.PG_DB,
            }

            def configure_connection(conn):
                register_vector_types(conn)
                if conn.info.transaction_status != _PG_TRANSACTION_IDLE:
                    conn.rollback()
                # Set session GUCs once per connection — avoids a round-trip on every query.
                # ef_search=100 covers max(top_k*2, 100) for all callers; going above
                # ef_construction (64) is capped by the index but never hurts correctness.
                conn.autocommit = True
                with conn.cursor() as _cur:
                    _cur.execute("SET hnsw.ef_search = 100")
                conn.autocommit = False

            try:
                logger.debug("Creating connection pool")
                self._ensure_vector_extension(_conn_kwargs)
                self.connection_pool = ConnectionPool(
                    kwargs=_conn_kwargs,
                    min_size=config.DB_POOL_MIN_CONN,
                    max_size=config.DB_POOL_MAX_CONN,
                    timeout=5,
                    configure=configure_connection,
                )
                self.is_connected = True
                self._ensure_extensions_and_tables()
                logger.info("Database connection established successfully with pgvector type support")
                return True, "Database connection established"

            except psycopg.OperationalError as e:
                error_msg = str(e)
                if "database" in error_msg and "does not exist" in error_msg:
                    logger.warning(f"Database {config.PG_DB} doesn't exist, creating...")
                    self._create_database()
                    self._ensure_vector_extension(_conn_kwargs)
                    self.connection_pool = ConnectionPool(
                        kwargs=_conn_kwargs,
                        min_size=config.DB_POOL_MIN_CONN,
                        max_size=config.DB_POOL_MAX_CONN,
                        timeout=5,
                        configure=configure_connection,
                    )
                    self.is_connected = True
                    self._ensure_extensions_and_tables()
                    logger.info("Database created and initialized successfully with pgvector type support")
                    return True, "Database created and initialized"
                else:
                    logger.error(f"Database connection error: {error_msg}")
                    raise

        except Exception as e:
            self.is_connected = False
            if self.connection_pool is not None:
                try:
                    self.connection_pool.close(timeout=2)
                except Exception:
                    pass
                self.connection_pool = None
            error_msg = f"Database connection failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg

    def _ensure_vector_extension(self, conn_kwargs: dict) -> None:
        """Install the pgvector extension before the pool is created.

        The connection pool fires ``configure_connection`` → ``register_vector_types``
        on every connection it opens at startup.  ``register_vector_types`` queries
        ``pg_type`` for the vector OID, so the extension must already exist at that
        point.  Using a direct one-shot connection here guarantees the extension is
        in place before the pool is instantiated.
        """
        with psycopg.connect(**conn_kwargs, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        logger.debug("pgvector extension ensured before pool creation")

    def _create_database(self) -> None:
        """Create the target database if it does not exist."""
        try:
            logger.info(f"Creating database: {config.PG_DB}")
            with psycopg.connect(
                host=config.PG_HOST,
                port=config.PG_PORT,
                user=config.PG_USER,
                password=config.PG_PASSWORD,
                dbname="postgres",
                autocommit=True,
            ) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT 1 FROM pg_database WHERE datname = %s",
                        (config.PG_DB,)
                    )
                    if not cursor.fetchone():
                        query = sql.SQL("CREATE DATABASE {}").format(
                            sql.Identifier(config.PG_DB)
                        )
                        cursor.execute(query)  # type: ignore
                        logger.info(f"Database '{config.PG_DB}' created successfully")
                    else:
                        logger.debug(f"Database '{config.PG_DB}' already exists")
        except Exception as e:
            logger.error(f"Error creating database: {e}", exc_info=True)
            raise

    def _ensure_extensions_and_tables(self) -> None:
        """Create the pgvector extension and all required tables/indexes if absent."""
        logger.debug("Ensuring database extensions and tables exist")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
                logger.debug("pgvector extension ensured")

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS documents (
                        id SERIAL PRIMARY KEY,
                        filename VARCHAR(255) NOT NULL,
                        content TEXT,
                        metadata JSONB,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                logger.debug("Documents table ensured")

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS document_chunks (
                        id SERIAL PRIMARY KEY,
                        document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
                        chunk_text TEXT NOT NULL,
                        chunk_index INTEGER NOT NULL,
                        embedding vector(768),
                        metadata JSONB,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                logger.debug("Document chunks table ensured")

                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS document_chunks_embedding_hnsw_idx
                    ON document_chunks USING hnsw (embedding vector_cosine_ops)
                    WITH (m = 16, ef_construction = 64)
                """)
                logger.debug("HNSW vector similarity index ensured")

                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS document_chunks_document_id_idx
                    ON document_chunks (document_id)
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS document_chunks_chunk_index_idx
                    ON document_chunks (document_id, chunk_index)
                """)
                logger.debug("Document ID and chunk indexes ensured")

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS conversations (
                        id UUID PRIMARY KEY,
                        title VARCHAR(255) NOT NULL DEFAULT 'New Conversation',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("""
                    ALTER TABLE conversations
                    ADD COLUMN IF NOT EXISTS document_ids JSONB DEFAULT '[]'::jsonb
                """)
                logger.debug("Conversations table ensured")

                cursor.execute("""
                    ALTER TABLE documents
                    ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)
                """)
                logger.debug("documents.content_hash column ensured")

                cursor.execute("""
                    ALTER TABLE documents
                    ADD COLUMN IF NOT EXISTS doc_type VARCHAR(20)
                """)
                cursor.execute("""
                    ALTER TABLE documents
                    ADD COLUMN IF NOT EXISTS chunker_version VARCHAR(50)
                """)
                logger.debug("documents.doc_type and chunker_version columns ensured")

                cursor.execute("""
                    ALTER TABLE documents
                    ADD COLUMN IF NOT EXISTS local_only BOOLEAN DEFAULT TRUE
                """)
                logger.debug("documents.local_only column ensured")

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS conversation_messages (
                        id SERIAL PRIMARY KEY,
                        conversation_id UUID NOT NULL
                            REFERENCES conversations(id) ON DELETE CASCADE,
                        role VARCHAR(20) NOT NULL,
                        content TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS conversation_messages_conv_id_idx
                    ON conversation_messages (conversation_id, created_at)
                """)
                logger.debug("Conversation messages table and index ensured")

                conn.commit()
                logger.info("All database extensions and tables verified")

    @contextmanager
    def get_connection(self) -> Generator[psycopg.Connection, None, None]:
        """
        Yield a connection from the pool.

        Commits on clean exit, rolls back on exception, always returns
        the connection to the pool.

        Raises:
            DatabaseUnavailableError: If the connection pool is not initialised.
        """
        if not self.connection_pool:
            raise DatabaseUnavailableError(
                "Database is not available. PostgreSQL connection was not established. "
                "Please ensure PostgreSQL is running and accessible."
            )
        connection = self.connection_pool.getconn()
        try:
            yield connection
            if connection.info.transaction_status == _PG_TRANSACTION_INTRANS:
                connection.commit()
        except Exception as e:
            connection.rollback()
            logger.debug(f"Transaction rolled back: {e}")
            raise
        finally:
            self.connection_pool.putconn(connection)

    def close(self) -> None:
        """Close all connections in the pool gracefully."""
        if self.connection_pool:
            try:
                logger.info("Closing database connection pool...")
                self.connection_pool.close(timeout=2)
                logger.info("Connection pool closed successfully")
            except Exception as e:
                logger.warning(f"Error closing connection pool: {e}", exc_info=True)
            finally:
                self.is_connected = False
                self.connection_pool = None
