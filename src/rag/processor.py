"""
Document Processor
==================

Main RAG processing engine that coordinates document ingestion,
embedding generation, and delegates to mixins for loading, chunking,
and retrieval.
"""

import hashlib
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .. import config
from ..db import db
from ..monitoring import counted, timed

# Read via globals() in __init__ so tests can patch src.rag.processor.ollama_client;
# ruff cannot see that access, hence the noqa.
from ..ollama_client import ollama_client  # noqa: F401
from ..utils.logging_config import get_logger
from .chunking import TextChunkerMixin
from .doc_type import ChunkerRegistry, DocTypeClassifier
from .loaders import DocumentLoaderMixin

_NO_EMBEDDING_MODEL = (
    "Welcome to LocalChat! Enjoy your stay. "
    "No embedding model is configured yet — please download one in the Models section "
    "(e.g. nomic-embed-text) to start ingesting documents."
)
from .loaders import _detect_language
from .retrieval import RetrievalMixin


def _compute_file_hash(file_path: str) -> str:
    """Return the SHA-256 hex digest of a file's raw bytes."""
    h = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for block in iter(lambda: f.read(65536), b''):
            h.update(block)
    return h.hexdigest()

logger = get_logger(__name__)


class DocumentProcessor(DocumentLoaderMixin, TextChunkerMixin, RetrievalMixin):
    """
    Handles document loading, chunking, and embedding.

    Main RAG processing engine that coordinates document ingestion,
    text chunking with hierarchical splitting, embedding generation,
    and context retrieval for question-answering.

    Attributes:
        embedding_model (Optional[str]): Name of embedding model to use
    """

    def __init__(
        self,
        db: Any = None,
        ollama_client: Any = None,
    ) -> None:
        # globals() reads the module-level names so patches on src.rag.processor.db
        # and .ollama_client are respected when creating instances inside tests.
        _g = globals()
        self._db = db if db is not None else _g['db']
        self._ollama_client = ollama_client if ollama_client is not None else _g['ollama_client']
        self.embedding_model: str | None = None
        self._corpus_chunks: list[str] = []
        self._corpus_metadata: list[dict[str, Any]] = []
        logger.info("DocumentProcessor initialized")

    @timed('rag.generate_embeddings')
    @counted('rag.embedding_batches')
    def generate_embeddings_batch(self, texts: list[str], model: str | None = None, batch_size: int | None = None) -> list[list[float] | None]:
        """
        Generate embeddings for a batch of texts with configurable batch size.

        Args:
            texts: List of text strings to embed
            model: Embedding model name (default: from config)
            batch_size: Number of texts to process at once (default: from config)

        Returns:
            List of embeddings (or None for failed items)
        """
        if model is None:
            model = self.embedding_model or self._ollama_client.get_embedding_model()
            if model is None:
                logger.error(_NO_EMBEDDING_MODEL)
                return [None] * len(texts)

        batch_size_int: int = batch_size if batch_size is not None else config.BATCH_SIZE

        embeddings = []
        total = len(texts)

        for i in range(0, total, batch_size_int):
            batch = texts[i:i+batch_size_int]
            batch_end = min(i+batch_size_int, total)

            logger.debug(f"Processing embedding batch {i//batch_size_int + 1}: texts {i+1}-{batch_end} of {total}")

            batch_results = self._ollama_client.generate_embeddings_batch(model, batch)
            embeddings.extend(batch_results)
            failed = sum(1 for e in batch_results if e is None)
            if failed:
                logger.warning(f"Failed to generate {failed} embedding(s) in batch {i//batch_size_int + 1}")

        logger.info(f"Generated embeddings for {len(texts)} texts using model {model} ({sum(1 for e in embeddings if e is not None)} successful)")
        return embeddings

    def process_document_chunk(
        self,
        doc_id: int,
        chunk_text: str,
        chunk_index: int,
        model: str
    ) -> tuple[int, str, int, list[float]] | None:
        """
        Process a single chunk (for parallel processing).

        Args:
            doc_id: Document ID
            chunk_text: Text content of chunk
            chunk_index: Index of chunk in document
            model: Name of embedding model

        Returns:
            Tuple of (doc_id, chunk_text, chunk_index, embedding) or None if failed
        """
        success, embedding = self._ollama_client.generate_embedding(model, chunk_text)
        if success and embedding:
            return (doc_id, chunk_text, chunk_index, embedding)
        logger.warning(f"Failed to generate embedding for chunk {chunk_index}")
        return None

    def _load_document_chunks(
        self,
        file_path: str,
        filename: str,
        ext: str,
        progress_callback: Callable[[str], None] | None,
    ) -> tuple[bool, str, list[dict[str, Any]] | None, str | None, str, str]:
        """
        Load a document and return
        (success, error_msg, chunks_with_metadata, raw_content, doc_type_str, chunker_version).
        """
        doc_type = DocTypeClassifier.classify(ext)
        chunker_fn, chunker_version = ChunkerRegistry.get_chunker(doc_type)
        ok, err, chunks, raw = chunker_fn(self, file_path, filename, progress_callback)
        if ok:
            assert chunks is not None, "chunker guarantees chunks when ok=True"
            logger.info(f"Generated {len(chunks)} chunks via {chunker_version}")
        return ok, err, chunks, raw, doc_type.value, chunker_version

    def _build_embeddings_batch(
        self,
        chunks_with_metadata: list[dict[str, Any]],
        doc_id: int,
        embedding_model: str,
        filename: str,
        progress_callback: Callable[[str], None] | None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Generate embeddings via BatchEmbeddingProcessor. Returns (chunks_data, failed)."""
        from ..performance.batch_processor import BatchEmbeddingProcessor

        batch_size = getattr(config, 'BATCH_SIZE', 64)
        max_workers = getattr(config, 'BATCH_MAX_WORKERS', 8)
        # self._ollama_client, not the module global: this path ignored an injected
        # client entirely, so a caller that supplied one got it for some calls and the
        # global for the batch. Invisible while every test mocked the layer above.
        processor = BatchEmbeddingProcessor(
            self._ollama_client, batch_size=batch_size, max_workers=max_workers
        )
        embeddings = processor.process_batch([c['text'] for c in chunks_with_metadata], embedding_model)

        chunks_data = []
        failed = 0
        for idx, (chunk_meta, embedding) in enumerate(zip(chunks_with_metadata, embeddings, strict=False)):
            if embedding is None:
                failed += 1
                logger.warning(f"Failed to generate embedding for chunk {idx}")
                continue
            metadata = {k: chunk_meta[k] for k in ('page_number', 'section_title') if chunk_meta.get(k)}
            chunks_data.append({
                'doc_id': doc_id, 'chunk_text': chunk_meta['text'],
                'chunk_index': chunk_meta['chunk_index'], 'embedding': embedding, 'metadata': metadata
            })
            if progress_callback and (idx + 1) % 10 == 0:
                pct = (idx + 1) / len(chunks_with_metadata) * 100
                progress_callback(f"Processing {filename}: {pct:.1f}% ({idx + 1}/{len(chunks_with_metadata)} chunks)")
        return chunks_data, failed

    def _process_parallel_future(
        self,
        future,
        future_map: dict,
    ) -> dict[str, Any] | None:
        """Extract chunk data from a completed parallel embedding future. Returns None on failure."""
        try:
            result = future.result()
        except Exception as exc:
            logger.warning(f"Chunk embedding task failed: {exc}")
            return None
        if not result:
            return None
        cm = future_map[future]
        metadata = {k: cm[k] for k in ('page_number', 'section_title') if cm.get(k)}
        return {
            'doc_id': result[0], 'chunk_text': result[1],
            'chunk_index': result[2], 'embedding': result[3], 'metadata': metadata
        }

    def _build_embeddings_parallel(
        self,
        chunks_with_metadata: list[dict[str, Any]],
        doc_id: int,
        embedding_model: str,
        filename: str,
        progress_callback: Callable[[str], None] | None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Generate embeddings via ThreadPoolExecutor fallback. Returns (chunks_data, failed)."""
        chunks_data = []
        failed = 0
        with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as executor:
            futures = {
                executor.submit(
                    self.process_document_chunk, doc_id,
                    cm['text'], cm['chunk_index'], embedding_model
                ): cm for cm in chunks_with_metadata
            }
            for future in as_completed(futures):
                chunk_data = self._process_parallel_future(future, futures)
                if chunk_data:
                    chunks_data.append(chunk_data)
                else:
                    failed += 1
                if progress_callback:
                    pct = len(chunks_data) / len(chunks_with_metadata) * 100
                    progress_callback(f"Processing {filename}: {pct:.1f}% ({len(chunks_data)}/{len(chunks_with_metadata)} chunks)")
        return chunks_data, failed

    def _run_embedding_pipeline(
        self,
        chunks_with_metadata: list[dict[str, Any]],
        doc_id: int,
        embedding_model: str,
        filename: str,
        progress_callback: Callable[[str], None] | None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Run batch embedding, falling back to parallel processing if unavailable."""
        try:
            chunks_data, failed_chunks = self._build_embeddings_batch(
                chunks_with_metadata, doc_id, embedding_model, filename, progress_callback
            )
            logger.info(f"Batch processing complete: {len(chunks_data)} ok, {failed_chunks} failed")
            return chunks_data, failed_chunks
        except ImportError:
            logger.warning("BatchEmbeddingProcessor not available, falling back to parallel processing")
            return self._build_embeddings_parallel(
                chunks_with_metadata, doc_id, embedding_model, filename, progress_callback
            )

    def _prepare_for_ingestion(
        self,
        filename: str,
        file_hash: str,
        workspace_id: str | None,
        progress_callback: Callable[[str], None] | None,
    ) -> tuple[tuple[bool, str, int | None] | None, int | None]:
        """Check for an existing document with this filename in this workspace.

        Returns ``(finished_result, None)`` if ingestion should be skipped, or
        ``(None, replace_doc_id)`` if ingestion should continue — ``replace_doc_id``
        is the id of an existing document to update in place once the new content
        is ready. The update is deferred (no DB write happens here) so it lands
        atomically with the fresh chunk insert, after slow chunking/embedding I/O
        has already completed.
        """
        exists, doc_info = self._db.document_exists(filename, workspace_id)
        if not exists:
            return None, None
        # A zero-chunk document means a prior ingestion died between the document
        # write and insert_chunks_batch() — matching content_hash alone would
        # otherwise report "already up to date" forever and never retry, a
        # permanent silent-corruption state. Fall through to replace.
        if doc_info.get('content_hash') == file_hash and doc_info.get('chunk_count', 0) > 0:
            message = (
                f"Document '{filename}' is already up to date "
                f"(ID: {doc_info['id']}, {doc_info['chunk_count']} chunks). "
                f"Skipping ingestion."
            )
            logger.info(message)
            if progress_callback:
                progress_callback(message)
            return (True, message, doc_info['id']), None
        # Same filename, different content (or a previously-failed, chunkless
        # ingestion of the same content) — replace.
        logger.info(
            f"Document '{filename}' has changed or is incomplete "
            f"(chunk_count={doc_info.get('chunk_count', 0)}). Replacing ID {doc_info['id']}."
        )
        if progress_callback:
            progress_callback(f"Replacing existing document '{filename}'...")
        return None, doc_info['id']

    def _extract_entities(
        self,
        doc_id: int,
        chunk_ids: list[int],
        chunks_data: list[dict[str, Any]],
    ) -> None:
        """Best-effort GraphRAG entity extraction; never fails the ingest.

        Kept out of ingest_document because it is an optional side-effect with its
        own failure handling, and inlining it pushed that function past the
        cognitive-complexity limit.
        """
        if not config.GRAPH_RAG_ENABLED:
            return
        try:
            from ..graph.extractor import EntityExtractor
            # Build chunks_with_ids from in-memory data + returned IDs —
            # avoids a DB round-trip to re-fetch what we just inserted.
            chunks_with_ids = [
                {'chunk_id': cid, 'chunk_text': cd['chunk_text']}
                for cid, cd in zip(chunk_ids, chunks_data, strict=False)
            ]
            EntityExtractor().extract_for_document(doc_id, chunks_with_ids, db)
        except Exception as graph_exc:
            logger.warning(f"[GraphRAG] Entity extraction failed (non-fatal): {graph_exc}")

    @timed('rag.ingest_document')
    @counted('rag.document_ingestions')
    def ingest_document(
        self,
        file_path: str,
        progress_callback: Callable[[str], None] | None = None,
        workspace_id: str | None = None,
        source_id: str | None = None,
    ) -> tuple[bool, str, int | None]:
        """
        Ingest a single document with OPTIMIZED batch embedding processing.

        Args:
            file_path: Path to document file
            progress_callback: Optional callback for progress updates

        Returns:
            Tuple of (success: bool, message: str, doc_id: Optional[int])
        """
        try:
            filename = os.path.basename(file_path)
            logger.info(f"Starting ingestion for: {filename}")

            file_hash = _compute_file_hash(file_path)

            early, replace_doc_id = self._prepare_for_ingestion(
                filename, file_hash, workspace_id, progress_callback
            )
            if early is not None:
                return early

            if not os.path.exists(file_path):
                error_msg = f"File not found: {file_path}"
                logger.error(error_msg)
                return False, error_msg, None

            embedding_model = self._ollama_client.get_embedding_model()
            if not embedding_model:
                logger.error(_NO_EMBEDDING_MODEL)
                return False, _NO_EMBEDDING_MODEL, None

            ext = Path(file_path).suffix.lower()
            ok, err, chunks_with_metadata, raw_content, doc_type_str, chunker_version = \
                self._load_document_chunks(file_path, filename, ext, progress_callback)
            if not ok or chunks_with_metadata is None:
                logger.error(err)
                return False, err, None

            # Build content preview — reuse already-loaded data; no second file read.
            content_preview = (raw_content or (chunks_with_metadata[0]['text'] if chunks_with_metadata else ''))[:1000]
            language = _detect_language(raw_content) if raw_content else None

            logger.info(f"Using embedding model: {embedding_model}")
            if progress_callback:
                progress_callback(f"Generating embeddings for {len(chunks_with_metadata)} chunks...")

            # Placeholder id for a brand-new document (no row exists yet — the
            # real id comes from insert_document() below); when replacing, the
            # id is already known and used directly. Embedding never touches
            # the DB, so no other DB state depends on which id is used here.
            working_doc_id = replace_doc_id if replace_doc_id is not None else 0
            chunks_data, failed_chunks = self._run_embedding_pipeline(
                chunks_with_metadata, working_doc_id, embedding_model, filename, progress_callback
            )

            logger.info(f"Successfully processed {len(chunks_data)} chunks ({failed_chunks} failed)")

            if not chunks_data:
                error_msg = f"No chunks were successfully processed for {filename}"
                logger.error(error_msg)
                return False, error_msg, None

            # The only DB mutation in the whole ingest: retire superseded chunks
            # (if replacing) + write the document row (update in place — same
            # id, so citations stay valid — or insert new) + insert the fresh
            # chunk batch, as one short transaction. Runs only after all slow
            # I/O (chunking, embedding) has already completed.
            metadata = {'total_chunks': len(chunks_data), 'file_path': file_path}
            with self._db.get_connection() as conn:
                if replace_doc_id is not None:
                    self._db.soft_delete_chunks_for_document(replace_doc_id, conn=conn)
                    self._db.update_document(
                        replace_doc_id,
                        content=content_preview,
                        metadata=metadata,
                        content_hash=file_hash,
                        doc_type=doc_type_str,
                        chunker_version=chunker_version,
                        language=language,
                        conn=conn,
                    )
                    doc_id = replace_doc_id
                else:
                    doc_id = self._db.insert_document(
                        filename=filename,
                        content=content_preview,
                        metadata=metadata,
                        content_hash=file_hash,
                        doc_type=doc_type_str,
                        chunker_version=chunker_version,
                        workspace_id=workspace_id,
                        language=language,
                        source_id=source_id,
                        conn=conn,
                    )
                for chunk in chunks_data:
                    chunk['doc_id'] = doc_id
                chunk_ids = self._db.insert_chunks_batch(chunks_data, conn=conn)
            logger.debug(f"Document ID: {doc_id}")
            logger.info("Chunks inserted successfully")

            self._extract_entities(doc_id, chunk_ids, chunks_data)

            success_msg = f"Successfully ingested {filename} ({len(chunks_data)} chunks)"
            logger.info(success_msg)
            return True, success_msg, doc_id

        except Exception as e:
            error_msg = f"Error ingesting document: {str(e)}"
            logger.exception(error_msg)
            return False, error_msg, None

    def ingest_multiple_documents(
        self,
        file_paths: list[str],
        progress_callback: Callable[[str], None] | None = None
    ) -> list[tuple[bool, str, int | None]]:
        """
        Ingest multiple documents.

        Args:
            file_paths: List of file paths to ingest
            progress_callback: Optional callback for progress updates

        Returns:
            List of (success, message, doc_id) tuples
        """
        results = []
        logger.info(f"Starting ingestion of {len(file_paths)} documents")

        for idx, file_path in enumerate(file_paths):
            if progress_callback:
                progress_callback(f"Processing document {idx + 1}/{len(file_paths)}")

            result = self.ingest_document(file_path, progress_callback)
            results.append(result)

        logger.info("Batch ingestion completed")
        return results


# ============================================================================
# MODULE-LEVEL INSTANCE
# ============================================================================

# Create a singleton instance for use across the application
doc_processor = DocumentProcessor()
logger.debug("Created module-level doc_processor instance")
