"""
RAG (Retrieval-Augmented Generation) Module
===========================================

Handles document ingestion, chunking, embedding generation, and context retrieval
for the LocalChat RAG application.

Classes:
    DocumentProcessor: Main RAG processing engine

Example:
    >>> from rag import doc_processor
    >>> success, msg, doc_id = doc_processor.ingest_document("file.pdf")
    >>> context = doc_processor.retrieve_context("What is this about?")

Author: LocalChat Team
Last Updated: 2024-12-27
"""

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Tuple, Optional, Callable, Any, Dict, Union
from . import config
from .db import db
from .ollama_client import ollama_client
from .utils.logging_config import get_logger

# Setup logger
logger = get_logger(__name__)

# Document loaders
try:
    import PyPDF2
    PDF_AVAILABLE = True
    logger.debug("PyPDF2 available for PDF processing")
except ImportError:
    PDF_AVAILABLE = False
    logger.warning("PyPDF2 not available - PDF support disabled")

try:
    from docx import Document
    DOCX_AVAILABLE = True
    logger.debug("python-docx available for DOCX processing")
except ImportError:
    DOCX_AVAILABLE = False
    logger.warning("python-docx not available - DOCX support disabled")


class DocumentProcessor:
    """
    Handles document loading, chunking, and embedding.
    
    Main RAG processing engine that coordinates document ingestion,
    text chunking with hierarchical splitting, embedding generation,
    and context retrieval for question-answering.
    
    Attributes:
        embedding_model (Optional[str]): Name of embedding model to use
    
    Example:
        >>> processor = DocumentProcessor()
        >>> success, msg, doc_id = processor.ingest_document("doc.pdf")
        >>> if success:
        ...     results = processor.retrieve_context("query")
    """
    
    def __init__(self) -> None:
        """Initialize document processor."""
        self.embedding_model: Optional[str] = None
        logger.info("DocumentProcessor initialized")
    
    def load_text_file(self, file_path: str) -> Tuple[bool, str]:
        """
        Load a text file.
        
        Args:
            file_path: Path to text file
        
        Returns:
            Tuple of (success: bool, content_or_error: str)
        """
        try:
            logger.debug(f"Loading text file: {file_path}")
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            logger.debug(f"Loaded {len(content)} characters from text file")
            return True, content
        except Exception as e:
            logger.error(f"Error loading text file: {e}", exc_info=True)
            return False, str(e)
    
    def load_pdf_file(self, file_path: str) -> Tuple[bool, str]:
        """
        Load a PDF file with enhanced table extraction.
        
        Uses pdfplumber for better table extraction if available,
        falls back to PyPDF2 for basic text extraction.
        
        Args:
            file_path: Path to PDF file
        
        Returns:
            Tuple of (success: bool, content_or_error: str)
        """
        if not PDF_AVAILABLE:
            logger.error("PyPDF2 not installed")
            return False, "PyPDF2 not installed"
        
        try:
            logger.debug(f"Loading PDF file: {file_path}")
            
            # Try to use pdfplumber for better table extraction
            try:
                import pdfplumber
                PDFPLUMBER_AVAILABLE = True
                logger.debug("pdfplumber available - using enhanced table extraction")
            except ImportError:
                PDFPLUMBER_AVAILABLE = False
                logger.debug("pdfplumber not available - using basic PyPDF2 extraction")
            
            text = ""
            
            if PDFPLUMBER_AVAILABLE:
                # Enhanced extraction with pdfplumber (handles tables better)
                try:
                    with pdfplumber.open(file_path) as pdf:
                        num_pages = len(pdf.pages)
                        logger.debug(f"PDF has {num_pages} pages (using pdfplumber)")
                        
                        for page_num, page in enumerate(pdf.pages):
                            # Extract regular text
                            page_text = page.extract_text()
                            if page_text:
                                text += page_text + "\n"
                            
                            # Extract tables
                            tables = page.extract_tables()
                            if tables:
                                logger.debug(f"Page {page_num + 1}: Found {len(tables)} table(s)")
                                for table_idx, table in enumerate(tables):
                                    text += f"\n[Table {table_idx + 1} on page {page_num + 1}]\n"
                                    # Convert table to text format
                                    for row in table:
                                        # Filter out None values and join cells
                                        row_text = " | ".join([str(cell) if cell else "" for cell in row])
                                        text += row_text + "\n"
                                    text += "\n"
                    
                    logger.debug(f"Extracted {len(text)} characters from PDF (with tables)")
                    return True, text
                
                except Exception as plumber_error:
                    logger.warning(f"pdfplumber extraction failed: {plumber_error}, falling back to PyPDF2")
                    # Fall through to PyPDF2 method
            
            # Fallback to PyPDF2 (basic extraction)
            text = ""
            with open(file_path, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                num_pages = len(pdf_reader.pages)
                logger.debug(f"PDF has {num_pages} pages (using PyPDF2)")
                
                for page_num, page in enumerate(pdf_reader.pages):
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
            
            if not text.strip():
                logger.warning("PDF extraction resulted in empty text - file may be image-based or encrypted")
                return False, "PDF contains no extractable text. It may be image-based (scanned) or password-protected."
            
            logger.debug(f"Extracted {len(text)} characters from PDF")
            return True, text
            
        except Exception as e:
            logger.error(f"Error loading PDF: {e}", exc_info=True)
            return False, str(e)
    
    def load_docx_file(self, file_path: str) -> Tuple[bool, str]:
        """
        Load a DOCX file with enhanced error handling.
        
        Extracts text from both paragraphs and tables in the document.
        
        Args:
            file_path: Path to DOCX file
        
        Returns:
            Tuple of (success: bool, content_or_error: str)
        """
        if not DOCX_AVAILABLE:
            logger.error("python-docx not installed")
            return False, "python-docx not installed"
        
        try:
            logger.debug(f"Loading DOCX file: {file_path}")
            
            # Check if file exists
            if not os.path.exists(file_path):
                error_msg = f"File not found: {file_path}"
                logger.error(error_msg)
                return False, error_msg
            
            # Check file size
            file_size = os.path.getsize(file_path)
            logger.debug(f"DOCX file size: {file_size} bytes")
            
            if file_size == 0:
                logger.error("File is empty (0 bytes)")
                return False, "File is empty (0 bytes)"
            
            # Try to open the document
            try:
                doc = Document(file_path)
            except Exception as doc_error:
                error_msg = f"Failed to open DOCX file: {str(doc_error)}"
                logger.error(error_msg, exc_info=True)
                return False, f"{error_msg}. File might be corrupted or password-protected."
            
            # Extract text from paragraphs
            paragraphs = []
            for para in doc.paragraphs:
                text = para.text.strip()
                if text:  # Only include non-empty paragraphs
                    paragraphs.append(text)
            
            # Also extract text from tables
            tables_text = []
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        text = cell.text.strip()
                        if text:
                            tables_text.append(text)
            
            # Combine all text
            all_text = paragraphs + tables_text
            text = "\n".join(all_text)
            
            logger.debug(f"Extracted {len(paragraphs)} paragraphs and {len(tables_text)} table cells")
            logger.debug(f"Total text length: {len(text)} characters")
            
            if not text or len(text.strip()) < 10:
                error_msg = f"Document appears to be empty or has very little text (only {len(text)} characters)"
                logger.warning(error_msg)
                return False, f"{error_msg}. Check if document has actual content."
            
            return True, text
            
        except Exception as e:
            logger.error(f"Error loading DOCX: {e}", exc_info=True)
            return False, f"Error loading DOCX: {str(e)}"
    
    def load_document(self, file_path: str) -> Tuple[bool, str]:
        """
        Load a document based on its extension.
        
        Args:
            file_path: Path to document file
        
        Returns:
            Tuple of (success: bool, content_or_error: str)
        
        Example:
            >>> success, content = processor.load_document("doc.pdf")
            >>> if success:
            ...     print(f"Loaded {len(content)} characters")
        """
        ext = Path(file_path).suffix.lower()
        logger.debug(f"Loading document with extension: {ext}")
        
        if ext == '.txt' or ext == '.md':
            return self.load_text_file(file_path)
        elif ext == '.pdf':
            return self.load_pdf_file(file_path)
        elif ext == '.docx':
            return self.load_docx_file(file_path)
        else:
            error_msg = f"Unsupported file type: {ext}"
            logger.error(error_msg)
            return False, error_msg
    
    def chunk_text(self, text: str, chunk_size: Optional[int] = None, overlap: Optional[int] = None) -> List[str]:
        """
        Chunk text using recursive character splitting for better semantic preservation.
        
        ENHANCED: Keeps tables together as single chunks when possible.
        
        Tries to split at natural boundaries in this order:
        1. Table boundaries ([Table X] markers)
        2. Paragraph breaks (\n\n)
        3. Line breaks (\n)
        4. Sentence endings (. )
        5. Word boundaries ( )
        6. Character level (last resort)
        
        Args:
            text: The input text to chunk
            chunk_size: Maximum size of each chunk (in characters)
            overlap: Overlap between chunks (in characters)
        
        Returns:
            List of text chunks
        """
        chunk_size = chunk_size or config.CHUNK_SIZE
        overlap = overlap or config.CHUNK_OVERLAP
        
        # Clean text
        text = text.strip()
        
        if len(text) <= chunk_size:
            return [text] if text else []
        
        # STEP 1: Extract and protect tables
        # Tables should be kept together as much as possible
        table_pattern = r'\[Table \d+ on page \d+\].*?(?=\[Table \d+ on page \d+\]|\Z)'
        import re
        
        chunks = []
        table_matches = list(re.finditer(table_pattern, text, re.DOTALL))
        
        if table_matches:
            logger.debug(f"Found {len(table_matches)} table(s) in text - will try to keep them intact")
            
            # Process text with tables
            current_pos = 0
            
            for match in table_matches:
                table_start = match.start()
                table_end = match.end()
                table_text = match.group(0).strip()
                
                # Process text BEFORE this table
                if table_start > current_pos:
                    before_text = text[current_pos:table_start].strip()
                    if before_text:
                        # Chunk the non-table text normally
                        before_chunks = self._chunk_text_standard(before_text, chunk_size, overlap)
                        chunks.extend(before_chunks)
                
                # Handle the TABLE itself
                if len(table_text) <= chunk_size:
                    # Table fits in one chunk - keep it intact!
                    chunks.append(table_text)
                    logger.debug(f"Table kept intact ({len(table_text)} chars)")
                else:
                    # Table is too large - split carefully by rows
                    table_lines = table_text.split('\n')
                    table_header = table_lines[0] if table_lines else ""  # [Table X on page Y]
                    
                    current_table_chunk = [table_header]
                    current_table_size = len(table_header)
                    
                    for line in table_lines[1:]:
                        line_size = len(line) + 1  # +1 for newline
                        
                        if current_table_size + line_size > chunk_size and current_table_chunk:
                            # Save current chunk
                            chunks.append('\n'.join(current_table_chunk))
                            # Start new chunk with header
                            current_table_chunk = [table_header, line]
                            current_table_size = len(table_header) + line_size
                        else:
                            current_table_chunk.append(line)
                            current_table_size += line_size
                    
                    if current_table_chunk:
                        chunks.append('\n'.join(current_table_chunk))
                    
                    logger.debug(f"Large table split into {len([c for c in chunks if table_header in c])} chunks")
                
                current_pos = table_end
            
            # Process text AFTER last table
            if current_pos < len(text):
                after_text = text[current_pos:].strip()
                if after_text:
                    after_chunks = self._chunk_text_standard(after_text, chunk_size, overlap)
                    chunks.extend(after_chunks)
        else:
            # No tables - use standard chunking
            chunks = self._chunk_text_standard(text, chunk_size, overlap)
        
        # Final validation
        valid_chunks = []
        for chunk in chunks:
            chunk = chunk.strip()
            # Only keep chunks with meaningful content (at least 10 characters)
            if len(chunk) >= 10:
                valid_chunks.append(chunk)
        
        logger.debug(f"Chunked text into {len(valid_chunks)} valid chunks")
        return valid_chunks
    
    def _chunk_text_standard(self, text: str, chunk_size: int, overlap: int) -> List[str]:
        """
        Standard text chunking without table protection.
        
        Args:
            text: Text to chunk
            chunk_size: Maximum chunk size
            overlap: Overlap between chunks
        
        Returns:
            List of chunks
        """
        separators = config.CHUNK_SEPARATORS
        
        # Recursive splitting function
        def split_text_recursive(text, separators, chunk_size, overlap):
            """Recursively split text using hierarchical separators."""
            if not text:
                return []
            
            if len(text) <= chunk_size:
                return [text]
            
            # Try each separator in order
            for separator in separators:
                if separator == '':
                    # Character-level split as last resort
                    return character_split(text, chunk_size, overlap)
                
                if separator in text:
                    # Split by this separator
                    splits = text.split(separator)
                    
                    # Reconstruct with separator and chunk
                    chunks = []
                    current_chunk = []
                    current_size = 0
                    
                    for i, split in enumerate(splits):
                        split_with_sep = split + separator if i < len(splits) - 1 else split
                        split_size = len(split_with_sep)
                        
                        # If single split is too large, recursively split it
                        if split_size > chunk_size:
                            # Save current chunk if exists
                            if current_chunk:
                                chunks.append(''.join(current_chunk).strip())
                                current_chunk = []
                                current_size = 0
                            
                            # Recursively split the large piece
                            remaining_separators = separators[separators.index(separator) + 1:]
                            sub_chunks = split_text_recursive(
                                split_with_sep, 
                                remaining_separators, 
                                chunk_size, 
                                overlap
                            )
                            chunks.extend(sub_chunks)
                        
                        # Check if adding this split exceeds chunk size
                        elif current_size + split_size > chunk_size:
                            # Save current chunk
                            if current_chunk:
                                chunks.append(''.join(current_chunk).strip())
                            
                            # Start new chunk with overlap
                            if overlap > 0 and current_chunk:
                                # Take last part of previous chunk for overlap
                                overlap_text = ''.join(current_chunk)[-overlap:]
                                current_chunk = [overlap_text, split_with_sep]
                                current_size = len(overlap_text) + split_size
                            else:
                                current_chunk = [split_with_sep]
                                current_size = split_size
                        else:
                            # Add to current chunk
                            current_chunk.append(split_with_sep)
                            current_size += split_size
                    
                    # Add remaining chunk
                    if current_chunk:
                        chunks.append(''.join(current_chunk).strip())
                    
                    # Filter out empty chunks
                    return [c for c in chunks if c.strip()]
            
            # Fallback if no separator found
            return character_split(text, chunk_size, overlap)
        
        def character_split(text, chunk_size, overlap):
            """Split text at character level with overlap."""
            chunks = []
            start = 0
            
            while start < len(text):
                end = start + chunk_size
                chunk = text[start:end]
                
                if chunk.strip():
                    chunks.append(chunk.strip())
                
                start = end - overlap
                if start <= 0:
                    break
            
            return chunks
        
        # Perform recursive splitting
        return split_text_recursive(text, separators, chunk_size, overlap)
    
    def generate_embeddings_batch(self, texts: List[str], model: Optional[str] = None) -> List[Optional[List[float]]]:
        """Generate embeddings for a batch of texts."""
        if model is None:
            model = self.embedding_model or ollama_client.get_embedding_model()
        
        embeddings = []
        for text in texts:
            success, embedding = ollama_client.generate_embedding(model, text)
            if success:
                embeddings.append(embedding)
            else:
                embeddings.append(None)
        
        logger.info(f"Generated embeddings for {len(texts)} texts using model {model}")
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
    
    def ingest_document(
        self,
        file_path: str,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> Tuple[bool, str, Optional[int]]:
        """
        Ingest a single document with parallel chunk processing.
        
        Checks if document already exists before processing. If it exists,
        returns existing document info instead of re-ingesting.
        
        Loads document, chunks text, generates embeddings in parallel,
        and stores in database.
        
        Args:
            file_path: Path to document file
            progress_callback: Optional callback for progress updates
        
        Returns:
            Tuple of (success: bool, message: str, doc_id: Optional[int])
        
        Example:
            >>> def progress(msg):
            ...     print(f"Progress: {msg}")
            >>> success, msg, doc_id = processor.ingest_document(
            ...     "file.pdf",
            ...     progress_callback=progress
            ... )
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
            
            # Chunk document
            if progress_callback:
                progress_callback(f"Chunking {filename}...")
            
            logger.debug("Chunking document...")
            chunks = self.chunk_text(content)
            
            if not chunks:
                error_msg = f"No chunks generated from {filename}"
                logger.error(error_msg)
                return False, error_msg, None
            
            logger.info(f"Generated {len(chunks)} chunks")
            
            # Insert document record
            logger.debug("Inserting document record...")
            doc_id = db.insert_document(
                filename=filename,
                content=content[:1000],  # Store first 1000 chars as preview
                metadata={'total_chunks': len(chunks), 'file_path': file_path}
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
                progress_callback(f"Generating embeddings for {len(chunks)} chunks...")
            
            # Process chunks in parallel
            chunks_data = []
            failed_chunks = 0
            
            with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as executor:
                futures = {
                    executor.submit(
                        self.process_document_chunk,
                        doc_id,
                        chunk,
                        idx,
                        embedding_model
                    ): idx for idx, chunk in enumerate(chunks)
                }
                
                for future in as_completed(futures):
                    result = future.result()
                    if result:
                        chunks_data.append(result)
                    else:
                        failed_chunks += 1
                    
                    if progress_callback:
                        progress = len(chunks_data) / len(chunks) * 100
                        progress_callback(f"Processing {filename}: {progress:.1f}% ({len(chunks_data)}/{len(chunks)} chunks)")
            
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
        
        Example:
            >>> files = ["doc1.pdf", "doc2.txt"]
            >>> results = processor.ingest_multiple_documents(files)
            >>> for success, msg, doc_id in results:
            ...     print(f"{msg}")
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
    
    def retrieve_context(self, query: str, top_k: Optional[int] = None, min_similarity: Optional[float] = None, file_type_filter: Optional[str] = None) -> List[Tuple[str, str, int, float]]:
        """
        Retrieve relevant context for a query with enhanced filtering and re-ranking.
        
        Args:
            query: User's question
            top_k: Number of chunks to retrieve (default from config)
            min_similarity: Minimum similarity threshold (0.0-1.0)
            file_type_filter: Filter by file extension (e.g., '.pdf', '.docx')
        
        Returns:
            List of (chunk_text, filename, chunk_index, similarity) tuples
        """
        top_k = top_k or config.TOP_K_RESULTS
        min_similarity = min_similarity if min_similarity is not None else config.MIN_SIMILARITY_THRESHOLD
        
        logger.info(f"Retrieve context called with query: {query[:50]}...")
        logger.debug(f"top_k: {top_k}, min_similarity: {min_similarity}")
        if file_type_filter:
            logger.debug(f"file_type_filter: {file_type_filter}")
        
        # Preprocess query
        query_clean = ' '.join(query.split())  # Remove extra whitespace
        logger.debug(f"Preprocessed query: {query_clean[:50]}...")
        
        # Get embedding model
        embedding_model = ollama_client.get_embedding_model()
        if not embedding_model:
            logger.error("No embedding model available")
            return []
        
        logger.info(f"Using embedding model: {embedding_model}")
        
        # Generate query embedding
        success, query_embedding = ollama_client.generate_embedding(embedding_model, query_clean)
        if not success:
            logger.error("Failed to generate query embedding")
            return []
        
        logger.info(f"Generated query embedding: dimension {len(query_embedding)}")
        
        # Search for similar chunks (get more for better filtering/re-ranking)
        search_k = top_k * 3 if min_similarity > 0 else top_k * 2
        results = db.search_similar_chunks(query_embedding, search_k, file_type_filter=file_type_filter)
        logger.info(f"Database search returned {len(results)} results")
        
        # Filter by similarity threshold
        filtered_results = []
        for chunk_text, filename, chunk_index, similarity in results:
            if similarity >= min_similarity:
                filtered_results.append((chunk_text, filename, chunk_index, similarity))
                logger.debug(f"? {filename} chunk {chunk_index}: similarity {similarity:.3f}")
            else:
                logger.debug(f"? {filename} chunk {chunk_index}: similarity {similarity:.3f} (below threshold)")
        
        if not filtered_results:
            logger.warning(f"No chunks passed similarity threshold {min_similarity}")
            return []
        
        logger.info(f"{len(filtered_results)} chunks passed similarity filter")
        
        # Enhanced re-ranking with multiple signals
        if config.RERANK_RESULTS and len(filtered_results) > 1:
            logger.info(f"Applying enhanced re-ranking...")
            filtered_results = self._rerank_with_multiple_signals(query_clean, filtered_results)
            logger.info(f"Results re-ranked by relevance")
        
        # Limit to final top_k
        final_top_k = getattr(config, 'RERANK_TOP_K', top_k)
        filtered_results = filtered_results[:final_top_k]
        
        logger.info(f"Returning {len(filtered_results)} chunks")
        return filtered_results
    
    def _rerank_with_multiple_signals(self, query: str, results: List[Tuple[str, str, int, float]]) -> List[Tuple[str, str, int, float]]:
        """
        Advanced re-ranking using multiple relevance signals.
        
        Args:
            query: Original query
            results: List of (chunk_text, filename, chunk_index, similarity)
        
        Returns:
            Re-ranked results
        """
        if not results:
            return results
        
        query_lower = query.lower()
        query_terms = set(query_lower.split())
        
        scored_results = []
        
        for chunk_text, filename, chunk_index, similarity in results:
            chunk_lower = chunk_text.lower()
            chunk_terms = set(chunk_lower.split())
            
            # 1. Vector similarity (from database) - PRIMARY SIGNAL
            sim_score = similarity
            
            # 2. Keyword matching - EXACT MATCHES
            if query_terms:
                exact_matches = len(query_terms & chunk_terms)
                keyword_score = exact_matches / len(query_terms)
            else:
                keyword_score = 0
            
            # 3. BM25-style scoring - TERM FREQUENCY
            bm25_score = self._compute_simple_bm25(query_lower, chunk_lower)
            
            # 4. Position score - FAVOR EARLY CHUNKS (often summaries)
            position_score = 1.0 / (1.0 + chunk_index * 0.05)
            
            # 5. Length score - PREFER SUBSTANTIAL CHUNKS
            length_score = min(len(chunk_text) / 1000.0, 1.0)
            
            # Combined weighted score
            final_score = (
                config.SIMILARITY_WEIGHT * sim_score +
                config.KEYWORD_WEIGHT * keyword_score +
                config.BM25_WEIGHT * bm25_score +
                config.POSITION_WEIGHT * position_score +
                0.05 * length_score
            )
            
            logger.debug(f"Chunk {chunk_index}: sim={sim_score:.3f}, kw={keyword_score:.3f}, bm25={bm25_score:.3f}, pos={position_score:.3f}, final={final_score:.3f}")
            
            scored_results.append((chunk_text, filename, chunk_index, similarity, final_score))
        
        # Sort by final score
        scored_results.sort(key=lambda x: x[4], reverse=True)
        
        # Return original format (without final_score)
        return [(text, fname, idx, sim) for text, fname, idx, sim, _ in scored_results]
    
    def _compute_simple_bm25(self, query: str, document: str, k1: float = 1.5, b: float = 0.75) -> float:
        """
        Compute simplified BM25 relevance score.
        
        Args:
            query: Search query (lowercase)
            document: Document text (lowercase)
            k1: Term frequency saturation parameter
            b: Length normalization parameter
        
        Returns:
            BM25 score (normalized to 0-1 range)
        """
        from collections import Counter
        
        query_terms = query.split()
        doc_terms = document.split()
        doc_length = len(doc_terms)
        
        if doc_length == 0:
            return 0.0
        
        # Term frequencies in document
        doc_term_freqs = Counter(doc_terms)
        
        # Average document length (approximate)
        avg_doc_length = 500  # Approximate average
        
        score = 0.0
        for term in query_terms:
            if term in doc_term_freqs:
                tf = doc_term_freqs[term]
                # Simplified BM25 formula (without IDF component)
                numerator = tf * (k1 + 1)
                denominator = tf + k1 * (1 - b + b * (doc_length / avg_doc_length))
                score += numerator / denominator
        
        # Normalize score to 0-1 range (approximate)
        normalized_score = min(score / 10.0, 1.0)
        return normalized_score
    
    def test_retrieval(self, query: str) -> Tuple[bool, Union[str, List[Dict[str, Any]]]]:
        """
        Test retrieval with a sample query.
        
        Args:
            query: Test query string
        
        Returns:
            Tuple of (success: bool, results_or_error: Union[str, List[Dict]])
        
        Example:
            >>> success, results = processor.test_retrieval("What is this about?")
            >>> if success:
            ...     for result in results:
            ...         print(result['filename'])
        """
        logger.info(f"Testing retrieval with query: {query[:50]}...")
        results = self.retrieve_context(query)
        
        if not results:
            logger.warning("No results found for test query")
            return False, "No results found. Make sure documents are ingested."
        
        # Format results
        formatted_results = []
        for chunk_text, filename, chunk_index, similarity in results:
            formatted_results.append({
                'text': chunk_text[:200] + '...' if len(chunk_text) > 200 else chunk_text,
                'filename': filename,
                'chunk_index': chunk_index,
                'similarity': float(similarity)
            })
        
        logger.info(f"Test retrieval returned {len(formatted_results)} results")
        return True, formatted_results


# ============================================================================
# GLOBAL INSTANCE
# ============================================================================

# Global document processor instance
doc_processor = DocumentProcessor()

logger.info("RAG module loaded")


