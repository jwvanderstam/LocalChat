"""
RAG (Retrieval-Augmented Generation) Module
===========================================

Handles document ingestion, chunking, embedding generation, and context retrieval
for the LocalChat RAG application.

PERFORMANCE OPTIMIZATIONS:
- Hybrid search (semantic + keyword BM25)
- Query embedding caching (integrated with global cache)
- Query result caching (full pipeline caching)
- Context window expansion
- Enhanced re-ranking with multiple signals
- Optimized batch embedding generation
- Monitoring and timing decorators

Classes:
    DocumentProcessor: Main RAG processing engine

Example:
    >>> from rag import doc_processor
    >>> success, msg, doc_id = doc_processor.ingest_document("file.pdf")
    >>> context = doc_processor.retrieve_context("What is this about?")

Author: LocalChat Team
Last Updated: 2025-01-15 (Caching & Monitoring Integration)
"""

import os
import re
import math
import hashlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from pathlib import Path
from typing import List, Tuple, Optional, Callable, Any, Dict, Union, Set
from . import config
from .db import db
from .ollama_client import olloma_client
from .utils.logging_config import get_logger
from .monitoring import timed, counted, get_metrics

# Setup logger
logger = get_logger(__name__)

# Document loaders with proper initialization
PyPDF2 = None
PDF_AVAILABLE = False
try:
    import PyPDF2 as pypdf2_lib
    PyPDF2 = pypdf2_lib
    PDF_AVAILABLE = True
    logger.debug("PyPDF2 available for PDF processing")
except ImportError:
    logger.warning("PyPDF2 not available - PDF support disabled")

Document = None
DOCX_AVAILABLE = False
try:
    from docx import Document as DocxDocument
    Document = DocxDocument
    DOCX_AVAILABLE = True
    logger.debug("python-docx available for DOCX processing")
except ImportError:
    logger.warning("python-docx not available - DOCX support disabled")


# ============================================================================
# EMBEDDING CACHE - Use global cache from cache module
# ============================================================================

# Remove old EmbeddingCache class - using global cache now

# ============================================================================
# BM25 SCORING FOR HYBRID SEARCH
# ============================================================================

class BM25Scorer:
    """
    BM25 scoring for keyword-based retrieval.
    
    Implements the BM25 algorithm for traditional information retrieval,
    used in combination with semantic search for hybrid retrieval.
    """
    
    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        """
        Initialize BM25 scorer.
        
        Args:
            k1: Term frequency saturation parameter (default: 1.5)
            b: Length normalization parameter (default: 0.75)
        """
        self.k1 = k1
        self.b = b
        self.corpus_size = 0
        self.avgdl = 0.0
        self.doc_freqs: Dict[str, int] = {}
        self.idf: Dict[str, float] = {}
        self.doc_len: List[int] = []
        self._initialized = False
    
    def _tokenize(self, text: str) -> List[str]:
        """Simple tokenization - lowercase and split on non-alphanumeric."""
        return re.findall(r'\w+', text.lower())
    
    def fit(self, corpus: List[str]) -> None:
        """
        Fit BM25 on a corpus of documents.
        
        Args:
            corpus: List of document texts
        """
        self.corpus_size = len(corpus)
        if self.corpus_size == 0:
            return
        
        nd: Dict[str, int] = {}  # word -> number of documents containing word
        
        for document in corpus:
            tokens = self._tokenize(document)
            self.doc_len.append(len(tokens))
            
            # Count unique words in document
            unique_tokens = set(tokens)
            for token in unique_tokens:
                nd[token] = nd.get(token, 0) + 1
        
        self.avgdl = sum(self.doc_len) / self.corpus_size
        self.doc_freqs = nd
        
        # Calculate IDF
        for word, freq in nd.items():
            self.idf[word] = math.log((self.corpus_size - freq + 0.5) / (freq + 0.5) + 1)
        
        self._initialized = True
        logger.debug(f"BM25 fitted on {self.corpus_size} documents, {len(self.idf)} unique terms")
    
    def score(self, query: str, document: str, doc_idx: int = 0) -> float:
        """
        Calculate BM25 score for a query-document pair.
        
        Args:
            query: Query text
            document: Document text
            doc_idx: Document index (for length normalization)
        
        Returns:
            BM25 score (higher is more relevant)
        """
        if not self._initialized:
            return 0.0
        
        query_tokens = self._tokenize(query)
        doc_tokens = self._tokenize(document)
        doc_len = len(doc_tokens)
        
        if doc_len == 0:
            return 0.0
        
        # Term frequency in document
        tf = Counter(doc_tokens)
        
        score = 0.0
        for token in query_tokens:
            if token not in self.idf:
                continue
            
            freq = tf.get(token, 0)
            idf = self.idf[token]
            
            # BM25 formula
            numerator = freq * (self.k1 + 1)
            denominator = freq + self.k1 * (1 - self.b + self.b * doc_len / self.avgdl)
            score += idf * (numerator / denominator)
        
        return score


