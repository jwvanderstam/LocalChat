"""
Text Chunking
=============

Handles text chunking with recursive character splitting, table preservation,
and metadata tracking for enhanced citations.
"""

import re
from typing import List, Optional, Dict, Any

from .. import config
from ..utils.logging_config import get_logger

logger = get_logger(__name__)

# Try to import monitoring - graceful degradation if not available
try:
    from ..monitoring import timed
except ImportError:
    def timed(metric_name): 
        return lambda func: func


class TextChunkerMixin:
    """
    Mixin providing text chunking methods for DocumentProcessor.
    
    Supports recursive character splitting with table preservation
    and metadata tracking for enhanced citations.
    """
    
    def _split_large_table(
        self, table_text: str, table_header: str, max_size: int
    ) -> List[str]:
        """Split an oversized table into row-bounded chunks."""
        table_lines = table_text.split('\n')
        chunks: List[str] = []
        current: List[str] = [table_header]
        current_size = len(table_header)
        for line in table_lines[1:]:
            line_size = len(line) + 1
            if current_size + line_size > max_size and current:
                chunks.append('\n'.join(current))
                current = [table_header, line]
                current_size = len(table_header) + line_size
            else:
                current.append(line)
                current_size += line_size
        if current:
            chunks.append('\n'.join(current))
        return chunks

    @timed('rag.chunk_text')
    def chunk_text(
        self, text: str, chunk_size: Optional[int] = None, overlap: Optional[int] = None
    ) -> List[str]:
        """
        Chunk text using recursive character splitting for better semantic preservation.

        ENHANCED: Keeps tables together as single chunks when possible, using larger
        TABLE_CHUNK_SIZE for tables to maximize context retention.
        
        Args:
            text: The input text to chunk
            chunk_size: Maximum size of each chunk (in characters)
            overlap: Overlap between chunks (in characters)
        
        Returns:
            List of text chunks
        """
        chunk_size = chunk_size or config.CHUNK_SIZE
        overlap = overlap or config.CHUNK_OVERLAP
        table_chunk_size = getattr(config, 'TABLE_CHUNK_SIZE', chunk_size * 2)
        keep_tables_intact = getattr(config, 'KEEP_TABLES_INTACT', True)
        
        # Clean text
        text = text.strip()
        
        if len(text) <= chunk_size:
            return [text] if text else []
        
        # STEP 1: Extract and protect tables
        table_pattern = r'\[Table \d+ on page \d+\].*?(?=\[Table \d+ on page \d+\]|\Z)'
        
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
                        before_chunks = self._chunk_text_standard(before_text, chunk_size, overlap)
                        chunks.extend(before_chunks)
                
                # Handle the TABLE itself with larger chunk size
                max_table_chunk = table_chunk_size if keep_tables_intact else chunk_size
                fits_intact = len(table_text) <= max_table_chunk
                if fits_intact:
                    chunks.append(table_text)
                    logger.debug(f"Table kept intact ({len(table_text)} chars)")
                else:
                    table_header = table_text.split('\n')[0]
                    split_chunks = self._split_large_table(table_text, table_header, max_table_chunk)
                    chunks.extend(split_chunks)
                    logger.debug(f"Large table split into {len(split_chunks)} chunks (max size={max_table_chunk})")
                
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
            if len(chunk) >= 10:
                valid_chunks.append(chunk)
        
        logger.info(f"Chunked text into {len(valid_chunks)} valid chunks (standard_size={chunk_size}, table_size={table_chunk_size})")
        return valid_chunks
    
    def _character_split(self, text: str, chunk_size: int, overlap: int) -> List[str]:
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

    def _split_text_recursive(
        self, text: str, separators: List[str], chunk_size: int, overlap: int
    ) -> List[str]:
        """Recursively split text using hierarchical separators."""
        if not text:
            return []
        if len(text) <= chunk_size:
            return [text]

        for separator in separators:
            if separator == '':
                return self._character_split(text, chunk_size, overlap)
            if separator not in text:
                continue

            splits = text.split(separator)
            chunks: List[str] = []
            current_chunk: List[str] = []
            current_size = 0

            for i, split in enumerate(splits):
                split_with_sep = split + separator if i < len(splits) - 1 else split
                split_size = len(split_with_sep)

                if split_size > chunk_size:
                    if current_chunk:
                        chunks.append(''.join(current_chunk).strip())
                        current_chunk = []
                        current_size = 0
                    remaining = separators[separators.index(separator) + 1:]
                    chunks.extend(self._split_text_recursive(split_with_sep, remaining, chunk_size, overlap))
                elif current_size + split_size > chunk_size:
                    if current_chunk:
                        chunks.append(''.join(current_chunk).strip())
                    if overlap > 0 and current_chunk:
                        overlap_text = ''.join(current_chunk)[-overlap:]
                        current_chunk = [overlap_text, split_with_sep]
                        current_size = len(overlap_text) + split_size
                    else:
                        current_chunk = [split_with_sep]
                        current_size = split_size
                else:
                    current_chunk.append(split_with_sep)
                    current_size += split_size

            if current_chunk:
                chunks.append(''.join(current_chunk).strip())
            return [c for c in chunks if c.strip()]

        return self._character_split(text, chunk_size, overlap)

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
        return self._split_text_recursive(text, config.CHUNK_SEPARATORS, chunk_size, overlap)
    
    def chunk_pages_with_metadata(
        self, 
        pages_data: List[Dict[str, Any]], 
        chunk_size: Optional[int] = None, 
        overlap: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Chunk pages with metadata preservation for enhanced citations.
        
        Args:
            pages_data: List of page dicts with keys: page_number, text, section_title
            chunk_size: Maximum size of each chunk (in characters)
            overlap: Overlap between chunks (in characters)
        
        Returns:
            List of chunk dictionaries with keys:
                - text: Chunk text content
                - page_number: Page number where chunk originates
                - section_title: Section title for the chunk (or None)
                - chunk_index: Sequential index of the chunk
        """
        chunks_with_metadata = []
        current_section = None
        chunk_index = 0
        
        for page_data in pages_data:
            page_num = page_data['page_number']
            page_text = page_data['text']
            
            if page_data.get('section_title'):
                current_section = page_data['section_title']
            
            section = page_data.get('section_title') or current_section
            
            page_chunks = self.chunk_text(page_text, chunk_size, overlap)
            
            for chunk_text in page_chunks:
                if len(chunk_text.strip()) >= 10:
                    chunks_with_metadata.append({
                        'text': chunk_text,
                        'page_number': page_num,
                        'section_title': section,
                        'chunk_index': chunk_index
                    })
                    chunk_index += 1
        
        logger.info(f"Created {len(chunks_with_metadata)} chunks with metadata from {len(pages_data)} pages")
        return chunks_with_metadata
