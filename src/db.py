"""
Database Module
==============

Manages PostgreSQL database connections with connection pooling and pgvector support.
Handles document storage, chunk management, and vector similarity search.

Classes:
    Database: Connection pool manager with pgvector operations

Example:
    >>> from db import db
    >>> success, message = db.initialize()
    >>> if success:
    ...     doc_id = db.insert_document("test.pdf", "content")

Author: LocalChat Team
Last Updated: 2025-01-27
"""

import psycopg
from psycopg_pool import ConnectionPool
from psycopg.types.json import Jsonb
from psycopg.adapt import Loader, Dumper
from psycopg import sql
import numpy as np
import uuid
from contextlib import contextmanager
from typing import List, Tuple, Optional, Any, Dict, Union, Generator
import socket
from . import config
from .utils.logging_config import get_logger

# Setup logger
logger = get_logger(__name__)


# ============================================================================
# CUSTOM EXCEPTIONS
# ============================================================================

class DatabaseUnavailableError(Exception):
    """
    Exception raised when database operations are attempted without an active connection.
    
    This occurs when the application is running in degraded mode (PostgreSQL unavailable).
    """
    pass


# ============================================================================
# PGVECTOR TYPE ADAPTERS FOR PSYCOPG3
# ============================================================================

class VectorDumper(Dumper):
    """Dumper for pgvector vector type."""
    
    def dump(self, obj):
        """Convert Python list/array to pgvector format."""
        if hasattr(obj, 'tolist'):
            obj = obj.tolist()
        # Format: [val1,val2,val3,...]
        values_str = ','.join(str(float(v)) for v in obj)
        return f'[{values_str}]'.encode('utf-8')


class VectorBinaryDumper(Dumper):
    """Binary dumper for pgvector vector type."""
    
    format: int = 1  # Binary format - type: ignore for Pyright
    
    def dump(self, obj):
        """Convert Python list/array to binary pgvector format."""
        if hasattr(obj, 'tolist'):
            obj = obj.tolist()
        values_str = ','.join(str(float(v)) for v in obj)
        return f'[{values_str}]'.encode('utf-8')


class VectorLoader(Loader):
    """Loader for pgvector vector type."""
    
    def load(self, data):
        """Convert pgvector format to Python list."""
        if isinstance(data, memoryview):
            data = bytes(data)
        if isinstance(data, bytes):
            data = data.decode('utf-8')
        
        # Parse format: [val1,val2,val3,...]
        data_str = data.strip()
        if data_str.startswith('[') and data_str.endswith(']'):  # type: ignore
            data_str = data_str[1:-1]  # Remove brackets
            if data_str:
                return [float(x) for x in data_str.split(',')]  # type: ignore
        return []


def register_vector_types(conn):
    """
    Register pgvector type adapters for a connection.
    
    Args:
        conn: psycopg connection object
    """
    # Get the OID for the vector type
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT oid FROM pg_type WHERE typname = 'vector'")
            result = cur.fetchone()
            if result:
                vector_oid = result[0]
                
                # Register adapters for this connection
                conn.adapters.register_dumper(list, VectorDumper)
                conn.adapters.register_dumper(np.ndarray, VectorDumper)
                conn.adapters.register_loader(vector_oid, VectorLoader)
                
                logger.debug(f"Registered pgvector type adapters (OID: {vector_oid})")
            else:
                logger.warning("pgvector type 'vector' not found in database")
    except Exception as e:
        logger.error(f"Failed to register vector type adapters: {e}", exc_info=True)


# ============================================================================
# DATABASE CLASS
# ============================================================================