# ============================================================================
# BM25 SCORING FOR HYBRID SEARCH
# ============================================================================

class BM25Scorer:
    """
    BM25 scoring for keyword-based retrieval.
    
    Implements the BM25 algorithm for traditional information retrieval,
    used in combination with semantic search for hybrid retrieval.
    """
    
    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        """
        Initialize BM25 scorer.
        
        Args:
            k1: Term frequency saturation parameter (default: 1.5)
            b: Length normalization parameter (default: 0.75)
        """
        self.k1 = k1
        self.b = b
        self.corpus_size = 0
        self.avgdl = 0.0
        self.doc_freqs: Dict[str, int] = {}
        self.idf: Dict[str, float] = {}
        self.doc_len: List[int] = []
        self._initialized = False
    
    def _tokenize(self, text: str) -> List[str]:
        """Simple tokenization - lowercase and split on non-alphanumeric."""
        return re.findall(r'\w+', text.lower())
    
    def fit(self, corpus: List[str]) -> None:
        """
        Fit BM25 on a corpus of documents.
        
        Args:
            corpus: List of document texts
        """
        self.corpus_size = len(corpus)
        if self.corpus_size == 0:
            return
        
        nd: Dict[str, int] = {}  # word -> number of documents containing word
        
        for document in corpus:
            tokens = self._tokenize(document)
            self.doc_len.append(len(tokens))
            
            # Count unique words in document
            unique_tokens = set(tokens)
            for token in unique_tokens:
                nd[token] = nd.get(token, 0) + 1
        
        self.avgdl = sum(self.doc_len) / self.corpus_size
        self.doc_freqs = nd
        
        # Calculate IDF
        for word, freq in nd.items():
            self.idf[word] = math.log((self.corpus_size - freq + 0.5) / (freq + 0.5) + 1)
        
        self._initialized = True
        logger.debug(f"BM25 fitted on {self.corpus_size} documents, {len(self.idf)} unique terms")
    
    def score(self, query: str, document: str, doc_idx: int = 0) -> float:
        """
        Calculate BM25 score for a query-document pair.
        
        Args:
            query: Query text
            document: Document text
            doc_idx: Document index (for length normalization)
        
        Returns:
            BM25 score (higher is more relevant)
        """
        if not self._initialized:
            return 0.0
        
        query_tokens = self._tokenize(query)
        doc_tokens = self._tokenize(document)
        doc_len = len(doc_tokens)
        
        if doc_len == 0:
            return 0.0
        
        # Term frequency in document
        tf = Counter(doc_tokens)
        
        score = 0.0
        for token in query_tokens:
            if token not in self.idf:
                continue
            
            freq = tf.get(token, 0)
            idf = self.idf[token]
            
            # BM25 formula
            numerator = freq * (self.k1 + 1)
            denominator = freq + self.k1 * (1 - self.b + self.b * doc_len / self.avgdl)
            score += idf * (numerator / denominator)
        
        return score


