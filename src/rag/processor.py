"""
Document Processor
==================

Main RAG processing engine that coordinates document ingestion,
embedding generation, and delegates to mixins for loading, chunking,
and retrieval.
"""

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Tuple, Optional, Callable, Any, Dict

from .. import config
from ..db import db
from ..ollama_client import ollama_client
from ..utils.logging_config import get_logger
from .loaders import DocumentLoaderMixin
from .chunking import TextChunkerMixin

_NO_EMBEDDING_MODEL = "No embedding model available"
from .retrieval import RetrievalMixin

logger = get_logger(__name__)

# Try to import monitoring - graceful degradation if not available
try:
    from ..monitoring import timed, counted
except ImportError:
    def timed(_metric_name):  # noqa: E306
        return lambda func: func
    def counted(_metric_name, _labels=None):  # noqa: E306
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
        self.embedding_model: Optional[str] = None
        self.bm25_scorer = None
        self._corpus_chunks: List[str] = []
        self._corpus_metadata: List[Dict[str, Any]] = []
        logger.info("DocumentProcessor initialized")
    
    @timed('rag.generate_embeddings')
    @counted('rag.embedding_batches')
    def generate_embeddings_batch(self, texts: List[str], model: Optional[str] = None, batch_size: Optional[int] = None) -> List[Optional[List[float]]]:
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
            
            for text in batch:
                success, embedding = ollama_client.generate_embedding(model, text)
                if success:
                    embeddings.append(embedding)
                else:
                    embeddings.append(None)
                    logger.warning(f"Failed to generate embedding for text at index {len(embeddings)-1}")
        
        logger.info(f"Generated embeddings for {len(texts)} texts using model {model} ({sum(1 for e in embeddings if e is not None)} successful)")
        return embeddings
    
    def process_document_chunk(
        self,
        doc_id: int,
        chunk_text: str,
        chunk_index: int,
        model: str
    ) -> Optional[Tuple[int, str, int, List[float]]]:
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
        progress_callback: Optional[Callable[[str], None]],
    ) -> Tuple[bool, str, Optional[List[Dict[str, Any]]]]:
        """Load a document and return (success, error_msg, chunks_with_metadata)."""
        if progress_callback:
            progress_callback(f"Loading {filename}...")

        if ext == '.pdf':
            success, pages_or_error = self._load_pdf_with_pages(file_path)
            if not success:
                return False, f"Failed to load {filename}: {pages_or_error}", None
            pages_data = pages_or_error
            logger.info(f"Successfully loaded {len(pages_data)} pages with metadata")
            if progress_callback:
                progress_callback(f"Chunking {filename}...")
            chunks_with_metadata = self.chunk_pages_with_metadata(pages_data)
            if not chunks_with_metadata:
                return False, f"No chunks generated from {filename}", None
            logger.info(f"Generated {len(chunks_with_metadata)} chunks with metadata")
            return True, "", chunks_with_metadata

        success, content = self.load_document(file_path)
        if not success:
            return False, f"Failed to load {filename}: {content}", None
        logger.info(f"Successfully loaded {len(content)} characters")
        if not content or len(content.strip()) < 10:
            return False, f"Document {filename} has insufficient content ({len(content)} chars)", None
        if progress_callback:
            progress_callback(f"Chunking {filename}...")
        chunk_texts = self.chunk_text(content)
        if not chunk_texts:
            return False, f"No chunks generated from {filename}", None
        chunks_with_metadata = [
            {'text': c, 'page_number': None, 'section_title': None, 'chunk_index': i}
            for i, c in enumerate(chunk_texts)
        ]
        logger.info(f"Generated {len(chunks_with_metadata)} chunks")
        return True, "", chunks_with_metadata

    def _build_embeddings_batch(
        self,
        chunks_with_metadata: List[Dict[str, Any]],
        doc_id: int,
        embedding_model: str,
        filename: str,
        progress_callback: Optional[Callable[[str], None]],
    ) -> Tuple[List[Dict[str, Any]], int]:
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

    def _build_embeddings_parallel(
        self,
        chunks_with_metadata: List[Dict[str, Any]],
        doc_id: int,
        embedding_model: str,
        filename: str,
        progress_callback: Optional[Callable[[str], None]],
    ) -> Tuple[List[Dict[str, Any]], int]:
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
                try:
                    result = future.result()
                except Exception as exc:
                    logger.warning(f"Chunk embedding task failed: {exc}")
                    failed += 1
                    continue
                if result:
                    cm = futures[future]
                    metadata = {k: cm[k] for k in ('page_number', 'section_title') if cm.get(k)}
                    chunks_data.append({
                        'doc_id': result[0], 'chunk_text': result[1],
                        'chunk_index': result[2], 'embedding': result[3], 'metadata': metadata
                    })
                else:
                    failed += 1
                if progress_callback:
                    pct = len(chunks_data) / len(chunks_with_metadata) * 100
                    progress_callback(f"Processing {filename}: {pct:.1f}% ({len(chunks_data)}/{len(chunks_with_metadata)} chunks)")
        return chunks_data, failed

    @timed('rag.ingest_document')
    @counted('rag.document_ingestions')
    def ingest_document(
        self,
        file_path: str,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> Tuple[bool, str, Optional[int]]:
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

            exists, doc_info = db.document_exists(filename)
            if exists:
                message = (
                    f"Document '{filename}' already exists (ID: {doc_info['id']}, "
                    f"{doc_info['chunk_count']} chunks). Skipping ingestion."
                )
                logger.info(message)
                if progress_callback:
                    progress_callback(message)
                return True, message, doc_info['id']

            if not os.path.exists(file_path):
                error_msg = f"File not found: {file_path}"
                logger.error(error_msg)
                return False, error_msg, None

            ext = Path(file_path).suffix.lower()
            ok, err, chunks_with_metadata = self._load_document_chunks(file_path, filename, ext, progress_callback)
            if not ok:
                logger.error(err)
                return False, err, None

            # Build content preview for the document record
            if ext == '.pdf':
                success_pages, pages_or_err = self._load_pdf_with_pages(file_path)
                content_preview = pages_or_err[0]['text'][:1000] if success_pages else ""
            else:
                _, raw_content = self.load_document(file_path)
                content_preview = raw_content[:1000]

            doc_id = db.insert_document(
                filename=filename,
                content=content_preview,
                metadata={'total_chunks': len(chunks_with_metadata), 'file_path': file_path}
            )
            logger.debug(f"Document ID: {doc_id}")

            embedding_model = ollama_client.get_embedding_model()
            if not embedding_model:
                logger.error(_NO_EMBEDDING_MODEL)
                return False, _NO_EMBEDDING_MODEL, None

            logger.info(f"Using embedding model: {embedding_model}")
            if progress_callback:
                progress_callback(f"Generating embeddings for {len(chunks_with_metadata)} chunks...")

            try:
                chunks_data, failed_chunks = self._build_embeddings_batch(
                    chunks_with_metadata, doc_id, embedding_model, filename, progress_callback
                )
                logger.info(f"Batch processing complete: {len(chunks_data)} ok, {failed_chunks} failed")
            except ImportError:
                logger.warning("BatchEmbeddingProcessor not available, falling back to parallel processing")
                chunks_data, failed_chunks = self._build_embeddings_parallel(
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
        file_paths: List[str],
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> List[Tuple[bool, str, Optional[int]]]:
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
