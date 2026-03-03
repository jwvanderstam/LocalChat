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
from .retrieval import RetrievalMixin

logger = get_logger(__name__)

# Try to import monitoring - graceful degradation if not available
try:
    from ..monitoring import timed, counted
except ImportError:
    def timed(metric_name): 
        return lambda func: func
    def counted(metric_name, labels=None): 
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
                logger.error("No embedding model available")
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
            logger.debug(f"Full path: {file_path}")
            
            # Check if document already exists
            exists, doc_info = db.document_exists(filename)
            if exists:
                message = f"Document '{filename}' already exists (ID: {doc_info['id']}, {doc_info['chunk_count']} chunks{', ingested on ' + str(doc_info.get('created_at', 'unknown date')) if 'created_at' in doc_info else ''}). Skipping ingestion."
                logger.info(message)
                if progress_callback:
                    progress_callback(message)
                return True, message, doc_info['id']
            
            # Verify file exists
            if not os.path.exists(file_path):
                error_msg = f"File not found: {file_path}"
                logger.error(error_msg)
                return False, error_msg, None
            
            # Load document
            if progress_callback:
                progress_callback(f"Loading {filename}...")
            
            logger.debug("Loading document...")
            
            # Determine file type
            ext = Path(file_path).suffix.lower()
            
            # For PDFs, use page-aware loading for enhanced citations
            if ext == '.pdf':
                success, pages_or_error = self._load_pdf_with_pages(file_path)
                
                if not success:
                    error_msg = f"Failed to load {filename}: {pages_or_error}"
                    logger.error(error_msg)
                    return False, error_msg, None
                
                pages_data = pages_or_error
                logger.info(f"Successfully loaded {len(pages_data)} pages with metadata")
                
                # Chunk with metadata preservation
                if progress_callback:
                    progress_callback(f"Chunking {filename}...")
                
                logger.debug("Chunking document with metadata...")
                chunks_with_metadata = self.chunk_pages_with_metadata(pages_data)
                
                if not chunks_with_metadata:
                    error_msg = f"No chunks generated from {filename}"
                    logger.error(error_msg)
                    return False, error_msg, None
                
                logger.info(f"Generated {len(chunks_with_metadata)} chunks with metadata")
                
            else:
                # For non-PDF files, use standard loading
                success, content = self.load_document(file_path)
                
                if not success:
                    error_msg = f"Failed to load {filename}: {content}"
                    logger.error(error_msg)
                    return False, error_msg, None
                
                logger.info(f"Successfully loaded {len(content)} characters")
                
                # Check if content is meaningful
                if not content or len(content.strip()) < 10:
                    error_msg = f"Document {filename} has insufficient content (only {len(content)} characters)"
                    logger.error(error_msg)
                    return False, error_msg, None
                
                # Chunk document (without metadata)
                if progress_callback:
                    progress_callback(f"Chunking {filename}...")
                
                logger.debug("Chunking document...")
                chunk_texts = self.chunk_text(content)
                
                if not chunk_texts:
                    error_msg = f"No chunks generated from {filename}"
                    logger.error(error_msg)
                    return False, error_msg, None
                
                # Convert to metadata format (without page numbers/sections)
                chunks_with_metadata = [
                    {
                        'text': chunk,
                        'page_number': None,
                        'section_title': None,
                        'chunk_index': idx
                    }
                    for idx, chunk in enumerate(chunk_texts)
                ]
                
                logger.info(f"Generated {len(chunks_with_metadata)} chunks")
            
            # Insert document record
            logger.debug("Inserting document record...")
            
            # Get content preview for document record
            if ext == '.pdf':
                content_preview = pages_data[0]['text'][:1000] if pages_data else ""
            else:
                content_preview = content[:1000]
            
            doc_id = db.insert_document(
                filename=filename,
                content=content_preview,
                metadata={'total_chunks': len(chunks_with_metadata), 'file_path': file_path}
            )
            logger.debug(f"Document ID: {doc_id}")
            
            # Get embedding model
            embedding_model = ollama_client.get_embedding_model()
            if not embedding_model:
                error_msg = "No embedding model available"
                logger.error(error_msg)
                return False, error_msg, None
            
            logger.info(f"Using embedding model: {embedding_model}")
            
            if progress_callback:
                progress_callback(f"Generating embeddings for {len(chunks_with_metadata)} chunks...")
            
            # Extract chunk texts for embedding generation
            chunk_texts = [chunk_data['text'] for chunk_data in chunks_with_metadata]
            
            # Use BatchEmbeddingProcessor for faster embedding generation
            try:
                from ..performance.batch_processor import BatchEmbeddingProcessor
                
                batch_size = getattr(config, 'BATCH_SIZE', 64)
                max_workers = getattr(config, 'BATCH_MAX_WORKERS', 8)
                
                logger.info(f"Using BatchEmbeddingProcessor (batch_size={batch_size}, workers={max_workers})")
                
                processor = BatchEmbeddingProcessor(
                    ollama_client,
                    batch_size=batch_size,
                    max_workers=max_workers
                )
                
                embeddings = processor.process_batch(chunk_texts, embedding_model)
                
                # Build chunks_data from embeddings with metadata
                chunks_data = []
                failed_chunks = 0
                
                for idx, (chunk_meta, embedding) in enumerate(zip(chunks_with_metadata, embeddings)):
                    if embedding is not None:
                        metadata = {}
                        if chunk_meta.get('page_number'):
                            metadata['page_number'] = chunk_meta['page_number']
                        if chunk_meta.get('section_title'):
                            metadata['section_title'] = chunk_meta['section_title']
                        
                        chunks_data.append({
                            'doc_id': doc_id,
                            'chunk_text': chunk_meta['text'],
                            'chunk_index': chunk_meta['chunk_index'],
                            'embedding': embedding,
                            'metadata': metadata
                        })
                    else:
                        failed_chunks += 1
                        logger.warning(f"Failed to generate embedding for chunk {idx}")
                    
                    if progress_callback and (idx + 1) % 10 == 0:
                        progress = ((idx + 1) / len(chunks_with_metadata)) * 100
                        progress_callback(f"Processing {filename}: {progress:.1f}% ({idx + 1}/{len(chunks_with_metadata)} chunks)")
                
                logger.info(f"Batch processing complete: {len(chunks_data)} successful, {failed_chunks} failed")
                
            except ImportError:
                # Fallback to old method if BatchEmbeddingProcessor not available
                logger.warning("BatchEmbeddingProcessor not available, falling back to parallel processing")
                
                chunks_data = []
                failed_chunks = 0
                
                with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as executor:
                    futures = {
                        executor.submit(
                            self.process_document_chunk,
                            doc_id,
                            chunk_meta['text'],
                            chunk_meta['chunk_index'],
                            embedding_model
                        ): chunk_meta for chunk_meta in chunks_with_metadata
                    }
                    
                    for future in as_completed(futures):
                        try:
                            result = future.result()
                        except Exception as exc:
                            logger.warning(f"Chunk embedding task failed: {exc}")
                            failed_chunks += 1
                            continue
                        if result:
                            chunk_meta = futures[future]
                            metadata = {}
                            if chunk_meta.get('page_number'):
                                metadata['page_number'] = chunk_meta['page_number']
                            if chunk_meta.get('section_title'):
                                metadata['section_title'] = chunk_meta['section_title']
                            
                            chunks_data.append({
                                'doc_id': result[0],
                                'chunk_text': result[1],
                                'chunk_index': result[2],
                                'embedding': result[3],
                                'metadata': metadata
                            })
                        else:
                            failed_chunks += 1
                        
                        if progress_callback:
                            progress = len(chunks_data) / len(chunks_with_metadata) * 100
                            progress_callback(f"Processing {filename}: {progress:.1f}% ({len(chunks_data)}/{len(chunks_with_metadata)} chunks)")
            
            logger.info(f"Successfully processed {len(chunks_data)} chunks ({failed_chunks} failed)")
            
            # Batch insert chunks
            if chunks_data:
                logger.debug(f"Inserting {len(chunks_data)} chunks into database...")
                db.insert_chunks_batch(chunks_data)
                logger.info("Chunks inserted successfully")
            else:
                error_msg = f"No chunks were successfully processed for {filename}"
                logger.error(error_msg)
                return False, error_msg, None
            
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
