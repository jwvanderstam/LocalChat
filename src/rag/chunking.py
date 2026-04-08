"""
Text Chunking
=============

Handles text chunking with recursive character splitting, table preservation,
and metadata tracking for enhanced citations.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from .. import config
from ..utils.logging_config import get_logger

logger = get_logger(__name__)

# Try to import monitoring - graceful degradation if not available
try:
    from ..monitoring import timed
except ImportError:
    def timed(_metric_name: str):  # noqa: E306
        return lambda func: func


class TextChunkerMixin:
    """
    Mixin providing text chunking methods for DocumentProcessor.

    Supports recursive character splitting with table preservation
    and metadata tracking for enhanced citations.
    """

    def _split_large_table(
        self, table_text: str, table_header: str, max_size: int
    ) -> list[str]:
        """Split an oversized table into row-bounded chunks."""
        table_lines = table_text.split('\n')
        chunks: list[str] = []
        current: list[str] = [table_header]
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

    def _process_tables_in_text(
        self,
        text: str,
        table_matches: list,
        chunk_size: int,
        overlap: int,
        keep_tables_intact: bool,
        table_chunk_size: int,
    ) -> list[str]:
        """Process text that contains table markers, returning chunks with tables preserved."""
        chunks: list[str] = []
        current_pos = 0
        max_table_chunk = table_chunk_size if keep_tables_intact else chunk_size

        for match in table_matches:
            if match.start() > current_pos:
                before = text[current_pos:match.start()].strip()
                if before:
                    chunks.extend(self._chunk_text_standard(before, chunk_size, overlap))

            table_text = match.group(0).strip()
            if len(table_text) <= max_table_chunk:
                chunks.append(table_text)
                logger.debug(f"Table kept intact ({len(table_text)} chars)")
            else:
                table_header = table_text.split('\n')[0]
                split_chunks = self._split_large_table(table_text, table_header, max_table_chunk)
                chunks.extend(split_chunks)
                logger.debug(f"Large table split into {len(split_chunks)} chunks")

            current_pos = match.end()

        if current_pos < len(text):
            after = text[current_pos:].strip()
            if after:
                chunks.extend(self._chunk_text_standard(after, chunk_size, overlap))

        return chunks

    @staticmethod
    def _filter_valid_chunks(chunks: list[str]) -> list[str]:
        """Strip and drop chunks shorter than 10 characters."""
        return [c for raw in chunks if (c := raw.strip()) and len(c) >= 10]

    @timed('rag.chunk_text')
    def chunk_text(
        self, text: str, chunk_size: int | None = None, overlap: int | None = None
    ) -> list[str]:
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

        text = text.strip()
        if len(text) <= chunk_size:
            return [text] if text else []

        table_pattern = r'\[Table \d+ on page \d+\].*?(?=\[Table \d+ on page \d+\]|\Z)'  # NOSONAR
        table_matches = list(re.finditer(table_pattern, text, re.DOTALL))

        if table_matches:
            logger.debug(f"Found {len(table_matches)} table(s) in text")
            chunks = self._process_tables_in_text(
                text, table_matches, chunk_size, overlap, keep_tables_intact, table_chunk_size
            )
        else:
            chunks = self._chunk_text_standard(text, chunk_size, overlap)

        valid_chunks = self._filter_valid_chunks(chunks)
        logger.info(f"Chunked text into {len(valid_chunks)} valid chunks (standard_size={chunk_size}, table_size={table_chunk_size})")
        return valid_chunks

    def _character_split(self, text: str, chunk_size: int, overlap: int) -> list[str]:
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

    def _handle_split(
        self,
        split_with_sep: str,
        split_size: int,
        chunks: list[str],
        current_chunk: list[str],
        current_size: int,
        separators: list[str],
        separator: str,
        chunk_size: int,
        overlap: int,
    ) -> tuple[list[str], int]:
        """Process one split token, returning updated (current_chunk, current_size)."""
        if split_size > chunk_size:
            if current_chunk:
                chunks.append(''.join(current_chunk).strip())
            remaining = separators[separators.index(separator) + 1:]
            chunks.extend(self._split_text_recursive(split_with_sep, remaining, chunk_size, overlap))
            return [], 0

        if current_size + split_size > chunk_size:
            if current_chunk:
                chunks.append(''.join(current_chunk).strip())
            if overlap > 0 and current_chunk:
                overlap_text = ''.join(current_chunk)[-overlap:]
                return [overlap_text, split_with_sep], len(overlap_text) + split_size
            return [split_with_sep], split_size

        return current_chunk + [split_with_sep], current_size + split_size

    def _split_text_recursive(
        self, text: str, separators: list[str], chunk_size: int, overlap: int
    ) -> list[str]:
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

            chunks: list[str] = []
            current_chunk: list[str] = []
            current_size = 0
            splits = text.split(separator)

            for i, split in enumerate(splits):
                split_with_sep = split + separator if i < len(splits) - 1 else split
                current_chunk, current_size = self._handle_split(
                    split_with_sep, len(split_with_sep),
                    chunks, current_chunk, current_size,
                    separators, separator, chunk_size, overlap,
                )

            if current_chunk:
                chunks.append(''.join(current_chunk).strip())
            return [c for c in chunks if c.strip()]

        return self._character_split(text, chunk_size, overlap)

    def _chunk_text_standard(self, text: str, chunk_size: int, overlap: int) -> list[str]:
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
        pages_data: list[dict[str, Any]],
        chunk_size: int | None = None,
        overlap: int | None = None
    ) -> list[dict[str, Any]]:
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

    def chunk_slides(self, slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Chunk a PPTX presentation — one chunk per slide.

        Args:
            slides: List of slide dicts with keys: slide_number, text, title

        Returns:
            List of chunk dicts with keys: text, page_number, section_title, chunk_index
        """
        chunks = []
        for chunk_index, slide in enumerate(slides):
            text = slide.get('text', '').strip()
            if len(text) < 10:
                continue
            chunks.append({
                'text': text,
                'page_number': slide.get('slide_number'),
                'section_title': slide.get('title'),
                'chunk_index': chunk_index,
            })
        logger.info(f"chunk_slides: {len(chunks)} chunks from {len(slides)} slides")
        return chunks

    def chunk_code_python(self, text: str) -> list[dict[str, Any]]:
        """
        Chunk Python source code by top-level function and class definitions.

        Uses ``ast.parse`` to find boundaries; falls back to ``chunk_text``
        on SyntaxError.

        Returns:
            List of chunk dicts with keys: text, page_number, section_title, chunk_index
        """
        import ast as _ast

        lines = text.splitlines(keepends=True)

        try:
            tree = _ast.parse(text)
        except SyntaxError:
            logger.debug("chunk_code_python: SyntaxError — falling back to chunk_text")
            return [
                {'text': c, 'page_number': None, 'section_title': None, 'chunk_index': i}
                for i, c in enumerate(self.chunk_text(text))
            ]

        # Collect (start_line, end_line, name) for top-level defs (1-indexed)
        boundaries: list[tuple[int, int, str]] = []
        for node in _ast.iter_child_nodes(tree):
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
                end_line = getattr(node, 'end_lineno', None) or node.lineno
                boundaries.append((node.lineno, end_line, node.name))

        if not boundaries:
            return [
                {'text': c, 'page_number': None, 'section_title': None, 'chunk_index': i}
                for i, c in enumerate(self.chunk_text(text))
            ]

        chunks = []
        chunk_index = 0

        # Text before first definition
        first_start = boundaries[0][0]
        preamble = "".join(lines[:first_start - 1]).strip()
        if len(preamble) >= 10:
            chunks.append({'text': preamble, 'page_number': None, 'section_title': None, 'chunk_index': chunk_index})
            chunk_index += 1

        for start_line, end_line, name in boundaries:
            block = "".join(lines[start_line - 1:end_line]).strip()
            if len(block) < 10:
                continue
            chunks.append({'text': block, 'page_number': None, 'section_title': name, 'chunk_index': chunk_index})
            chunk_index += 1

        logger.info(f"chunk_code_python: {len(chunks)} chunks")
        return chunks

    def chunk_code_js_ts(self, text: str) -> list[dict[str, Any]]:
        """
        Chunk JavaScript/TypeScript source code by function and class boundaries.

        Uses regex on ``function NAME``, ``class NAME``, and
        ``const NAME = (`` patterns; no tree-sitter dependency.

        Returns:
            List of chunk dicts with keys: text, page_number, section_title, chunk_index
        """
        _BOUNDARY_RE = re.compile(
            r'^(?:export\s+)?(?:async\s+)?(?:function\s+(\w+)|class\s+(\w+)|const\s+(\w+)\s*=\s*(?:async\s*)?\()',
            re.MULTILINE,
        )

        matches = list(_BOUNDARY_RE.finditer(text))
        if not matches:
            return [
                {'text': c, 'page_number': None, 'section_title': None, 'chunk_index': i}
                for i, c in enumerate(self.chunk_text(text))
            ]

        chunks = []
        chunk_index = 0
        lines = text.splitlines(keepends=True)

        def _line_of(pos: int) -> int:
            return text[:pos].count('\n')

        # Preamble before first match
        preamble = text[:matches[0].start()].strip()
        if len(preamble) >= 10:
            chunks.append({'text': preamble, 'page_number': None, 'section_title': None, 'chunk_index': chunk_index})
            chunk_index += 1

        for i, match in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            block = text[match.start():end].strip()
            if len(block) < 10:
                continue
            name = match.group(1) or match.group(2) or match.group(3)
            chunks.append({'text': block, 'page_number': None, 'section_title': name, 'chunk_index': chunk_index})
            chunk_index += 1

        logger.info(f"chunk_code_js_ts: {len(chunks)} chunks")
        return chunks

    def chunk_email(self, text: str) -> list[dict[str, Any]]:
        """
        Chunk an email as a single unit.

        Multi-message threads are a future enhancement; for now one email
        → one chunk (or standard chunked if the body is very long).

        Returns:
            List of chunk dicts with keys: text, page_number, section_title, chunk_index
        """
        text = text.strip()
        if not text:
            return []
        if len(text) <= (config.CHUNK_SIZE * 2):
            return [{'text': text, 'page_number': None, 'section_title': None, 'chunk_index': 0}]
        # Very long email: fall back to standard chunking
        return [
            {'text': c, 'page_number': None, 'section_title': None, 'chunk_index': i}
            for i, c in enumerate(self.chunk_text(text))
        ]
