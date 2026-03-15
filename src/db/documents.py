"""
Document Operations Module
==========================

Mixin providing document storage, chunk management, and vector
similarity search operations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

import numpy as np
from psycopg import sql
from psycopg.types.json import Jsonb

from ..utils.logging_config import get_logger
from .connection import DatabaseUnavailableError

if TYPE_CHECKING:
    from .connection import DatabaseConnection

logger = get_logger(__name__)


class DocumentsMixin:
    """Mixin that adds document and chunk operations to the Database class."""

    # Provided by DatabaseConnection at runtime via MRO
    is_connected: bool
    get_connection: DatabaseConnection.get_connection  # type: ignore[assignment]
    _embedding_to_pg_array: DatabaseConnection._embedding_to_pg_array  # type: ignore[assignment]

    def insert_document(
        self,
        filename: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
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
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot insert document: Database is not connected")

        logger.debug(f"Inserting document: {filename}")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO documents (filename, content, metadata) VALUES (%s, %s, %s) RETURNING id",
                    (filename, content, Jsonb(metadata or {})),
                )
                doc_id = cursor.fetchone()[0]
                conn.commit()
        logger.info(f"Document inserted with ID: {doc_id}")
        return doc_id

    def insert_chunks_batch(
        self,
        chunks_data: List[Union[Tuple[int, str, int, Union[List[float], 'np.ndarray']], Dict[str, Any]]],
    ) -> None:
        """
        Insert multiple chunks in a single transaction.

        Args:
            chunks_data: List of tuples ``(doc_id, chunk_text, chunk_index, embedding)``
                         or dicts with keys ``doc_id, chunk_text, chunk_index, embedding[, metadata]``.

        Raises:
            DatabaseUnavailableError: If database is not connected
        """
        if not chunks_data:
            return

        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot insert chunks: Database is not connected")

        logger.debug(f"Inserting batch of {len(chunks_data)} chunks")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                for chunk in chunks_data:
                    if isinstance(chunk, dict):
                        doc_id = chunk['doc_id']
                        chunk_text = chunk['chunk_text']
                        chunk_index = chunk['chunk_index']
                        embedding = chunk['embedding']
                        metadata = chunk.get('metadata', {})
                    else:
                        doc_id, chunk_text, chunk_index, embedding = chunk
                        metadata = {}

                    embedding_str = self._embedding_to_pg_array(embedding)
                    cursor.execute(
                        """INSERT INTO document_chunks
                           (document_id, chunk_text, chunk_index, embedding, metadata)
                           VALUES (%s, %s, %s, %s::vector, %s)""",
                        (doc_id, chunk_text, chunk_index, embedding_str, Jsonb(metadata)),
                    )
                conn.commit()
        logger.info(f"Successfully inserted {len(chunks_data)} chunks")

    def search_similar_chunks(
        self,
        query_embedding: Union[List[float], 'np.ndarray'],
        top_k: int = 5,
        file_type_filter: Optional[str] = None,
    ) -> List[Tuple[str, str, int, float, Dict[str, Any]]]:
        """
        Search for similar chunks using cosine similarity via pgvector HNSW.

        Args:
            query_embedding: Query vector (768 dimensions)
            top_k: Number of results to return
            file_type_filter: Optional file extension filter (e.g. '.pdf')

        Returns:
            List of ``(chunk_text, filename, chunk_index, similarity, metadata)``

        Raises:
            DatabaseUnavailableError: If database is not connected
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot search chunks: Database is not connected")

        logger.debug(f"Searching for top {top_k} similar chunks")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                embedding_str = self._embedding_to_pg_array(query_embedding)
                ef_search_value = max(top_k * 2, 100)
                cursor.execute(
                    sql.SQL("SET hnsw.ef_search = {}").format(sql.Literal(ef_search_value))
                )

                if file_type_filter:
                    cursor.execute(
                        """
                        WITH q AS (SELECT %s::vector AS emb)
                        SELECT dc.chunk_text, d.filename, dc.chunk_index,
                               1 - (dc.embedding <=> q.emb) AS similarity,
                               dc.metadata
                        FROM document_chunks dc
                        JOIN documents d ON dc.document_id = d.id
                        CROSS JOIN q
                        WHERE dc.embedding IS NOT NULL AND d.filename LIKE %s
                        ORDER BY dc.embedding <=> q.emb
                        LIMIT %s
                        """,
                        (embedding_str, f'%{file_type_filter}', top_k),
                    )
                    logger.debug(f"Searching with file type filter: {file_type_filter}")
                else:
                    cursor.execute(
                        """
                        WITH q AS (SELECT %s::vector AS emb)
                        SELECT dc.chunk_text, d.filename, dc.chunk_index,
                               1 - (dc.embedding <=> q.emb) AS similarity,
                               dc.metadata
                        FROM document_chunks dc
                        JOIN documents d ON dc.document_id = d.id
                        CROSS JOIN q
                        WHERE dc.embedding IS NOT NULL
                        ORDER BY dc.embedding <=> q.emb
                        LIMIT %s
                        """,
                        (embedding_str, top_k),
                    )

                results = cursor.fetchall()
                logger.debug(f"Found {len(results)} similar chunks")
                return [(r[0], r[1], r[2], r[3], r[4] or {}) for r in results]

    def search_similar_chunks_with_scores(
        self,
        query_embedding: Union[List[float], 'np.ndarray'],
        top_k: int = 5,
        min_similarity: float = 0.0,
        file_type_filter: Optional[str] = None,
    ) -> List[Tuple[str, str, int, float, int]]:
        """
        Search for similar chunks, applying a similarity threshold at DB level.

        Returns:
            List of ``(chunk_text, filename, chunk_index, similarity, document_id)``

        Raises:
            DatabaseUnavailableError: If database is not connected
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot search chunks: Database is not connected")

        logger.debug(f"Searching for top {top_k} similar chunks (min_sim={min_similarity})")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                embedding_str = self._embedding_to_pg_array(query_embedding)
                ef_search_value = max(top_k * 2, 100)
                cursor.execute(
                    sql.SQL("SET hnsw.ef_search = {}").format(sql.Literal(ef_search_value))
                )
                max_distance = 1.0 - min_similarity

                if file_type_filter:
                    cursor.execute(
                        """
                        SELECT dc.chunk_text, d.filename, dc.chunk_index,
                               1 - (dc.embedding <=> %s::vector) AS similarity,
                               dc.document_id
                        FROM document_chunks dc
                        JOIN documents d ON dc.document_id = d.id
                        WHERE dc.embedding IS NOT NULL
                          AND d.filename LIKE %s
                          AND (dc.embedding <=> %s::vector) <= %s
                        ORDER BY dc.embedding <=> %s::vector
                        LIMIT %s
                        """,
                        (embedding_str, f'%{file_type_filter}', embedding_str,
                         max_distance, embedding_str, top_k),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT dc.chunk_text, d.filename, dc.chunk_index,
                               1 - (dc.embedding <=> %s::vector) AS similarity,
                               dc.document_id
                        FROM document_chunks dc
                        JOIN documents d ON dc.document_id = d.id
                        WHERE dc.embedding IS NOT NULL
                          AND (dc.embedding <=> %s::vector) <= %s
                        ORDER BY dc.embedding <=> %s::vector
                        LIMIT %s
                        """,
                        (embedding_str, embedding_str, max_distance, embedding_str, top_k),
                    )

                results = cursor.fetchall()
                logger.debug(f"Found {len(results)} chunks above similarity threshold {min_similarity}")
                return results

    def get_adjacent_chunks(
        self, document_id: int, chunk_index: int, window_size: int = 1
    ) -> List[Tuple[str, int]]:
        """
        Get chunks immediately before and after a given chunk.

        Args:
            document_id: ID of the document
            chunk_index: Index of the centre chunk
            window_size: Number of chunks before/after to include

        Returns:
            List of ``(chunk_text, chunk_index)`` ordered by chunk_index

        Raises:
            DatabaseUnavailableError: If database is not connected
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot get adjacent chunks: Database is not connected")

        logger.debug(
            f"Getting adjacent chunks for doc {document_id}, chunk {chunk_index}, window {window_size}"
        )
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT chunk_text, chunk_index
                    FROM document_chunks
                    WHERE document_id = %s
                      AND chunk_index BETWEEN %s AND %s
                    ORDER BY chunk_index
                    """,
                    (document_id, chunk_index - window_size, chunk_index + window_size),
                )
                results = cursor.fetchall()
                logger.debug(f"Retrieved {len(results)} adjacent chunks")
                return results

    def get_document_count(self) -> int:
        """Return the total number of documents in the database."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot get document count: Database is not connected")

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM documents")
                count = cursor.fetchone()[0]
                logger.debug(f"Document count: {count}")
                return count

    def get_chunk_count(self) -> int:
        """Return the total number of chunks in the database."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot get chunk count: Database is not connected")

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM document_chunks")
                count = cursor.fetchone()[0]
                logger.debug(f"Chunk count: {count}")
                return count

    def get_all_documents(self) -> List[Dict[str, Any]]:
        """
        List all documents with metadata.

        Returns:
            List of dicts with keys: id, filename, created_at, chunk_count

        Raises:
            DatabaseUnavailableError: If database is not connected
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot get documents: Database is not connected")

        logger.debug("Getting all documents")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT d.id, d.filename, d.created_at, COUNT(dc.id) AS chunk_count
                    FROM documents d
                    LEFT JOIN document_chunks dc ON d.id = dc.document_id
                    GROUP BY d.id, d.filename, d.created_at
                    ORDER BY d.created_at DESC
                """)
                rows = cursor.fetchall()
                documents = [
                    {
                        'id': row[0],
                        'filename': row[1],
                        'created_at': row[2].isoformat() if row[2] else None,
                        'chunk_count': row[3],
                    }
                    for row in rows
                ]
                logger.debug(f"Retrieved {len(documents)} documents")
                return documents

    def document_exists(self, filename: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Check whether a document with the given filename already exists.

        Returns:
            Tuple of ``(exists, doc_info)`` where ``doc_info`` has keys
            ``id``, ``created_at``, ``chunk_count``.

        Raises:
            DatabaseUnavailableError: If database is not connected
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot check document existence: Database is not connected")

        logger.debug(f"Checking if document exists: {filename}")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT d.id, d.created_at, COUNT(dc.id) AS chunk_count
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
                        'chunk_count': row[2],
                    }
                    logger.debug(f"Document exists: {filename} (ID: {row[0]})")
                    return True, doc_info
                logger.debug(f"Document does not exist: {filename}")
                return False, {}

    def get_chunk_statistics(self) -> Dict[str, Any]:
        """
        Return statistics about chunks (totals, embedding coverage, samples).

        Raises:
            DatabaseUnavailableError: If database is not connected
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot get chunk statistics: Database is not connected")

        logger.debug("Getting chunk statistics")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT COUNT(*) AS total,
                           COUNT(embedding) AS with_embeddings,
                           AVG(LENGTH(chunk_text)) AS avg_length
                    FROM document_chunks
                """)
                row = cursor.fetchone()
                total = row[0]
                with_embeddings = row[1]
                avg_length = float(row[2]) if row[2] else 0.0

                cursor.execute("""
                    SELECT d.filename, dc.chunk_index, dc.chunk_text,
                           LENGTH(dc.chunk_text) AS length,
                           dc.embedding IS NOT NULL AS has_embedding
                    FROM document_chunks dc
                    JOIN documents d ON dc.document_id = d.id
                    ORDER BY RANDOM()
                    LIMIT 3
                """)
                samples = [
                    {
                        'filename': r[0],
                        'chunk_index': r[1],
                        'preview': r[2][:200] + '...' if len(r[2]) > 200 else r[2],
                        'length': r[3],
                        'has_embedding': r[4],
                    }
                    for r in cursor.fetchall()
                ]

                stats = {
                    'total_chunks': total,
                    'chunks_with_embeddings': with_embeddings,
                    'chunks_without_embeddings': total - with_embeddings,
                    'avg_chunk_length': round(avg_length, 2),
                    'sample_chunks': samples,
                }
                logger.info(f"Chunk statistics: {total} total, {with_embeddings} with embeddings")
                return stats

    def search_chunks_by_text(
        self, search_text: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Case-insensitive text search over chunk content (for debugging).

        Args:
            search_text: Text to search for
            limit: Maximum number of results

        Returns:
            List of dicts with keys: filename, chunk_index, preview, full_text, length

        Raises:
            DatabaseUnavailableError: If database is not connected
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot search chunks by text: Database is not connected")

        logger.debug(f"Searching chunks for text: {search_text}")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT d.filename, dc.chunk_index, dc.chunk_text,
                           LENGTH(dc.chunk_text) AS length
                    FROM document_chunks dc
                    JOIN documents d ON dc.document_id = d.id
                    WHERE dc.chunk_text ILIKE %s
                    ORDER BY dc.chunk_index
                    LIMIT %s
                """, (f'%{search_text}%', limit))
                results = [
                    {
                        'filename': r[0],
                        'chunk_index': r[1],
                        'preview': r[2][:200] + '...' if len(r[2]) > 200 else r[2],
                        'full_text': r[2],
                        'length': r[3],
                    }
                    for r in cursor.fetchall()
                ]
                logger.info(f"Found {len(results)} chunks containing '{search_text}'")
                return results

    def delete_all_documents(self) -> None:
        """
        Delete every document and all its chunks.

        WARNING: This operation cannot be undone!

        Raises:
            DatabaseUnavailableError: If database is not connected
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot delete documents: Database is not connected")

        logger.warning("Deleting ALL documents and chunks")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM document_chunks")
                chunks_deleted = cursor.rowcount
                cursor.execute("DELETE FROM documents")
                docs_deleted = cursor.rowcount
                conn.commit()
        logger.info(f"Deleted {docs_deleted} documents and {chunks_deleted} chunks")
