from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
from psycopg.types.json import Jsonb

from ..utils.encryption import encrypt as _encrypt
from ..utils.logging_config import get_logger
from ..utils.sanitization import escape_sql_like
from .connection import DatabaseUnavailableError

if TYPE_CHECKING:
    from .connection import MixinHost
else:
    MixinHost = object

logger = get_logger(__name__)


class DocumentsMixin(MixinHost):
    """Mixin that adds document and chunk operations to the Database class."""

    def insert_document(
        self,
        filename: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        content_hash: str | None = None,
        doc_type: str | None = None,
        chunker_version: str | None = None,
        workspace_id: str | None = None,
        language: str | None = None,
        source_id: str | None = None,
    ) -> int:
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot insert document: Database is not connected")

        # PostgreSQL text columns reject NUL (0x00) bytes; strip them defensively.
        filename = filename.replace('\x00', '')
        content = content.replace('\x00', '')

        logger.debug(f"Inserting document: {filename}")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO documents"
                    " (filename, content, metadata, content_hash, doc_type, chunker_version, workspace_id, language, source_id)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (filename, _encrypt(content), Jsonb(metadata or {}), content_hash, doc_type, chunker_version, workspace_id, language, source_id),
                )
                row = cursor.fetchone()
                assert row is not None, "INSERT ... RETURNING id always returns a row"
                doc_id = row[0]
                conn.commit()
        logger.info(f"Document inserted with ID: {doc_id}")
        return doc_id

    def any_local_only_sources(self, filenames: list[str]) -> bool:
        """Used by cloud fallback to block cloud calls when context includes local-only documents."""
        if not filenames or not self.is_connected:
            return False
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT 1 FROM documents WHERE filename = ANY(%s)"
                        " AND local_only = TRUE AND deleted_at IS NULL LIMIT 1",
                        (filenames,),
                    )
                    return cursor.fetchone() is not None
        except Exception as e:
            logger.warning(f"any_local_only_sources query failed: {e}")
            return True  # Conservative: treat as local-only on error

    def get_chunks_with_ids(self, doc_id: int) -> list[dict[str, Any]]:
        """
        Return chunk_text and id for all chunks of a document.

        Used by the GraphRAG entity extractor after ingest.
        """
        if not self.is_connected:
            return []
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id, chunk_text FROM document_chunks WHERE document_id = %s",
                    (doc_id,),
                )
                rows = cursor.fetchall()
        return [{"chunk_id": r[0], "chunk_text": r[1]} for r in rows]

    def delete_document(self, doc_id: int, deleted_by: str | None = None) -> None:
        """
        Soft-delete a document by setting deleted_at / deleted_by.

        Chunks are excluded from live RAG queries via the JOIN on documents.deleted_at;
        the chunk rows themselves are left intact so citation history remains valid.
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot delete document: Database is not connected")

        logger.debug("Soft-deleting document ID: %s", doc_id)
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE documents SET deleted_at = NOW(), deleted_by = %s WHERE id = %s",
                    (deleted_by, doc_id),
                )
                conn.commit()
        logger.info("Document %s soft-deleted", doc_id)

    def purge_document(self, doc_id: int) -> bool:
        """
        Hard-delete only when no chunk_stats row exists for any of this document's chunks.
        Returns False when citations block the purge; True on success.
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot purge document: Database is not connected")

        logger.debug("Purge requested for document ID: %s", doc_id)
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                # Citation precondition: any chunk that was retrieved blocks the purge.
                cursor.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM chunk_stats cs
                        JOIN document_chunks dc ON dc.id = cs.chunk_id
                        WHERE dc.document_id = %s
                    )
                    """,
                    (doc_id,),
                )
                row = cursor.fetchone()
                assert row is not None, "SELECT EXISTS always returns a row"
                if row[0]:
                    logger.info("Purge of document %s blocked: chunk_stats references exist", doc_id)
                    return False

                cursor.execute("DELETE FROM document_chunks WHERE document_id = %s", (doc_id,))
                cursor.execute("DELETE FROM documents WHERE id = %s", (doc_id,))
                conn.commit()
        logger.info("Document %s permanently purged", doc_id)
        return True

    def insert_chunks_batch(
        self,
        chunks_data: list[tuple[int, str, int, list[float] | np.ndarray] | dict[str, Any]],
    ) -> list[int]:
        """Accepts ``(doc_id, chunk_text, chunk_index, embedding)`` tuples or equivalent dicts with optional metadata."""
        if not chunks_data:
            return []

        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot insert chunks: Database is not connected")

        logger.debug(f"Inserting batch of {len(chunks_data)} chunks")

        # Pre-process all rows outside the DB connection to keep CPU work
        # separate from network I/O.
        insert_sql = (
            "INSERT INTO document_chunks"
            " (document_id, chunk_text, chunk_index, embedding, metadata)"
            " VALUES (%s, %s, %s, %s::vector, %s)"
            " RETURNING id"
        )
        rows = []
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
            rows.append((
                doc_id,
                chunk_text.replace('\x00', ''),
                chunk_index,
                self._embedding_to_pg_array(embedding),
                Jsonb(metadata),
            ))

        # Pipeline mode batches all INSERT statements in one round-trip.
        # RETURNING id is collected after the pipeline flushes.
        chunk_ids: list[int] = []
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                with conn.pipeline():
                    for row in rows:
                        cursor.execute(insert_sql, row)
                # Fetch RETURNING results after pipeline flush (outside pipeline block).
                chunk_ids = [r[0] for r in cursor.fetchall()]
            conn.commit()
        logger.info(f"Successfully inserted {len(chunks_data)} chunks")
        return chunk_ids

    def search_similar_chunks(
        self,
        query_embedding: list[float] | np.ndarray,
        top_k: int = 5,
        min_similarity: float = 0.0,
        file_type_filter: str | None = None,
        filename_filter: list[str] | None = None,
        workspace_id: str | None = None,
        source_ids: list[str] | None = None,
    ) -> list[tuple[str, str, int, float, dict[str, Any], int]]:
        """Search via pgvector HNSW; min_similarity applied at DB level to avoid transferring chunks that fail the threshold."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot search chunks: Database is not connected")

        logger.debug(f"Searching for top {top_k} similar chunks (min_similarity={min_similarity})")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                embedding_str = self._embedding_to_pg_array(query_embedding)
                max_distance = 1.0 - min_similarity  # cosine distance = 1 - similarity

                where_extra = ""
                params: list = [embedding_str]
                if file_type_filter:
                    where_extra += "  AND d.filename LIKE %s\n"
                    params.append(f'%{file_type_filter}')
                    logger.debug(f"Searching with file type filter: {file_type_filter}")
                if filename_filter:
                    where_extra += "  AND d.filename = ANY(%s)\n"
                    params.append(filename_filter)
                    logger.debug(f"Searching with filename filter: {len(filename_filter)} file(s)")
                if workspace_id:
                    where_extra += "  AND d.workspace_id = %s\n"
                    params.append(workspace_id)
                if source_ids:
                    where_extra += "  AND d.source_id = ANY(%s)\n"
                    params.append(source_ids)
                params.extend([max_distance, top_k])

                cursor.execute(
                    f"""
                    WITH q AS (SELECT %s::vector AS emb)
                    SELECT dc.chunk_text, d.filename, dc.chunk_index,
                           1 - (dc.embedding <=> q.emb) AS similarity,
                           dc.metadata, dc.id
                    FROM document_chunks dc
                    JOIN documents d ON dc.document_id = d.id
                    CROSS JOIN q
                    WHERE dc.embedding IS NOT NULL
                      AND d.deleted_at IS NULL
                    {where_extra}  AND (dc.embedding <=> q.emb) <= %s
                    ORDER BY dc.embedding <=> q.emb
                    LIMIT %s
                    """,
                    params,
                )

                results = cursor.fetchall()
                logger.debug(f"Found {len(results)} similar chunks")
                return [(r[0], r[1], r[2], r[3], r[4] or {}, r[5]) for r in results]

    def search_similar_chunks_with_scores(
        self,
        query_embedding: list[float] | np.ndarray,
        top_k: int = 5,
        min_similarity: float = 0.0,
        file_type_filter: str | None = None,
    ) -> list[tuple[str, str, int, float, int]]:
        """Returns ``(chunk_text, filename, chunk_index, similarity, document_id)`` tuples."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot search chunks: Database is not connected")

        logger.debug(f"Searching for top {top_k} similar chunks (min_sim={min_similarity})")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                embedding_str = self._embedding_to_pg_array(query_embedding)
                max_distance = 1.0 - min_similarity

                if file_type_filter:
                    cursor.execute(
                        """
                        WITH q AS (SELECT %s::vector AS emb)
                        SELECT dc.chunk_text, d.filename, dc.chunk_index,
                               1 - (dc.embedding <=> q.emb) AS similarity,
                               dc.document_id
                        FROM document_chunks dc
                        JOIN documents d ON dc.document_id = d.id
                        CROSS JOIN q
                        WHERE dc.embedding IS NOT NULL
                          AND d.deleted_at IS NULL
                          AND d.filename LIKE %s
                          AND (dc.embedding <=> q.emb) <= %s
                        ORDER BY dc.embedding <=> q.emb
                        LIMIT %s
                        """,
                        (embedding_str, f'%{file_type_filter}', max_distance, top_k),
                    )
                else:
                    cursor.execute(
                        """
                        WITH q AS (SELECT %s::vector AS emb)
                        SELECT dc.chunk_text, d.filename, dc.chunk_index,
                               1 - (dc.embedding <=> q.emb) AS similarity,
                               dc.document_id
                        FROM document_chunks dc
                        JOIN documents d ON dc.document_id = d.id
                        CROSS JOIN q
                        WHERE dc.embedding IS NOT NULL
                          AND d.deleted_at IS NULL
                          AND (dc.embedding <=> q.emb) <= %s
                        ORDER BY dc.embedding <=> q.emb
                        LIMIT %s
                        """,
                        (embedding_str, max_distance, top_k),
                    )

                results = cursor.fetchall()
                logger.debug(f"Found {len(results)} chunks above similarity threshold {min_similarity}")
                return results

    def get_adjacent_chunks(
        self, document_id: int, chunk_index: int, window_size: int = 1
    ) -> list[tuple[str, int]]:
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

    def get_chunk_by_id(self, chunk_id: int) -> dict[str, Any] | None:
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot get chunk: Database is not connected")

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id, document_id, chunk_index, chunk_text, metadata"
                    " FROM document_chunks WHERE id = %s",
                    (chunk_id,),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        return {
            'id': row[0],
            'document_id': row[1],
            'chunk_index': row[2],
            'chunk_text': row[3],
            'metadata': row[4] or {},
        }

    def get_document_count(self, workspace_id: str | None = None) -> int:
        """Return the number of documents, optionally scoped to a workspace."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot get document count: Database is not connected")

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                if workspace_id:
                    cursor.execute(
                        "SELECT COUNT(*) FROM documents WHERE workspace_id = %s AND deleted_at IS NULL",
                        (workspace_id,),
                    )
                else:
                    cursor.execute("SELECT COUNT(*) FROM documents WHERE deleted_at IS NULL")
                row = cursor.fetchone()
                assert row is not None, "SELECT COUNT(*) always returns a row"
                count = row[0]
                logger.debug(f"Document count: {count}")
                return count

    def get_chunk_count(self, workspace_id: str | None = None) -> int:
        """Return the number of chunks, optionally scoped to a workspace."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot get chunk count: Database is not connected")

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                if workspace_id:
                    cursor.execute(
                        """
                        SELECT COUNT(*) FROM document_chunks dc
                        JOIN documents d ON dc.document_id = d.id
                        WHERE d.workspace_id = %s AND d.deleted_at IS NULL
                        """,
                        (workspace_id,),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT COUNT(*) FROM document_chunks dc
                        JOIN documents d ON dc.document_id = d.id
                        WHERE d.deleted_at IS NULL
                        """
                    )
                row = cursor.fetchone()
                assert row is not None, "SELECT COUNT(*) always returns a row"
                count = row[0]
                logger.debug(f"Chunk count: {count}")
                return count

    def get_all_documents(self, workspace_id: str | None = None) -> list[dict[str, Any]]:
        """List documents (id, filename, created_at, chunk_count), optionally scoped to a workspace."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot get documents: Database is not connected")

        logger.debug("Getting all documents")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                if workspace_id:
                    cursor.execute("""
                        SELECT d.id, d.filename, d.created_at, COUNT(dc.id) AS chunk_count
                        FROM documents d
                        LEFT JOIN document_chunks dc ON d.id = dc.document_id
                        WHERE d.workspace_id = %s AND d.deleted_at IS NULL
                        GROUP BY d.id, d.filename, d.created_at
                        ORDER BY d.created_at DESC
                    """, (workspace_id,))
                else:
                    cursor.execute("""
                        SELECT d.id, d.filename, d.created_at, COUNT(dc.id) AS chunk_count
                        FROM documents d
                        LEFT JOIN document_chunks dc ON d.id = dc.document_id
                        WHERE d.deleted_at IS NULL
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

    def document_exists(self, filename: str) -> tuple[bool, dict[str, Any]]:
        """Return ``(exists, doc_info)``; doc_info has id, created_at, chunk_count, content_hash."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot check document existence: Database is not connected")

        logger.debug(f"Checking if document exists: {filename}")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT d.id, d.created_at, COUNT(dc.id) AS chunk_count, d.content_hash
                    FROM documents d
                    LEFT JOIN document_chunks dc ON d.id = dc.document_id
                    WHERE d.filename = %s AND d.deleted_at IS NULL
                    GROUP BY d.id, d.created_at, d.content_hash
                """, (filename,))
                row = cursor.fetchone()
                if row:
                    doc_info = {
                        'id': row[0],
                        'created_at': row[1].isoformat() if row[1] else None,
                        'chunk_count': row[2],
                        'content_hash': row[3],
                    }
                    logger.debug(f"Document exists: {filename} (ID: {row[0]})")
                    return True, doc_info
                logger.debug(f"Document does not exist: {filename}")
                return False, {}

    def get_chunk_statistics(self) -> dict[str, Any]:
        """Return statistics about chunks (totals, embedding coverage, samples)."""
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
                assert row is not None, "SELECT COUNT(*)/AVG(...) always returns a row"
                total = row[0]
                with_embeddings = row[1]
                avg_length = float(row[2]) if row[2] else 0.0

                cursor.execute("""
                    SELECT d.filename, dc.chunk_index, dc.chunk_text,
                           LENGTH(dc.chunk_text) AS length,
                           dc.embedding IS NOT NULL AS has_embedding
                    FROM document_chunks dc TABLESAMPLE SYSTEM(1)
                    JOIN documents d ON dc.document_id = d.id
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
    ) -> list[dict[str, Any]]:
        """Case-insensitive text search over chunk content (for debugging — not the live search path)."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot search chunks by text: Database is not connected")

        logger.debug("Searching chunks for text: %s", str(search_text)[:100].replace('\r', '').replace('\n', ' '))
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT d.filename, dc.chunk_index, dc.chunk_text,
                           LENGTH(dc.chunk_text) AS length
                    FROM document_chunks dc
                    JOIN documents d ON dc.document_id = d.id
                    WHERE dc.chunk_text ILIKE %s ESCAPE '\\'
                    ORDER BY dc.chunk_index
                    LIMIT %s
                """, (f'%{escape_sql_like(search_text)}%', limit))
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
        """Delete every document and all its chunks. WARNING: irreversible."""
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

    def get_stale_documents(self, max_age_hours: int, workspace_id: str | None = None) -> list[dict[str, Any]]:
        """Return documents whose last_ingested_at is older than max_age_hours.

        Documents without last_ingested_at fall back to created_at for comparison.
        """
        if not self.is_connected:
            return []
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    sql = """
                        SELECT id, filename, workspace_id
                        FROM documents
                        WHERE COALESCE(last_ingested_at, created_at)
                              < NOW() - (INTERVAL '1 hour' * %s)
                          AND deleted_at IS NULL
                    """
                    params: list[Any] = [max_age_hours]
                    if workspace_id:
                        sql += " AND workspace_id = %s"
                        params.append(workspace_id)
                    cursor.execute(sql, params)
                    return [
                        {'id': row[0], 'filename': row[1], 'workspace_id': row[2]}
                        for row in cursor.fetchall()
                    ]
        except Exception as exc:
            logger.warning(f"get_stale_documents failed: {exc}")
            return []

    def update_last_ingested_at(self, doc_id: int) -> None:
        """Set last_ingested_at = NOW() for the given document after re-ingest."""
        if not self.is_connected:
            return
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "UPDATE documents SET last_ingested_at = NOW() WHERE id = %s",
                        (doc_id,),
                    )
                    conn.commit()
        except Exception as exc:
            logger.warning(f"update_last_ingested_at failed for doc {doc_id}: {exc}")
