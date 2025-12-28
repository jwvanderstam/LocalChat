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
Last Updated: 2024-12-27
"""

import psycopg
from psycopg_pool import ConnectionPool
from psycopg.types.json import Jsonb
import numpy as np
from contextlib import contextmanager
from typing import List, Tuple, Optional, Any, Dict, Union, Generator
from . import config
from .utils.logging_config import get_logger

# Setup logger
logger = get_logger(__name__)


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
        if hasattr(embedding, 'tolist'):
            embedding = embedding.tolist()
        # Format as PostgreSQL vector literal: [val1,val2,val3,...]
        values_str = ','.join(str(float(v)) for v in embedding)
        return f'[{values_str}]'
    
    def initialize(self) -> Tuple[bool, str]:
        """
        Initialize the connection pool and create database if needed.
        
        Attempts to connect to the database. If the database doesn't exist,
        creates it automatically. Sets up pgvector extension and required tables.
        
        Returns:
            Tuple of (success: bool, message: str)
            - success: True if initialization successful
            - message: Status message or error description
        
        Raises:
            Exception: If connection fails for reasons other than missing database
        
        Example:
            >>> db = Database()
            >>> success, message = db.initialize()
            >>> print(message)
            'Database connection established'
        """
        try:
            logger.info("Initializing database connection pool")
            
            # First, check if database exists by trying to connect directly
            try:
                # Try a simple connection without pool first
                conninfo = f"host={config.PG_HOST} port={config.PG_PORT} user={config.PG_USER} password={config.PG_PASSWORD} dbname={config.PG_DB}"
                test_conn = psycopg.connect(conninfo)
                test_conn.close()
                logger.debug("Database exists, creating connection pool")
                
                # Database exists, create the pool
                self.connection_pool = ConnectionPool(
                    conninfo=conninfo,
                    min_size=config.DB_POOL_MIN_CONN,
                    max_size=config.DB_POOL_MAX_CONN,
                    timeout=5  # Add timeout to prevent hanging
                )
                self.is_connected = True
                self._ensure_extensions_and_tables()
                logger.info("Database connection established successfully")
                return True, "Database connection established"
                
            except psycopg.OperationalError as e:
                error_msg = str(e)
                if "database" in error_msg and "does not exist" in error_msg:
                    # Database doesn't exist, create it
                    logger.warning(f"Database {config.PG_DB} doesn't exist, creating...")
                    self._create_database()
                    
                    # Now create the pool
                    conninfo = f"host={config.PG_HOST} port={config.PG_PORT} user={config.PG_User} password={config.PG_PASSWORD} dbname={config.PG_DB}"
                    self.connection_pool = ConnectionPool(
                        conninfo=conninfo,
                        min_size=config.DB_POOL_MIN_CONN,
                        max_size=config.DB_POOL_MAX_CONN,
                        timeout=5
                    )
                    self.is_connected = True
                    self._ensure_extensions_and_tables()
                    logger.info("Database created and initialized successfully")
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
                        cursor.execute(f"CREATE DATABASE {config.PG_DB}")
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
        and vector similarity search index if they don't already exist.
        
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
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                logger.debug("Document chunks table ensured")
                
                # Create index for vector similarity search
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS document_chunks_embedding_idx 
                    ON document_chunks USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = 100)
                """)
                logger.debug("Vector similarity index ensured")
                
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
        
        Example:
            >>> with db.get_connection() as conn:
            ...     with conn.cursor() as cursor:
            ...         cursor.execute("SELECT * FROM documents")
            ...         results = cursor.fetchall()
        """
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
        
        Example:
            >>> doc_id = db.insert_document(
            ...     "report.pdf",
            ...     "Document content here",
            ...     {"author": "John", "pages": 10}
            ... )
            >>> print(f"Inserted document ID: {doc_id}")
        """
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
        chunks_data: List[Tuple[int, str, int, Union[List[float], np.ndarray]]]
    ) -> None:
        """
        Insert multiple chunks in a batch for better performance.
        
        Args:
            chunks_data: List of tuples (doc_id, chunk_text, chunk_index, embedding)
        
        Example:
            >>> chunks = [
            ...     (1, "First chunk text", 0, [0.1, 0.2, ...]),
            ...     (1, "Second chunk text", 1, [0.3, 0.4, ...])
            ... ]
            >>> db.insert_chunks_batch(chunks)
        """
        logger.debug(f"Inserting batch of {len(chunks_data)} chunks")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                # Use executemany for batch insert
                for chunk in chunks_data:
                    doc_id, chunk_text, chunk_index, embedding = chunk
                    # Convert embedding to PostgreSQL array format
                    embedding_str = self._embedding_to_pg_array(embedding)
                    
                    cursor.execute(
                        """INSERT INTO document_chunks (document_id, chunk_text, chunk_index, embedding) 
                           VALUES (%s, %s, %s, %s::vector)""",
                        (doc_id, chunk_text, chunk_index, embedding_str)
                    )
                conn.commit()
                logger.info(f"Successfully inserted {len(chunks_data)} chunks")
    
    def search_similar_chunks(
        self,
        query_embedding: Union[List[float], np.ndarray],
        top_k: int = 5,
        file_type_filter: Optional[str] = None
    ) -> List[Tuple[str, str, int, float]]:
        """
        Search for similar chunks using cosine similarity.
        
        Uses pgvector's cosine distance operator (<=>)  to find the most
        similar chunks to the query embedding.
        
        Args:
            query_embedding: Query vector (768 dimensions)
            top_k: Number of results to return
            file_type_filter: Optional file extension filter (e.g., '.pdf')
        
        Returns:
            List of tuples: (chunk_text, filename, chunk_index, similarity)
            Similarity scores are in range [0, 1] where 1 is most similar
        
        Example:
            >>> results = db.search_similar_chunks(embedding, top_k=10)
            >>> for text, file, idx, score in results:
            ...     print(f"{file} chunk {idx}: {score:.3f}")
        """
        logger.debug(f"Searching for top {top_k} similar chunks")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                # Convert embedding to PostgreSQL array format
                embedding_str = self._embedding_to_pg_array(query_embedding)
                
                # Build query with optional file type filter
                if file_type_filter:
                    query = """
                        SELECT 
                            dc.chunk_text,
                            d.filename,
                            dc.chunk_index,
                            1 - (dc.embedding <=> %s::vector) as similarity
                        FROM document_chunks dc
                        JOIN documents d ON dc.document_id = d.id
                        WHERE dc.embedding IS NOT NULL
                          AND d.filename LIKE %s
                        ORDER BY dc.embedding <=> %s::vector
                        LIMIT %s
                    """
                    # Create LIKE pattern for file extension
                    file_pattern = f'%{file_type_filter}'
                    cursor.execute(query, (embedding_str, file_pattern, embedding_str, top_k))
                    logger.debug(f"Searching with file type filter: {file_type_filter}")
                else:
                    query = """
                        SELECT 
                            dc.chunk_text,
                            d.filename,
                            dc.chunk_index,
                            1 - (dc.embedding <=> %s::vector) as similarity
                        FROM document_chunks dc
                        JOIN documents d ON dc.document_id = d.id
                        WHERE dc.embedding IS NOT NULL
                        ORDER BY dc.embedding <=> %s::vector
                        LIMIT %s
                    """
                    cursor.execute(query, (embedding_str, embedding_str, top_k))
                
                results = cursor.fetchall()
                conn.commit()
                logger.debug(f"Found {len(results)} similar chunks")
                return results
    
    def get_document_count(self) -> int:
        """
        Get the total number of documents.
        
        Returns:
            int: Total document count
        
        Example:
            >>> count = db.get_document_count()
            >>> print(f"Total documents: {count}")
        """
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM documents")
                count = cursor.fetchone()[0]
                logger.debug(f"Document count: {count}")
                return count
    
    def get_chunk_count(self) -> int:
        """
        Get the total number of chunks.
        
        Returns:
            int: Total chunk count
        
        Example:
            >>> count = db.get_chunk_count()
            >>> print(f"Total chunks: {count}")
        """
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM document_chunks")
                count = cursor.fetchone()[0]
                logger.debug(f"Chunk count: {count}")
                return count
    
    def delete_all_documents(self) -> None:
        """
        Delete all documents and chunks.
        
        Cascading delete removes all associated chunks automatically.
        
        Warning:
            This operation cannot be undone!
        
        Example:
            >>> db.delete_all_documents()
            >>> print("All documents deleted")
        """
        logger.warning("Deleting ALL documents and chunks")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM document_chunks")
                cursor.execute("DELETE FROM documents")
                conn.commit()
                logger.info("All documents and chunks deleted")
    
    def get_all_documents(self) -> List[Dict[str, Any]]:
        """
        Get all documents with their metadata.
        
        Returns:
            List of dictionaries containing document information:
            - id: Document ID
            - filename: Document filename
            - created_at: Creation timestamp
            - metadata: Document metadata
            - chunk_count: Number of chunks for this document
        
        Example:
            >>> docs = db.get_all_documents()
            >>> for doc in docs:
            ...     print(f"{doc['filename']}: {doc['chunk_count']} chunks")
        """
        logger.debug("Fetching all documents")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        d.id,
                        d.filename,
                        d.created_at,
                        d.metadata,
                        COUNT(dc.id) as chunk_count
                    FROM documents d
                    LEFT JOIN document_chunks dc ON d.id = dc.document_id
                    GROUP BY d.id, d.filename, d.created_at, d.metadata
                    ORDER BY d.created_at DESC
                """)
                # Convert to list of dicts
                columns = [desc[0] for desc in cursor.description]
                results = []
                for row in cursor.fetchall():
                    results.append(dict(zip(columns, row)))
                logger.debug(f"Retrieved {len(results)} documents")
                return results
    
    def document_exists(self, filename: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Check if a document with the given filename already exists.
        
        Args:
            filename: Name of the document file to check
        
        Returns:
            Tuple of (exists: bool, document_info: Optional[Dict])
            - exists: True if document exists
            - document_info: Dict with id, filename, created_at, chunk_count if exists, None otherwise
        
        Example:
            >>> exists, doc_info = db.document_exists("report.pdf")
            >>> if exists:
            ...     print(f"Document already exists with {doc_info['chunk_count']} chunks")
        """
        logger.debug(f"Checking if document exists: {filename}")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        d.id,
                        d.filename,
                        d.created_at,
                        d.metadata,
                        COUNT(dc.id) as chunk_count
                    FROM documents d
                    LEFT JOIN document_chunks dc ON d.id = dc.document_id
                    WHERE d.filename = %s
                    GROUP BY d.id, d.filename, d.created_at, d.metadata
                """, (filename,))
                
                result = cursor.fetchone()
                
                if result:
                    columns = [desc[0] for desc in cursor.description]
                    doc_info = dict(zip(columns, result))
                    logger.debug(f"Document exists: ID={doc_info['id']}, chunks={doc_info['chunk_count']}")
                    return True, doc_info
                else:
                    logger.debug(f"Document does not exist: {filename}")
                    return False, None


# ============================================================================
# GLOBAL INSTANCE
# ============================================================================

# Global database instance
db = Database()

logger.info("Database module loaded")