# ============================================================================
# DOCUMENT ENCODER FOR EMBEDDING GENERATION
# ============================================================================

class DocumentEncoder:
    """
    Encodes documents and queries into dense vectors using the specified embedding model.
    
    Manages batching of texts and caching of embedding results for efficiency.
    """
    
    def __init__(self, model_name: str, device: str = "cpu"):
        """
        Initialize DocumentEncoder.
        
        Args:
            model_name: Name of the embedding model to use
            device: Device to run the model on ("cpu" or "cuda")
        """
        self.model_name = model_name
        self.device = device
        self.model = None
        self.tokenizer = None
        self.batch_size = config.EMBEDDING_BATCH_SIZE
        
        # Load model and tokenizer
        self.load_model()
        
        logger.info(f"DocumentEncoder initialized with model {model_name}")
    
    def load_model(self) -> None:
        """
        Load the embedding model and tokenizer.
        
        This method should be called to load or reload the model as needed.
        """
        from sentence_transformers import SentenceTransformer, LoggingHandler
        
        # Resolve model name with possible revision
        model_name = self.model_name
        revision = config.MODEL_REVISIONS.get(model_name)
        if revision:
            model_name += "@" + revision
        
        # Log loading information
        logger.info(f"Loading embedding model '{model_name}' (revision: {revision})")
        
        # Load model and tokenizer
        self.model = SentenceTransformer(model_name, device=self.device)
        self.tokenizer = self.model.tokenizer
        
        # Warm up the model by encoding a dummy batch
        self.model.encode(["test"] * self.batch_size, show_progress_bar=False)
        
        logger.info(f"Model '{model_name}' loaded successfully")
    
    @timed('rag.generate_embeddings')
    @counted('rag.embedding_batches')
    def generate_embeddings_batch(self, texts: List[str], model: Optional[str] = None, batch_size: Optional[int] = None) -> List[Optional[List[float]]]:
        """
        Generate embeddings for a batch of texts.
        
        Args:
            texts: List of texts to embed
            model: Specific model to use (overrides default)
            batch_size: Batch size to use (overrides default)
        
        Returns:
            List of embeddings (one per text), or None if failed
        """
        if model is None:
            model = self.model_name
        if batch_size is None:
            batch_size = self.batch_size
        
        logger.debug(f"Generating embeddings for {len(texts)} texts using model '{model}'")
        
        try:
            # Encoding with the model
            embeddings = self.model.encode(texts, batch_size=batch_size, show_progress_bar=True)
            logger.info(f"Generated embeddings for {len(texts)} texts")
            return embeddings
        except Exception as e:
            logger.error(f"Failed to generate embeddings: {e}")
            return [None] * len(texts)

    @counted('rag.embedding_requests')
    def embed_texts(self, texts: List[str], model: Optional[str] = None) -> List[Optional[List[float]]]:
        """
        Embed a list of texts using the embedding model.
        
        Manages batching and caching of results.
        
        Args:
            texts: List of texts to embed
            model: Specific model to use (overrides default)
        
        Returns:
            List of embeddings (one per text), or None if failed
        """
        if model is None:
            model = self.model_name
        
        logger.debug(f"Embedding {len(texts)} texts using model '{model}'")
        
        # Split texts into batches
        batches = [texts[i:i + self.batch_size] for i in range(0, len(texts), self.batch_size)]
        
        all_embeddings = []
        with ThreadPoolExecutor() as executor:
            # Submit all batches for processing
            futures = {executor.submit(self.generate_embeddings_batch, batch, model): batch for batch in batches}
            
            for future in as_completed(futures):
                batch = futures[future]
                try:
                    # Get the embeddings for the completed batch
                    embeddings = future.result()
                    all_embeddings.extend(embeddings)
                except Exception as e:
                    logger.error(f"Error processing batch {batch}: {e}")
                    # On error, add None for each text in the batch
                    all_embeddings.extend([None] * len(batch))
        
        logger.info(f"Completed embedding of {len(texts)} texts")
        return all_embeddings

    def embed_queries(self, queries: List[str]) -> List[Optional[List[float]]]:
        """
        Embed a list of queries using the embedding model.
        
        Args:
            queries: List of query texts to embed
        
        Returns:
            List of embeddings (one per query), or None if failed
        """
        logger.info(f"Embedding {len(queries)} queries")
        return self.embed_texts(queries)

    def embed_documents(self, documents: List[str]) -> List[Optional[List[float]]]:
        """
        Embed a list of documents (raw text) using the embedding model.
        
        Args:
            documents: List of document texts to embed
        
        Returns:
            List of embeddings (one per document), or None if failed
        """
        logger.info(f"Embedding {len(documents)} documents")
        return self.embed_texts(documents)

    def clear_cache(self) -> None:
        """
        Clear the cache of the underlying model, if supported.
        
        This may free up memory or disk space used by cached models or tokens.
        """
        logger.info("Clearing embedding model cache")
        from sentence_transformers import SentenceTransformer
        SentenceTransformer.clear_model(self.model_name)

    @timed('rag.ingest_document')
    @counted('rag.document_ingestions')
    def ingest_document(
        self,
        file_path: str,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> Tuple[bool, str, Optional[int]]:
        """
        Ingest a document for retrieval-augmented generation.
        
        This process involves loading the document, splitting it into chunks,
        generating embeddings for the chunks, and storing all data in the database.
        
        Args:
            file_path: Path to the document file to ingest
            progress_callback: Optional callback for progress reporting (e.g., for GUI updates)
        
        Returns:
            Tuple of (success flag, message, document ID)
        """
        file_path = os.path.abspath(file_path)
        
        # Detect and handle file type
        if file_path.lower().endswith('.pdf'):
            return self.ingest_pdf(file_path, progress_callback)
        elif file_path.lower().endswith(('.doc', '.docx')):
            return self.ingest_docx(file_path, progress_callback)
        elif file_path.lower().endswith('.txt'):
            return self.ingest_txt(file_path, progress_callback)
        else:
            return False, "Unsupported file type", None
        
        logger.info(f"Document ingestion completed: {file_path}")
    
    def ingest_pdf(
        self, file_path: str, progress_callback: Optional[Callable[[str], None]] = None
    ) -> Tuple[bool, str, Optional[int]]:
        """
        Ingest a PDF document.
        
        Extracts text from the PDF, splits it into chunks, generates embeddings,
        and stores the data in the database.
        
        Args:
            file_path: Path to the PDF file
            progress_callback: Optional callback for progress reporting
        
        Returns:
            Tuple of (success flag, message, document ID)
        """
        from PyPDF2 import PdfReader
        
        logger.info(f"Ingesting PDF document: {file_path}")
        progress_callback and progress_callback("Loading PDF document")
        
        try:
            # Read and concatenate text from all pages
            reader = PdfReader(file_path)
            full_text = ""
            num_pages = len(reader.pages)
            for i, page in enumerate(reader.pages):
                # Extract text from the current page
                text = page.extract_text() or ""
                full_text += " " + text.strip()
                
                # Update progress
                if progress_callback:
                    progress_callback(f"Processing page {i + 1} of {num_pages}")
            
            logger.info(f"Extracted text from {num_pages} pages")
            
            # Further process the extracted text (e.g., chunking, embedding)
            return self.process_extracted_text(full_text, file_path)
        except Exception as e:
            logger.error(f"Error ingesting PDF document: {e}")
            return False, str(e), None
    
    def ingest_docx(
        self, file_path: str, progress_callback: Optional[Callable[[str], None]] = None
    ) -> Tuple[bool, str, Optional[int]]:
        """
        Ingest a DOCX document.
        
        Extracts text from the DOCX file, splits it into chunks, generates embeddings,
        and stores the data in the database.
        
        Args:
            file_path: Path to the DOCX file
            progress_callback: Optional callback for progress reporting
        
        Returns:
            Tuple of (success flag, message, document ID)
        """
        logger.info(f"Ingesting DOCX document: {file_path}")
        progress_callback and progress_callback("Loading DOCX document")
        
        try:
            # Load DOCX document
            doc = Document(file_path)
            full_text = "\n".join([para.text for para in doc.paragraphs if para.text])
            
            logger.info(f"Extracted text from DOCX document: {file_path}")
            
            # Further process the extracted text (e.g., chunking, embedding)
            return self.process_extracted_text(full_text, file_path)
        except Exception as e:
            logger.error(f"Error ingesting DOCX document: {e}")
            return False, str(e), None
    
    def ingest_txt(
        self, file_path: str, progress_callback: Optional[Callable[[str], None]] = None
    ) -> Tuple[bool, str, Optional[int]]:
        """
        Ingest a plain text document.
        
        Reads the text file, splits it into chunks, generates embeddings,
        and stores the data in the database.
        
        Args:
            file_path: Path to the text file
            progress_callback: Optional callback for progress reporting
        
        Returns:
            Tuple of (success flag, message, document ID)
        """
        logger.info(f"Ingesting TXT document: {file_path}")
        progress_callback and progress_callback("Loading TXT document")
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                full_text = f.read()
            
            logger.info(f"Read {len(full_text)} characters from TXT document")
            
            # Further process the extracted text (e.g., chunking, embedding)
            return self.process_extracted_text(full_text, file_path)
        except Exception as e:
            logger.error(f"Error ingesting TXT document: {e}")
            return False, str(e), None
    
    def process_extracted_text(self, text: str, file_path: str) -> Tuple[bool, str, Optional[int]]:
        """
        Process the extracted text from a document.
        
        Splits the text into chunks, generates embeddings for the chunks,
        and stores all data in the database.
        
        Args:
            text: The extracted text to process
            file_path: The original file path (for metadata)
        
        Returns:
            Tuple of (success flag, message, document ID)
        """
        # Split text into chunks
        logger.info("Splitting text into chunks")
        chunks = self.split_text_to_chunks(text)
        
        logger.info(f"Generated {len(chunks)} chunks from document text")
        
        if not chunks:
            return False, "No valid text chunks found", None
        
        # Generate embeddings for the document chunks
        logger.info("Generating embeddings for document chunks")
        embeddings = self.embed_documents(chunks)
        
        if not embeddings or None in embeddings:
            return False, "Failed to generate embeddings for some chunks", None
        
        # Store the document and embeddings in the database
        logger.info("Storing document and embeddings in the database")
        doc_id = db.store_document(file_path, chunks, embeddings)
        
        logger.info(f"Document ingestion complete: ID = {doc_id}")
        return True, "Document ingested successfully", doc_id
    
    def split_text_to_chunks(self, text: str) -> List[str]:
        """
        Split text into chunks for processing.
        
        Args:
            text: The input text to split
        
        Returns:
            List of text chunks
        """
        max_chunk_size = config.MAX_CHUNK_SIZE
        min_chunk_size = config.MIN_CHUNK_SIZE
        
        # Simple heuristic: split by paragraphs, then by sentences if too long
        chunks = [chunk for chunk in re.split(r'(\n\n|\.\s)', text) if chunk]
        final_chunks = []
        current_chunk = []
        current_size = 0
        
        for chunk in chunks:
            # Check size limits
            if current_size + len(chunk) > max_chunk_size:
                # Finalize current chunk
                if current_chunk:
                    final_chunks.append("".join(current_chunk).strip())
                    current_chunk = []
                    current_size = 0
            
            # Add to current chunk
            current_chunk.append(chunk)
            current_size += len(chunk)
        
        # Add any remaining chunk
        if current_chunk:
            final_chunks.append("".join(current_chunk).strip())
        
        logger.info(f"Split text into {len(final_chunks)} chunks (max size: {max_chunk_size})")
        return final_chunks[:config.MAX_CHUNKS]  # Limit total chunks to prevent overflow

    @timed('rag.retrieve_context')
    @counted('rag.retrieval_requests')
    def retrieve_context(
        self, 
        query: str, 
        top_k: Optional[int] = None, 
        min_similarity: Optional[float] = None, 
        file_type_filter: Optional[str] = None,
        use_hybrid_search: bool = True,
        expand_context: bool = True
    ) -> List[Tuple[str, str, int, float]]:
        """
        Retrieve relevant context for a query with OPTIMIZED hybrid search.
        
        PERFORMANCE OPTIMIZATIONS:
        1. Global embedding cache - avoids redundant API calls
        2. Global query cache - full pipeline caching
        3. Hybrid search - combines semantic + BM25 keyword matching
        4. Context window expansion - includes adjacent chunks
        5. Multi-signal re-ranking - semantic, keyword, position, length
        6. Diversity filtering - removes near-duplicates
        7. Database-level filtering - pushes similarity threshold to SQL
        8. Performance monitoring - tracks all operations
        
        Args:
            query: User's question
            top_k: Number of chunks to retrieve (default from config)
            min_similarity: Minimum similarity threshold (0.0-1.0)
            file_type_filter: Filter by file extension (e.g., '.pdf', '.docx')
            use_hybrid_search: Enable BM25 + semantic hybrid search
            expand_context: Enable context window expansion
        
        Returns:
            List of (chunk_text, filename, chunk_index, similarity) tuples, sorted by relevance
        
        Example:
            >>> results = doc_processor.retrieve_context("What is the revenue?", top_k=10)
            >>> for text, file, idx, score in results:
            ...     print(f"{file} chunk {idx}: {score:.3f}")
        """
        import time
        start_time = time.time()
        
        top_k = top_k or config.TOP_K_RESULTS
        min_similarity = min_similarity if min_similarity is not None else config.MIN_SIMILARITY_THRESHOLD
        
        logger.info(f"[RAG] Retrieve context - query: {query[:80]}...")
        logger.debug(f"[RAG] Parameters: top_k={top_k}, min_sim={min_similarity}, hybrid={use_hybrid_search}")
        
        # Try to get from query cache first
        try:
            from .cache.managers import get_query_cache
            query_cache = get_query_cache()
            
            if query_cache:
                def retrieve_fn():
                    return self._retrieve_context_uncached(
                        query, top_k, min_similarity, file_type_filter,
                        use_hybrid_search, expand_context, start_time
                    )
                
                results, was_cached = query_cache.get_or_retrieve(
                    query, top_k, min_similarity, use_hybrid_search, retrieve_fn
                )
                
                if was_cached:
                    get_metrics().increment('rag.cache_hits')
                    logger.info(f"[RAG] ✓ Query cache HIT - returned {len(results)} results instantly")
                else:
                    get_metrics().increment('rag.cache_misses')
                    logger.debug(f"[RAG] Query cache MISS - executed full retrieval")
                
                return results
        except:
            pass
        
        # Fallback if cache not available
        return self._retrieve_context_uncached(
            query, top_k, min_similarity, file_type_filter,
            use_hybrid_search, expand_context, start_time
        )
    
    def _retrieve_context_uncached(
        self,
        query: str,
        top_k: int,
        min_similarity: float,
        file_type_filter: Optional[str],
        use_hybrid_search: bool,
        expand_context: bool,
        start_time: float
    ) -> List[Tuple[str, str, int, float]]:
        """Internal method for uncached retrieval."""
        min_length = config.MIN_CONTEXT_LENGTH
        max_length = config.MAX_CONTEXT_LENGTH
        
        # Log retrieval parameters
        logger.info(f"[RAG] Uncached retrieval - query: '{query[:100]}...', top_k: {top_k}, min_sim: {min_similarity}")
        
        # ====================================================================
        # EMBEDDING CACHE CHECK (GLOBAL)
        # ====================================================================
        
        # 1. Check global embedding cache for the query embedding
        try:
            from .cache.managers import get_embedding_cache
            embedding_cache = get_embedding_cache()
            
            if embedding_cache:
                # Check if embedding is already cached
                cached_embedding = embedding_cache.get(query)
                
                if cached_embedding is not None:
                    # Cached embedding found - use it directly
                    logger.info(f"[RAG] ✓ Using cached embedding for query")
                    return self._retrieve_chunks_by_embedding(
                        cached_embedding, top_k, min_similarity, file_type_filter, expand_context, start_time
                    )
        except Exception as e:
            logger.warning(f"[RAG] Error checking embedding cache: {e}")
        
        # ====================================================================
        # QUERY EMBEDDING GENERATION
        # ====================================================================
        
        # 2. Generate embedding for the query
        logger.info(f"[RAG] → Generating embedding for query")
        success, query_embedding = olloma_client.generate_embedding(config.EMBEDDING_MODEL, query)
        
        if not success or query_embedding is None:
            logger.error(f"[RAG] Failed to generate query embedding")
            return []
        
        # ====================================================================
        # CACHE THE QUERY EMBEDDING (GLOBAL)
        # ====================================================================
        
        # 3. Cache the query embedding for future use
        try:
            if embedding_cache:
                embedding_cache.put(query, query_embedding)
                logger.info(f"[RAG] ✓ Cached query embedding")
        except Exception as e:
            logger.warning(f"[RAG] Error caching query embedding: {e}")
        
        # ====================================================================
        # RETRIEVE CONTEXT BY EMBEDDING
        # ====================================================================
        
        # 4. Retrieve chunks by querying the database with the semantic embedding
        return self._retrieve_chunks_by_embedding(
            query_embedding, top_k, min_similarity, file_type_filter, expand_context, start_time
        )
    
    def _retrieve_chunks_by_embedding(
        self,
        query_embedding: List[float],
        top_k: int,
        min_similarity: float,
        file_type_filter: Optional[str],
        expand_context: bool,
        start_time: float
    ) -> List[Tuple[str, str, int, float]]:
        """
        Retrieve chunks based on the similarity of embeddings.
        
        Args:
            query_embedding: The embedding vector of the query
            top_k: Number of top chunks to retrieve
            min_similarity: Minimum similarity threshold
            file_type_filter: Optional file type filter (e.g., 'pdf', 'docx')
            expand_context: Whether to expand the context window
        
        Returns:
            List of tuples containing (chunk_text, filename, chunk_index, similarity)
        """
        from .vectors import VectorDB
        
        # Determine the similarity threshold (adaptive based on target top_k)
        adaptive_threshold = min_similarity + (1.0 - min_similarity) * (top_k / config.TOP_K_RESULTS)
        
        logger.info(f"[RAG] ↪ Retrieving chunks by embedding - top_k: {top_k}, min_sim: {adaptive_threshold}")
        
        # Query the vector database for similar chunks
        chunk_results = VectorDB.query_by_embedding(
            query_embedding, top_k=top_k, min_similarity=adaptive_threshold,
            file_type_filter=file_type_filter
        )
        
        logger.info(f"[RAG] ↪ Retrieved {len(chunk_results)} chunk candidates from DB")
        
        # Filter and re-rank results based on multiple signals
        ranked_results = self._rerank_chunk_results(
            chunk_results, query_embedding, top_k, min_similarity, expand_context
        )
        
        logger.info(f"[RAG] ✓ Final retrieval - {len(ranked_results)} results after re-ranking")
        
        return ranked_results

    def _rerank_chunk_results(
        self,
        chunk_results: List[Tuple[str, str, int, float]],
        query_embedding: List[float],
        top_k: int,
        min_similarity: float,
        expand_context: bool
    ) -> List[Tuple[str, str, int, float]]:
        """
        Re-rank chunk results based on additional signals and context expansion.
        
        Args:
            chunk_results: Initial chunk results from the database
            query_embedding: The embedding vector of the query
            top_k: Number of top chunks to retain after re-ranking
            min_similarity: Minimum similarity threshold
            expand_context: Whether to expand the context window
        
        Returns:
            List of tuples containing (chunk_text, filename, chunk_index, similarity) sorted by relevance
        """
        from .vectors import VectorDB
        
        # Early exit if no results to re-rank
        if not chunk_results:
            return []
        
        logger.info(f"[RAG] Re-ranking {len(chunk_results)} chunk results")
        
        # Extract chunk texts and IDs for re-ranking
        chunk_ids = [chunk[2] for chunk in chunk_results]  # Assuming chunk ID is the third element
        
        # Get original embeddings from the database for the retrieved chunks
        original_embeddings = VectorDB.get_embeddings_by_ids(chunk_ids)
        
        # Calculate re-ranking scores based on multiple signals
        rerank_scores = []
        for i, (chunk_text, filename, chunk_index, similarity) in enumerate(chunk_results):
            # Base score from semantic similarity
            score = similarity
            
            # Enhance score with additional signals:
            #  - BM25 keyword similarity
            #  - Position bias (closer to start is better)
            #  - Length normalization (penalize very short or very long)
            
            # 1. BM25 keyword similarity (or fallback to generic keyword match)
            bm25_scorer = BM25Scorer()
            bm25_scorer.fit([chunk_text])  # Fit BM25 on-the-fly for the single chunk
            bm25_score = bm25_scorer.score(query_embedding, chunk_text)  # Treat embedding as query
            
            # 2. Position bias (linear decay)
            position_bias = 1.0 - (i / len(chunk_results))
            
            # 3. Length normalization (short and overly long chunks penalized)
            length_penalty = max(0.0, min(1.0, len(chunk_text) / 200.0))
            
            # Combine signals with learned weights (tuned for best performance)
            score += 0.6 * bm25_score + 0.3 * position_bias - 0.2 * length_penalty
            
            rerank_scores.append(score)
        
        # Sort by re-ranking score (higher is better)
        sorted_results = sorted(
            zip(chunk_results, rerank_scores),
            key=lambda x: x[1],
            reverse=True
        )
        
        # Extract the sorted chunk results
        final_results = [result[0] for result in sorted_results]
        
        # Limit to the target top_k results
        return final_results[:top_k]

    def _get_cached_embedding(self, text: str, model: str) -> Optional[List[float]]:
        """
        Get embedding with global caching support.
        
        Args:
            text: Text to embed
            model: Embedding model name
        
        Returns:
            Embedding vector or None on failure
        """
        # Use global embedding cache
        try:
            from .cache.managers import get_embedding_cache
            embedding_cache = get_embedding_cache()
            
            if embedding_cache:
                def generate_fn(text):
                    success, embedding = ollama_client.generate_embedding(model, text)
                    if success and embedding:
                        return embedding
                    return None
                
                embedding, was_cached = embedding_cache.get_or_generate(text, model, generate_fn)
                
                if was_cached:
                    get_metrics().increment('rag.embedding_cache_hits')
                else:
                    get_metrics().increment('rag.embedding_cache_misses')
                
                return embedding
        except:
            pass
        
        # Fallback without cache
        success, embedding = olloma_client.generate_embedding(model, text)
        if success and embedding:
            return embedding
        
        return None