class Database:
    """
    Database connection pool manager with pgvector support.
    
    Manages PostgreSQL connections using a connection pool for efficient
    resource utilization. Provides methods for document storage, chunk
    management, and vector similarity search using pgvector extension.
    
    Attributes:
        connection_pool (Optional[ConnectionPool]): psycopg connection pool
        is_connected (bool): Connection status flag
    
    Example:
        >>> db = Database()
        >>> success, msg = db.initialize()
        >>> if success:
        ...     doc_id = db.insert_document("file.pdf", "content")
        ...     results = db.search_similar_chunks(embedding, top_k=5)
    """
    
    def __init__(self) -> None:
        """
        Initialize database manager.
        
        Creates an unconnected database manager. Call initialize() to
        establish the connection pool.
        """
        self.connection_pool: Optional[ConnectionPool] = None
        self.is_connected: bool = False
        logger.info("Database manager initialized")
    
    @staticmethod
    def check_server_availability(host: str, port: int, timeout: float = 2.0) -> Tuple[bool, str]:
        """
        Fast check if PostgreSQL server is available on the network.
        
        Performs a quick socket connection test to see if the server is listening
        before attempting a full database connection. This provides fast failure
        with a meaningful error message.
        
        Args:
            host: PostgreSQL server hostname or IP
            port: PostgreSQL server port
            timeout: Connection timeout in seconds (default: 2.0)
        
        Returns:
            Tuple of (available: bool, message: str)
            - available: True if server is reachable
            - message: Status message or error description
        
        Example:
            >>> available, msg = Database.check_server_availability('localhost', 5432)
            >>> if not available:
            ...     print(f"PostgreSQL not available: {msg}")
        """
        logger.debug(f"Checking if PostgreSQL server is available at {host}:{port}")
        sock = None
        try:
            # Try to establish a socket connection
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))

            if result == 0:
                logger.debug(f"? PostgreSQL server is reachable at {host}:{port}")
                return True, f"PostgreSQL server is reachable at {host}:{port}"
            else:
                error_msg = (
                    f"PostgreSQL server is NOT reachable at {host}:{port}\n"
                    f"  ??  Please ensure:\n"
                    f"     1. PostgreSQL is installed\n"
                    f"     2. PostgreSQL service is running\n"
                    f"     3. Server is listening on {host}:{port}\n"
                    f"  ?? Quick fix:\n"
                    f"     - Windows: Start 'postgresql-x64-XX' service in Services\n"
                    f"     - Linux: sudo systemctl start postgresql\n"
                    f"     - macOS: brew services start postgresql\n"
                    f"     - Docker: docker start postgres-container"
                )
                logger.error(error_msg)
                return False, error_msg

        except socket.gaierror as e:
            # DNS/hostname resolution error
            error_msg = (
                f"Cannot resolve hostname '{host}'\n"
                f"  ??  Check your database configuration in config.py\n"
                f"  ?? Current setting: PG_HOST = '{host}'"
            )
            logger.error(error_msg)
            return False, error_msg

        except socket.timeout:
            error_msg = (
                f"Connection to PostgreSQL at {host}:{port} timed out\n"
                f"  ??  Server may be unresponsive or firewalled\n"
                f"  ?? Check network connectivity and firewall rules"
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
    def _embedding_to_pg_array(embedding: Union[List[float], np.ndarray]) -> str:
        """
        Convert Python list/numpy array to PostgreSQL vector format string.
        
        Args:
            embedding: Embedding vector as list or numpy array
        
        Returns:
            PostgreSQL vector literal string in format '[val1,val2,val3,...]
        
        Example:
            >>> embedding = [0.1, 0.2, 0.3]
            >>> result = Database._embedding_to_pg_array(embedding)
            >>> print(result)
            '[0.1,0.2,0.3]'
        """
        # Handle numpy arrays - convert to list
        if isinstance(embedding, np.ndarray):
            embedding = embedding.tolist()
        # Format as PostgreSQL vector literal: [val1,val2,val3,...]
        values_str = ','.join(str(float(v)) for v in embedding)
        return f'[{values_str}]'
    
    def initialize(self) -> Tuple[bool, str]:
        """
        Initialize the connection pool and create database if needed.
        
        ENHANCED: First checks if PostgreSQL server is reachable before attempting
        connection. This provides fast failure with actionable error messages.
        
        Attempts to connect to the database. If the database doesn't exist,
        creates it automatically. Sets up pgvector extension and required tables.
        Also registers pgvector type adapters for proper vector handling.
        
        Returns:
            Tuple of (success: bool, message: str)
            - success: True if initialization successful
            - message: Status message or error description
        
        Raises:
            Exception: If connection fails for reasons other than missing database
        
        Example:
            >>> db = Database()
            >>> success, message = db.initialize()
            >>> if not success:
            ...     print(f"Database initialization failed: {message}")
            ...     sys.exit(1)
        """
        try:
            logger.info("Initializing database connection pool")
            
            # FAST FAIL: Check if PostgreSQL server is available first
            logger.info(f"Checking PostgreSQL server availability at {config.PG_HOST}:{config.PG_PORT}...")
            available, availability_msg = self.check_server_availability(
                config.PG_HOST,
                config.PG_PORT,
                timeout=3.0
            )
            
            if not available:
                # Server is not available - fail fast with clear message
                self.is_connected = False
                logger.error("? PostgreSQL server is not available - cannot start application")
                return False, availability_msg
            
            logger.info("? PostgreSQL server is reachable, attempting connection...")
            
            # First, check if database exists by trying to connect directly
            try:
                # Try a simple connection without pool first
                conninfo = f"host={config.PG_HOST} port={config.PG_PORT} user={config.PG_USER} password={config.PG_PASSWORD} dbname={config.PG_DB}"
                test_conn = psycopg.connect(conninfo)
                
                # Register vector types for this connection
                register_vector_types(test_conn)
                
                test_conn.close()
                logger.debug("Database exists, creating connection pool")
                
                # Database exists, create the pool with configure callback
                def configure_connection(conn):
                    """Configure each connection from the pool."""
                    register_vector_types(conn)
                    # Ensure connection is in idle state
                    if conn.info.transaction_status != 0:  # 0 = IDLE
                        conn.rollback()
                
                self.connection_pool = ConnectionPool(
                    conninfo=conninfo,
                    min_size=config.DB_POOL_MIN_CONN,
                    max_size=config.DB_POOL_MAX_CONN,
                    timeout=5,
                    configure=configure_connection  # Register types for each connection
                )
                self.is_connected = True
                self._ensure_extensions_and_tables()
                logger.info("Database connection established successfully with pgvector type support")
                return True, "Database connection established"
                
            except psycopg.OperationalError as e:
                error_msg = str(e)
                if "database" in error_msg and "does not exist" in error_msg:
                    # Database doesn't exist, create it
                    logger.warning(f"Database {config.PG_DB} doesn't exist, creating...")
                    self._create_database()
                    
                    # Now create the pool with configure callback
                    def configure_connection(conn):
                        """Configure each connection from the pool."""
                        register_vector_types(conn)
                        # Ensure connection is in idle state
                        if conn.info.transaction_status != 0:  # 0 = IDLE
                            conn.rollback()
                    
                    conninfo = f"host={config.PG_HOST} port={config.PG_PORT} user={config.PG_USER} password={config.PG_PASSWORD} dbname={config.PG_DB}"
                    self.connection_pool = ConnectionPool(
                        conninfo=conninfo,
                        min_size=config.DB_POOL_MIN_CONN,
                        max_size=config.DB_POOL_MAX_CONN,
                        timeout=5,
                        configure=configure_connection  # Register types for each connection
                    )
                    self.is_connected = True
                    self._ensure_extensions_and_tables()
                    logger.info("Database created and initialized successfully with pgvector type support")
                    return True, "Database created and initialized"
                else:
                    # Some other connection error
                    logger.error(f"Database connection error: {error_msg}")
                    raise
                    
        except Exception as e:
            self.is_connected = False
            error_msg = f"Database connection failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg
    
    def _create_database(self) -> None:
        """
        Create the database if it doesn't exist.
        
        Connects to the 'postgres' database to create the target database.
        Uses autocommit to execute the CREATE DATABASE command.
        
        Raises:
            Exception: If database creation fails
        """
        try:
            logger.info(f"Creating database: {config.PG_DB}")
            conninfo = f"host={config.PG_HOST} port={config.PG_PORT} user={config.PG_USER} password={config.PG_PASSWORD} dbname=postgres"
            with psycopg.connect(conninfo, autocommit=True) as conn:
                with conn.cursor() as cursor:
                    # Check if database already exists
                    cursor.execute(
                        "SELECT 1 FROM pg_database WHERE datname = %s",
                        (config.PG_DB,)
                    )
                    
                    if not cursor.fetchone():
                        # Use psycopg.sql for safe query composition
                        from psycopg import sql as psycopg_sql
                        query = psycopg_sql.SQL("CREATE DATABASE {}").format(
                            psycopg_sql.Identifier(config.PG_DB)
                        )
                        cursor.execute(query)  # type: ignore
                        logger.info(f"Database '{config.PG_DB}' created successfully")
                    else:
                        logger.debug(f"Database '{config.PG_DB}' already exists")
        except Exception as e:
            logger.error(f"Error creating database: {e}", exc_info=True)
            raise
    
    def _ensure_extensions_and_tables(self) -> None:
        """
        Ensure pgvector extension and required tables exist.
        
        Creates the pgvector extension, documents table, document_chunks table,
        and vector similarity search indexes if they don't already exist.
        
        ENHANCED: Uses HNSW index for better approximate nearest neighbor performance.
        
        Raises:
            Exception: If table creation fails
        """
        logger.debug("Ensuring database extensions and tables exist")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                # Create pgvector extension
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
                logger.debug("pgvector extension ensured")
                
                # Create documents table
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
                
                # Create document_chunks table with vector embeddings
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
                # Add metadata column to existing tables that were created without it
                cursor.execute("""
                    ALTER TABLE document_chunks
                    ADD COLUMN IF NOT EXISTS metadata JSONB
                """)
                logger.debug("Document chunks table ensured")
                
                # Create HNSW index for vector similarity search (better than ivfflat for performance)
                # HNSW provides better recall and faster queries at the cost of more memory
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS document_chunks_embedding_hnsw_idx 
                    ON document_chunks USING hnsw (embedding vector_cosine_ops)
                    WITH (m = 16, ef_construction = 64)
                """)
                logger.debug("HNSW vector similarity index ensured")
                
                # Create index on document_id for faster joins
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS document_chunks_document_id_idx 
                    ON document_chunks (document_id)
                """)
                logger.debug("Document ID index ensured")
                
                # Create index on chunk_index for position-based queries
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS document_chunks_chunk_index_idx 
                    ON document_chunks (document_id, chunk_index)
                """)
                logger.debug("Chunk index ensured")
                
                # Create conversations table for persistent chat memory
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS conversations (
                        id UUID PRIMARY KEY,
                        title VARCHAR(255) NOT NULL DEFAULT 'New Conversation',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                logger.debug("Conversations table ensured")

                # Create conversation_messages table
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
                logger.debug("Conversation messages table ensured")

                # Index for fast message retrieval per conversation
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS conversation_messages_conv_id_idx
                    ON conversation_messages (conversation_id, created_at)
                """)
                logger.debug("Conversation messages index ensured")

                conn.commit()
                logger.info("All database extensions and tables verified")
    
    @contextmanager
    def get_connection(self) -> Generator[psycopg.Connection, None, None]:
        """
        Get a connection from the pool as a context manager.

        Automatically handles connection lifecycle: acquire from pool,
        commit on success, rollback on error, and return to pool.

        Yields:
            psycopg.Connection: Database connection from pool

        Raises:
            DatabaseUnavailableError: If connection pool is not initialized

        Example:
            >>> with db.get_connection() as conn:
            ...     with conn.cursor() as cursor:
            ...         cursor.execute("SELECT * FROM documents")
            ...         results = cursor.fetchall()
        """
        if not self.connection_pool:
            raise DatabaseUnavailableError(
                "Database is not available. PostgreSQL connection was not established. "
                "Please ensure PostgreSQL is running and accessible. "
                "Check logs for details or set REQUIRE_DATABASE=true to prevent startup without database."
            )
        
        connection = self.connection_pool.getconn()
        try:
            yield connection
            # Auto-commit if no explicit commit was called
            if connection.info.transaction_status == 2:  # INTRANS state
                connection.commit()
        except Exception as e:
            connection.rollback()
            logger.error(f"Connection error, rolled back: {e}", exc_info=True)
            raise
        finally:
            self.connection_pool.putconn(connection)
    
    def close(self) -> None:
        """
        Close all connections in the pool gracefully.
        
        Waits up to 2 seconds for connections to close cleanly.
        Sets is_connected to False regardless of success.
        """
        if self.connection_pool:
            try:
                logger.info("Closing database connection pool...")
                self.connection_pool.close(timeout=2)  # Wait up to 2 seconds
                self.is_connected = False
                logger.info("Connection pool closed successfully")
            except Exception as e:
                logger.warning(f"Error closing connection pool: {e}", exc_info=True)
                self.is_connected = False
    
    def insert_document(
        self,
        filename: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Insert a new document and return its ID.

        Args:
            filename: Name of the document file
            content: Text content of the document
            metadata: Optional metadata dictionary

        Returns:
            int: ID of inserted document

        Raises:
            DatabaseUnavailableError: If database is not connected

        Example:
            >>> doc_id = db.insert_document(
            ...     "report.pdf",
            ...     "Document content here",
            ...     {"author": "John", "pages": 10}
            ... )
            >>> print(f"Inserted document ID: {doc_id}")
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot insert document: Database is not connected")

        logger.debug(f"Inserting document: {filename}")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO documents (filename, content, metadata) VALUES (%s, %s, %s) RETURNING id",
                    (filename, content, Jsonb(metadata or {}))
                )
                doc_id = cursor.fetchone()[0]
                conn.commit()
                logger.info(f"Document inserted with ID: {doc_id}")
                return doc_id
    
    def insert_chunks_batch(
        self,
        chunks_data: List[Union[Tuple[int, str, int, Union[List[float], np.ndarray]], Dict[str, Any]]]
    ) -> None:
        """
        Insert multiple chunks in a batch for better performance.

        Args:
            chunks_data: List of tuples (doc_id, chunk_text, chunk_index, embedding)
                        OR List of dicts with keys: doc_id, chunk_text, chunk_index, embedding, metadata

        Raises:
            DatabaseUnavailableError: If database is not connected

        Example:
            >>> # Old format (still supported)
            >>> chunks = [
            ...     (1, "First chunk text", 0, [0.1, 0.2, ...]),
            ...     (1, "Second chunk text", 1, [0.3, 0.4, ...])
            ... ]
            >>> db.insert_chunks_batch(chunks)

            >>> # New format with metadata
            >>> chunks = [
            ...     {
            ...         'doc_id': 1,
            ...         'chunk_text': "First chunk",
            ...         'chunk_index': 0,
            ...         'embedding': [0.1, 0.2, ...],
            ...         'metadata': {'page_number': 1, 'section_title': 'Introduction'}
            ...     }
            ... ]
            >>> db.insert_chunks_batch(chunks)
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot insert chunks: Database is not connected")

        logger.debug(f"Inserting batch of {len(chunks_data)} chunks")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                for chunk in chunks_data:
                    # Handle both old tuple format and new dict format
                    if isinstance(chunk, dict):
                        doc_id = chunk['doc_id']
                        chunk_text = chunk['chunk_text']
                        chunk_index = chunk['chunk_index']
                        embedding = chunk['embedding']
                        metadata = chunk.get('metadata', {})
                    else:
                        # Old tuple format: (doc_id, chunk_text, chunk_index, embedding)
                        doc_id, chunk_text, chunk_index, embedding = chunk
                        metadata = {}
                    
                    # Convert embedding to PostgreSQL array format
                    embedding_str = self._embedding_to_pg_array(embedding)
                    
                    # Insert with metadata
                    cursor.execute(
                        """INSERT INTO document_chunks 
                           (document_id, chunk_text, chunk_index, embedding, metadata) 
                           VALUES (%s, %s, %s, %s::vector, %s)""",
                        (doc_id, chunk_text, chunk_index, embedding_str, Jsonb(metadata))
                    )
                conn.commit()
                logger.info(f"Successfully inserted {len(chunks_data)} chunks")
    
    def search_similar_chunks(
        self,
        query_embedding: Union[List[float], np.ndarray],
        top_k: int = 5,
        file_type_filter: Optional[str] = None
    ) -> List[Tuple[str, str, int, float, Dict[str, Any]]]:
        """
        Search for similar chunks using cosine similarity.

        Uses pgvector's cosine distance operator (<=>) to find the most
        similar chunks to the query embedding. Optimized with HNSW index
        for fast approximate nearest neighbor search.

        Args:
            query_embedding: Query vector (768 dimensions)
            top_k: Number of results to return
            file_type_filter: Optional file extension filter (e.g., '.pdf')

        Returns:
            List of tuples: (chunk_text, filename, chunk_index, similarity, metadata)
            Similarity scores are in range [0, 1] where 1 is most similar
            metadata is a dict with page_number, section_title, etc.

        Raises:
            DatabaseUnavailableError: If database is not connected

        Example:
            >>> results = db.search_similar_chunks(embedding, top_k=10)
            >>> for text, file, idx, score, meta in results:
            ...     page = meta.get('page_number', 'N/A')
            ...     print(f"{file} chunk {idx} (page {page}): {score:.3f}")
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot search chunks: Database is not connected")

        logger.debug(f"Searching for top {top_k} similar chunks")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                # Convert embedding to string format for SQL
                embedding_str = self._embedding_to_pg_array(query_embedding)
                
                # Set HNSW search parameters for better recall
                # ef_search should be >= top_k for good results
                # Note: SET command doesn't support parameterized queries
                ef_search_value = max(top_k * 2, 100)
                cursor.execute(
                    sql.SQL("SET hnsw.ef_search = {}").format(sql.Literal(ef_search_value))
                )

                # This leverages the HNSW index for fast ANN search
                if file_type_filter:
                    query_sql = """
                        SELECT 
                            dc.chunk_text,
                            d.filename,
                            dc.chunk_index,
                            1 - (dc.embedding <=> %s::vector) as similarity,
                            dc.metadata
                        FROM document_chunks dc
                        JOIN documents d ON dc.document_id = d.id
                        WHERE dc.embedding IS NOT NULL
                          AND d.filename LIKE %s
                        ORDER BY dc.embedding <=> %s::vector
                        LIMIT %s
                    """
                    file_pattern = f'%{file_type_filter}'
                    cursor.execute(query_sql, (embedding_str, file_pattern, embedding_str, top_k))
                    logger.debug(f"Searching with file type filter: {file_type_filter}")
                else:
                    query_sql = """
                        SELECT 
                            dc.chunk_text,
                            d.filename,
                            dc.chunk_index,
                            1 - (dc.embedding <=> %s::vector) as similarity,
                            dc.metadata
                        FROM document_chunks dc
                        JOIN documents d ON dc.document_id = d.id
                        WHERE dc.embedding IS NOT NULL
                        ORDER BY dc.embedding <=> %s::vector
                        LIMIT %s
                    """
                    cursor.execute(query_sql, (embedding_str, embedding_str, top_k))
                results = cursor.fetchall()
                conn.commit()
                logger.debug(f"Found {len(results)} similar chunks")
                # Convert None metadata to empty dict
                return [(r[0], r[1], r[2], r[3], r[4] or {}) for r in results]
    
    def search_similar_chunks_with_scores(
        self,
        query_embedding: Union[List[float], np.ndarray],
        top_k: int = 5,
        min_similarity: float = 0.0,
        file_type_filter: Optional[str] = None
    ) -> List[Tuple[str, str, int, float, int]]:
        """
        Search for similar chunks with additional metadata for re-ranking.

        Enhanced version that returns document_id for context window expansion
        and applies similarity threshold at database level.

        Args:
            query_embedding: Query vector (768 dimensions)
            top_k: Number of results to return
            min_similarity: Minimum similarity threshold (0.0-1.0)
            file_type_filter: Optional file extension filter

        Returns:
            List of tuples: (chunk_text, filename, chunk_index, similarity, document_id)

        Raises:
            DatabaseUnavailableError: If database is not connected
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot search chunks: Database is not connected")

        logger.debug(f"Searching for top {top_k} similar chunks (min_sim={min_similarity})")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                embedding_str = self._embedding_to_pg_array(query_embedding)
                # Set HNSW search parameters
                ef_search_value = max(top_k * 2, 100)
                cursor.execute(
                    sql.SQL("SET hnsw.ef_search = {}").format(sql.Literal(ef_search_value))
                )

                # Calculate distance threshold from similarity threshold
                # similarity = 1 - distance, so distance = 1 - similarity
                max_distance = 1.0 - min_similarity

                if file_type_filter:
                    query_sql = """
                        SELECT 
                            dc.chunk_text,
                            d.filename,
                            dc.chunk_index,
                            1 - (dc.embedding <=> %s::vector) as similarity,
                            dc.document_id
                        FROM document_chunks dc
                        JOIN documents d ON dc.document_id = d.id
                        WHERE dc.embedding IS NOT NULL
                          AND d.filename LIKE %s
                          AND (dc.embedding <=> %s::vector) <= %s
                        ORDER BY dc.embedding <=> %s::vector
                        LIMIT %s
                    """
                    file_pattern = f'%{file_type_filter}'
                    cursor.execute(query_sql, (embedding_str, file_pattern, embedding_str, max_distance, embedding_str, top_k))
                else:
                    query_sql = """
                        SELECT 
                            dc.chunk_text,
                            d.filename,
                            dc.chunk_index,
                            1 - (dc.embedding <=> %s::vector) as similarity,
                            dc.document_id
                        FROM document_chunks dc
                        JOIN documents d ON dc.document_id = d.id
                        WHERE dc.embedding IS NOT NULL
                          AND (dc.embedding <=> %s::vector) <= %s
                        ORDER BY dc.embedding <=> %s::vector
                        LIMIT %s
                    """
                    cursor.execute(query_sql, (embedding_str, embedding_str, max_distance, embedding_str, top_k))

                results = cursor.fetchall()
                conn.commit()
                logger.debug(f"Found {len(results)} chunks above similarity threshold {min_similarity}")
                return results
    
    def get_adjacent_chunks(
        self,
        document_id: int,
        chunk_index: int,
        window_size: int = 1
    ) -> List[Tuple[str, int]]:
        """
        Get adjacent chunks for context window expansion.

        Retrieves chunks before and after the specified chunk to provide
        additional context for better understanding.

        Args:
            document_id: ID of the document
            chunk_index: Index of the center chunk
            window_size: Number of chunks before and after to retrieve

        Returns:
            List of tuples: (chunk_text, chunk_index) ordered by chunk_index

        Raises:
            DatabaseUnavailableError: If database is not connected
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot get adjacent chunks: Database is not connected")

        logger.debug(f"Getting adjacent chunks for doc {document_id}, chunk {chunk_index}, window {window_size}")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT chunk_text, chunk_index
                    FROM document_chunks
                    WHERE document_id = %s
                      AND chunk_index BETWEEN %s AND %s
                    ORDER BY chunk_index
                """, (document_id, chunk_index - window_size, chunk_index + window_size))
                
                results = cursor.fetchall()
                logger.debug(f"Retrieved {len(results)} adjacent chunks")
                return results
    
    def get_document_count(self) -> int:
        """
        Get total number of documents in database.

        Returns:
            int: Count of documents

        Raises:
            DatabaseUnavailableError: If database is not connected

        Example:
            >>> count = db.get_document_count()
            >>> print(f"Total documents: {count}")
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot get document count: Database is not connected")

        logger.debug("Getting document count")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM documents")
                count = cursor.fetchone()[0]
                logger.debug(f"Document count: {count}")
                return count

    def get_chunk_count(self) -> int:
        """
        Get total number of chunks in database.

        Returns:
            int: Count of chunks

        Raises:
            DatabaseUnavailableError: If database is not connected

        Example:
            >>> count = db.get_chunk_count()
            >>> print(f"Total chunks: {count}")
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot get chunk count: Database is not connected")

        logger.debug("Getting chunk count")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM document_chunks")
                count = cursor.fetchone()[0]
                logger.debug(f"Chunk count: {count}")
                return count
    
    def get_all_documents(self) -> List[Dict[str, Any]]:
        """
        Get list of all documents with metadata.

        Returns:
            List of dictionaries containing document information:
            - id: Document ID
            - filename: Document filename
            - created_at: Creation timestamp
            - chunk_count: Number of chunks for this document

        Raises:
            DatabaseUnavailableError: If database is not connected

        Example:
            >>> docs = db.get_all_documents()
            >>> for doc in docs:
            ...     print(f"{doc['filename']}: {doc['chunk_count']} chunks")
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot get documents: Database is not connected")

        logger.debug("Getting all documents")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        d.id,
                        d.filename,
                        d.created_at,
                        COUNT(dc.id) as chunk_count
                    FROM documents d
                    LEFT JOIN document_chunks dc ON d.id = dc.document_id
                    GROUP BY d.id, d.filename, d.created_at
                    ORDER BY d.created_at DESC
                """)
                
                rows = cursor.fetchall()
                documents = []
                for row in rows:
                    documents.append({
                        'id': row[0],
                        'filename': row[1],
                        'created_at': row[2].isoformat() if row[2] else None,
                        'chunk_count': row[3]
                    })
                
                logger.debug(f"Retrieved {len(documents)} documents")
                return documents
    
    def document_exists(self, filename: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Check if a document with given filename already exists.

        Args:
            filename: Name of the document file

        Returns:
            Tuple of (exists: bool, doc_info: Dict)
            - exists: True if document exists
            - doc_info: Dictionary with document details (id, chunk_count, created_at)

        Raises:
            DatabaseUnavailableError: If database is not connected

        Example:
            >>> exists, info = db.document_exists("report.pdf")
            >>> if exists:
            ...     print(f"Document already exists with {info['chunk_count']} chunks")
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot check document existence: Database is not connected")

        logger.debug(f"Checking if document exists: {filename}")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        d.id,
                        d.created_at,
                        COUNT(dc.id) as chunk_count
                    FROM documents d
                    LEFT JOIN document_chunks dc ON d.id = dc.document_id
                    WHERE d.filename = %s
                    GROUP BY d.id, d.created_at
                """, (filename,))
                
                row = cursor.fetchone()
                if row:
                    doc_info = {
                        'id': row[0],
                        'created_at': row[1].isoformat() if row[1] else None,
                        'chunk_count': row[2]
                    }
                    logger.debug(f"Document exists: {filename} (ID: {row[0]})")
                    return True, doc_info
                else:
                    logger.debug(f"Document does not exist: {filename}")
                    return False, {}
    
    def get_chunk_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about chunks in the database for debugging.

        Returns:
            Dictionary with chunk statistics:
            - total_chunks: Total number of chunks
            - chunks_with_embeddings: Number of chunks with embeddings
            - chunks_without_embeddings: Number of chunks without embeddings
            - avg_chunk_length: Average chunk text length
            - sample_chunks: Sample of 3 chunks for inspection

        Raises:
            DatabaseUnavailableError: If database is not connected

        Example:
            >>> stats = db.get_chunk_statistics()
            >>> print(f"Total chunks: {stats['total_chunks']}")
            >>> print(f"Sample: {stats['sample_chunks'][0]['preview']}")
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot get chunk statistics: Database is not connected")

        logger.debug("Getting chunk statistics")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                # Get counts
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total,
                        COUNT(embedding) as with_embeddings,
                        AVG(LENGTH(chunk_text)) as avg_length
                    FROM document_chunks
                """)
                row = cursor.fetchone()
                total = row[0]
                with_embeddings = row[1]
                avg_length = float(row[2]) if row[2] else 0.0
                
                # Get sample chunks
                cursor.execute("""
                    SELECT 
                        d.filename,
                        dc.chunk_index,
                        dc.chunk_text,
                        LENGTH(dc.chunk_text) as length,
                        dc.embedding IS NOT NULL as has_embedding
                    FROM document_chunks dc
                    JOIN documents d ON dc.document_id = d.id
                    ORDER BY RANDOM()
                    LIMIT 3
                """)
                
                samples = []
                for row in cursor.fetchall():
                    samples.append({
                        'filename': row[0],
                        'chunk_index': row[1],
                        'preview': row[2][:200] + '...' if len(row[2]) > 200 else row[2],
                        'length': row[3],
                        'has_embedding': row[4]
                    })
                
                stats = {
                    'total_chunks': total,
                    'chunks_with_embeddings': with_embeddings,
                    'chunks_without_embeddings': total - with_embeddings,
                    'avg_chunk_length': round(avg_length, 2),
                    'sample_chunks': samples
                }
                
                logger.info(f"Chunk statistics: {total} total, {with_embeddings} with embeddings")
                return stats
    
    def search_chunks_by_text(
        self,
        search_text: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Search chunks by text content (for debugging keyword matching).

        Performs a simple SQL text search to see what content is in chunks.
        Useful for debugging why BM25 might not find keyword matches.

        Args:
            search_text: Text to search for (case-insensitive)
            limit: Maximum number of results

        Returns:
            List of dictionaries with chunk information

        Raises:
            DatabaseUnavailableError: If database is not connected

        Example:
            >>> results = db.search_chunks_by_text("security", limit=5)
            >>> for r in results:
            ...     print(f"{r['filename']}: {r['preview']}")
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot search chunks by text: Database is not connected")

        logger.debug(f"Searching chunks for text: {search_text}")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        d.filename,
                        dc.chunk_index,
                        dc.chunk_text,
                        LENGTH(dc.chunk_text) as length
                    FROM document_chunks dc
                    JOIN documents d ON dc.document_id = d.id
                    WHERE dc.chunk_text ILIKE %s
                    ORDER BY dc.chunk_index
                    LIMIT %s
                """, (f'%{search_text}%', limit))
                
                results = []
                for row in cursor.fetchall():
                    results.append({
                        'filename': row[0],
                        'chunk_index': row[1],
                        'preview': row[2][:200] + '...' if len(row[2]) > 200 else row[2],
                        'full_text': row[2],
                        'length': row[3]
                    })
                
                logger.info(f"Found {len(results)} chunks containing '{search_text}'")
                return results
    
    # ========================================================================
    # CONVERSATION / PERSISTENT MEMORY METHODS
    # ========================================================================

    def create_conversation(self, title: str = 'New Conversation') -> str:
        """
        Create a new conversation and return its UUID.

        Args:
            title: Conversation title (truncated to 255 chars)

        Returns:
            str: UUID of the created conversation

        Raises:
            DatabaseUnavailableError: If database is not connected
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot create conversation: Database is not connected")

        conversation_id = str(uuid.uuid4())
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO conversations (id, title) VALUES (%s, %s)",
                    (conversation_id, title[:255])
                )
                conn.commit()
        logger.debug(f"Created conversation: {conversation_id}")
        return conversation_id

    def list_conversations(self) -> List[Dict[str, Any]]:
        """
        List all conversations ordered by most recently updated.

        Returns:
            List of dicts with keys: id, title, created_at, updated_at, message_count

        Raises:
            DatabaseUnavailableError: If database is not connected
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot list conversations: Database is not connected")

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT
                        c.id,
                        c.title,
                        c.created_at,
                        c.updated_at,
                        COUNT(cm.id) AS message_count
                    FROM conversations c
                    LEFT JOIN conversation_messages cm ON c.id = cm.conversation_id
                    GROUP BY c.id, c.title, c.created_at, c.updated_at
                    ORDER BY c.updated_at DESC
                """)
                rows = cursor.fetchall()
                return [
                    {
                        'id': str(row[0]),
                        'title': row[1],
                        'created_at': row[2].isoformat() if row[2] else None,
                        'updated_at': row[3].isoformat() if row[3] else None,
                        'message_count': row[4],
                    }
                    for row in rows
                ]

    def get_conversation_messages(self, conversation_id: str) -> Optional[List[Dict[str, Any]]]:
        """
        Get all messages for a conversation.

        Args:
            conversation_id: UUID of the conversation

        Returns:
            List of message dicts (role, content, timestamp), or None if not found

        Raises:
            DatabaseUnavailableError: If database is not connected
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot get messages: Database is not connected")

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id FROM conversations WHERE id = %s", (conversation_id,))
                if not cursor.fetchone():
                    return None

                cursor.execute("""
                    SELECT role, content, created_at
                    FROM conversation_messages
                    WHERE conversation_id = %s
                    ORDER BY created_at ASC, id ASC
                """, (conversation_id,))
                rows = cursor.fetchall()
                return [
                    {
                        'role': row[0],
                        'content': row[1],
                        'timestamp': row[2].isoformat() if row[2] else None,
                    }
                    for row in rows
                ]

    def save_message(self, conversation_id: str, role: str, content: str) -> int:
        """
        Append a message to a conversation and bump its updated_at timestamp.

        Args:
            conversation_id: UUID of the conversation
            role: 'user' or 'assistant'
            content: Message text

        Returns:
            int: ID of the inserted message row

        Raises:
            DatabaseUnavailableError: If database is not connected
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot save message: Database is not connected")

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO conversation_messages (conversation_id, role, content)
                       VALUES (%s, %s, %s) RETURNING id""",
                    (conversation_id, role, content)
                )
                message_id = cursor.fetchone()[0]
                cursor.execute(
                    "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                    (conversation_id,)
                )
                conn.commit()
        logger.debug(f"Saved {role} message (id={message_id}) to conversation {conversation_id}")
        return message_id

    def update_conversation_title(self, conversation_id: str, title: str) -> bool:
        """
        Update a conversation's title.

        Args:
            conversation_id: UUID of the conversation
            title: New title (truncated to 255 chars)

        Returns:
            bool: True if updated, False if conversation not found

        Raises:
            DatabaseUnavailableError: If database is not connected
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot update conversation: Database is not connected")

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE conversations SET title = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                    (title[:255], conversation_id)
                )
                updated = cursor.rowcount > 0
                conn.commit()
        return updated

    def delete_conversation(self, conversation_id: str) -> bool:
        """
        Delete a conversation and all its messages (cascade).

        Args:
            conversation_id: UUID of the conversation

        Returns:
            bool: True if deleted, False if not found

        Raises:
            DatabaseUnavailableError: If database is not connected
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot delete conversation: Database is not connected")

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM conversations WHERE id = %s", (conversation_id,))
                deleted = cursor.rowcount > 0
                conn.commit()
        logger.debug(f"Deleted conversation: {conversation_id}")
        return deleted

    def delete_all_documents(self) -> None:
        """
        Delete all documents and their chunks from the database.

        WARNING: This operation cannot be undone!

        Raises:
            DatabaseUnavailableError: If database is not connected

        Example:
            >>> db.delete_all_documents()
            >>> print("All documents deleted")
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot delete documents: Database is not connected")

        logger.warning("Deleting ALL documents and chunks")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                # Delete all chunks (will cascade from documents due to FK)
                cursor.execute("DELETE FROM document_chunks")
                chunks_deleted = cursor.rowcount
                
                # Delete all documents
                cursor.execute("DELETE FROM documents")
                docs_deleted = cursor.rowcount
                
                conn.commit()
                logger.info(f"Deleted {docs_deleted} documents and {chunks_deleted} chunks")
                
# ============================================================================
# GLOBAL INSTANCE
# ============================================================================

# Global database instance
db = Database()

logger.info("Database module loaded")

# Export exception for use in error handlers
__all__ = ['Database', 'db', 'DatabaseUnavailableError']
