"""
Document Processor
==================

Main RAG processing engine that coordinates document ingestion,
embedding generation, and delegates to mixins for loading, chunking,
and retrieval.
"""

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .. import config
from ..db import db
from ..ollama_client import ollama_client
from ..utils.logging_config import get_logger
from .chunking import TextChunkerMixin
from .loaders import DocumentLoaderMixin

_NO_EMBEDDING_MODEL = "No embedding model available"
from .retrieval import RetrievalMixin


def _compute_file_hash(file_path: str) -> str:
    """Return the SHA-256 hex digest of a file's raw bytes."""
    h = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for block in iter(lambda: f.read(65536), b''):
            h.update(block)
    return h.hexdigest()

logger = get_logger(__name__)

# Try to import monitoring - graceful degradation if not available
try:
    from ..monitoring import counted, timed
except ImportError:
    def timed(_metric_name: str):  # noqa: E306
        return lambda func: func
    def counted(_metric_name: str, _labels=None):  # noqa: E306
        return lambda func: func


class DocumentProcessor(DocumentLoaderMixin, TextChunkerMixin, RetrievalMixin):
    """
    Handles document loading, chunking, and embedding.

    Main RAG processing engine that coordinates document ingestion,
    text chunking with hierarchical splitting, embedding generation,
    and context retrieval for question-answering.

    Attributes:
        embedding_model (Optional[str]): Name of embedding model to use
        bm25_scorer: BM25 scorer for keyword matching
    """

    def __init__(self) -> None:
        """Initialize document processor."""
        self.embedding_model: str | None = None
        self.bm25_scorer = None
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
            model = self.embedding_model or ollama_client.get_embedding_model()
            if model is None:
                logger.error(_NO_EMBEDDING_MODEL)
                return [None] * len(texts)

        batch_size_int = batch_size or getattr(config, 'BATCH_SIZE', 50)

        embeddings = []
        total = len(texts)

        for i in range(0, total, batch_size_int):
            batch = texts[i:i+batch_size_int]
            batch_end = min(i+batch_size_int, total)

            logger.debug(f"Processing embedding batch {i//batch_size_int + 1}: texts {i+1}-{batch_end} of {total}")

            batch_results = ollama_client.generate_embeddings_batch(model, batch)
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
        success, embedding = ollama_client.generate_embedding(model, chunk_text)
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
    ) -> tuple[bool, str, list[dict[str, Any]] | None, str | None]:
        """Load a document and return (success, error_msg, chunks_with_metadata, raw_content)."""
        if progress_callback:
            progress_callback(f"Loading {filename}...")

        if ext == '.pdf':
            success, pages_or_error = self._load_pdf_with_pages(file_path)
            if not success:
                return False, f"Failed to load {filename}: {pages_or_error}", None, None
            pages_data = pages_or_error
            logger.info(f"Successfully loaded {len(pages_data)} pages with metadata")
            if progress_callback:
                progress_callback(f"Chunking {filename}...")
            chunks_with_metadata = self.chunk_pages_with_metadata(pages_data)
            if not chunks_with_metadata:
                return False, f"No chunks generated from {filename}", None, None
            logger.info(f"Generated {len(chunks_with_metadata)} chunks with metadata")
            return True, "", chunks_with_metadata, None

        success, content = self.load_document(file_path)
        if not success:
            return False, f"Failed to load {filename}: {content}", None, None
        logger.info(f"Successfully loaded {len(content)} characters")
        if not content or len(content.strip()) < 10:
            return False, f"Document {filename} has insufficient content ({len(content)} chars)", None, None
        if progress_callback:
            progress_callback(f"Chunking {filename}...")
        chunk_texts = self.chunk_text(content)
        if not chunk_texts:
            return False, f"No chunks generated from {filename}", None, None
        chunks_with_metadata = [
            {'text': c, 'page_number': None, 'section_title': None, 'chunk_index': i}
            for i, c in enumerate(chunk_texts)
        ]
        logger.info(f"Generated {len(chunks_with_metadata)} chunks")
        return True, "", chunks_with_metadata, content

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
        processor = BatchEmbeddingProcessor(ollama_client, batch_size=batch_size, max_workers=max_workers)
        embeddings = processor.process_batch([c['text'] for c in chunks_with_metadata], embedding_model)

        chunks_data = []
        failed = 0
        for idx, (chunk_meta, embedding) in enumerate(zip(chunks_with_metadata, embeddings)):
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

    @timed('rag.ingest_document')
    @counted('rag.document_ingestions')
    def ingest_document(
        self,
        file_path: str,
        progress_callback: Callable[[str], None] | None = None
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

            exists, doc_info = db.document_exists(filename)
            if exists:
                if doc_info.get('content_hash') == file_hash:
                    message = (
                        f"Document '{filename}' is already up to date "
                        f"(ID: {doc_info['id']}, {doc_info['chunk_count']} chunks). "
                        f"Skipping ingestion."
                    )
                    logger.info(message)
                    if progress_callback:
                        progress_callback(message)
                    return True, message, doc_info['id']

                # Same filename, different content — replace.
                logger.info(
                    f"Document '{filename}' has changed (hash mismatch). "
                    f"Replacing ID {doc_info['id']}."
                )
                if progress_callback:
                    progress_callback(f"Replacing existing document '{filename}'...")
                db.delete_document(doc_info['id'])

            if not os.path.exists(file_path):
                error_msg = f"File not found: {file_path}"
                logger.error(error_msg)
                return False, error_msg, None

            ext = Path(file_path).suffix.lower()
            ok, err, chunks_with_metadata, raw_content = self._load_document_chunks(file_path, filename, ext, progress_callback)
            if not ok:
                logger.error(err)
                return False, err, None

            # Build content preview — reuse already-loaded data; no second file read.
            if ext == '.pdf':
                content_preview = chunks_with_metadata[0]['text'][:1000] if chunks_with_metadata else ""
            else:
                content_preview = (raw_content or '')[:1000]

            doc_id = db.insert_document(
                filename=filename,
                content=content_preview,
                metadata={'total_chunks': len(chunks_with_metadata), 'file_path': file_path},
                content_hash=file_hash,
            )
            logger.debug(f"Document ID: {doc_id}")

            embedding_model = ollama_client.get_embedding_model()
            if not embedding_model:
                logger.error(_NO_EMBEDDING_MODEL)
                return False, _NO_EMBEDDING_MODEL, None

            logger.info(f"Using embedding model: {embedding_model}")
            if progress_callback:
                progress_callback(f"Generating embeddings for {len(chunks_with_metadata)} chunks...")

            chunks_data, failed_chunks = self._run_embedding_pipeline(
                chunks_with_metadata, doc_id, embedding_model, filename, progress_callback
            )

            logger.info(f"Successfully processed {len(chunks_data)} chunks ({failed_chunks} failed)")

            if not chunks_data:
                error_msg = f"No chunks were successfully processed for {filename}"
                logger.error(error_msg)
                return False, error_msg, None

            db.insert_chunks_batch(chunks_data)
            logger.info("Chunks inserted successfully")

            success_msg = f"Successfully ingested {filename} ({len(chunks_data)} chunks)"
            logger.info(success_msg)
            return True, success_msg, doc_id

        except Exception as e:
            error_msg = f"Error ingesting document: {str(e)}"
            logger.error(error_msg, exc_info=True)
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
