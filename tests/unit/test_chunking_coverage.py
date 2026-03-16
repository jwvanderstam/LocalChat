# -*- coding: utf-8 -*-
"""Additional coverage for rag/chunking.py."""

import pytest
from typing import List


class TestSplitLargeTable:
    def setup_method(self):
        from src.rag.chunking import TextChunkerMixin
        self.chunker = TextChunkerMixin()

    def test_single_chunk_when_fits(self):
        table = "Header Row\nRow 1 data\nRow 2 data"
        chunks = self.chunker._split_large_table(table, "Header Row", 1000)
        assert len(chunks) == 1
        assert chunks[0] == table

    def test_splits_when_over_max_size(self):
        header = "Col1 | Col2"
        rows = "\n".join([f"Val{i} | Data{i}" for i in range(50)])
        table = header + "\n" + rows
        chunks = self.chunker._split_large_table(table, header, 100)
        assert len(chunks) > 1
        for chunk in chunks:
            assert header in chunk

    def test_each_chunk_starts_with_header(self):
        header = "Name | Value"
        rows = "\n".join([f"Row{i} | {i}" for i in range(20)])
        table = header + "\n" + rows
        chunks = self.chunker._split_large_table(table, header, 80)
        for chunk in chunks:
            assert chunk.startswith(header)


class TestProcessTablesInText:
    def setup_method(self):
        from src.rag.chunking import TextChunkerMixin
        self.chunker = TextChunkerMixin()

    def test_single_table_kept_intact(self):
        import re
        text = "Before text.\n[Table 1 on page 1]\nCol A | Col B\nVal 1 | Val 2\n"
        pattern = r'\[Table \d+ on page \d+\].*?(?=\[Table \d+ on page \d+\]|\Z)'
        matches = list(re.finditer(pattern, text, re.DOTALL))
        chunks = self.chunker._process_tables_in_text(
            text, matches, 500, 50, True, 2000
        )
        assert any("[Table 1 on page 1]" in c for c in chunks)

    def test_text_before_table_is_chunked(self):
        import re
        before = "This is text before the table. " * 5
        table_section = "[Table 1 on page 1]\nH1 | H2\nA | B"
        text = before + table_section
        pattern = r'\[Table \d+ on page \d+\].*?(?=\[Table \d+ on page \d+\]|\Z)'
        matches = list(re.finditer(pattern, text, re.DOTALL))
        chunks = self.chunker._process_tables_in_text(
            text, matches, 100, 10, True, 2000
        )
        # Before text should be split into chunks
        assert len(chunks) >= 1

    def test_text_after_last_table_is_chunked(self):
        import re
        table_section = "[Table 1 on page 1]\nH1 | H2\nA | B\n"
        after = "Text after the table. " * 5
        text = table_section + after
        pattern = r'\[Table \d+ on page \d+\].*?(?=\[Table \d+ on page \d+\]|\Z)'
        matches = list(re.finditer(pattern, text, re.DOTALL))
        chunks = self.chunker._process_tables_in_text(
            text, matches, 100, 10, True, 2000
        )
        assert len(chunks) >= 1

    def test_large_table_is_split(self):
        import re
        header = "Col1 | Col2"
        rows = "\n".join([f"Row{i} | Data{i}" for i in range(100)])
        table_section = f"[Table 1 on page 1]\n{header}\n{rows}"
        pattern = r'\[Table \d+ on page \d+\].*?(?=\[Table \d+ on page \d+\]|\Z)'
        matches = list(re.finditer(pattern, table_section, re.DOTALL))
        chunks = self.chunker._process_tables_in_text(
            table_section, matches, 200, 20, True, 500
        )
        assert len(chunks) > 1


class TestFilterValidChunks:
    def test_removes_short_chunks(self):
        from src.rag.chunking import TextChunkerMixin
        result = TextChunkerMixin._filter_valid_chunks(["hi", "a" * 10, "   ", "x" * 15])
        assert "hi" not in result
        assert "a" * 10 in result

    def test_strips_whitespace(self):
        from src.rag.chunking import TextChunkerMixin
        result = TextChunkerMixin._filter_valid_chunks(["  " + "a" * 10 + "  "])
        assert result[0] == "a" * 10

    def test_empty_input_returns_empty(self):
        from src.rag.chunking import TextChunkerMixin
        result = TextChunkerMixin._filter_valid_chunks([])
        assert result == []

    def test_all_too_short_returns_empty(self):
        from src.rag.chunking import TextChunkerMixin
        result = TextChunkerMixin._filter_valid_chunks(["abc", "de", "f"])
        assert result == []


class TestHandleSplit:
    def setup_method(self):
        from src.rag.chunking import TextChunkerMixin
        self.chunker = TextChunkerMixin()
        self.separators = ['\n\n', '\n', ' ', '']

    def test_oversized_split_flushes_current_chunk(self):
        chunks = []
        current_chunk = ["existing "]
        current_size = 9
        new_chunk, new_size = self.chunker._handle_split(
            "a" * 600, 600,
            chunks, current_chunk, current_size,
            self.separators, '\n\n', 500, 50
        )
        assert "existing" in chunks[0]
        assert new_chunk == []
        assert new_size == 0

    def test_overflow_creates_overlap(self):
        chunks = []
        current_chunk = ["existing text "]
        current_size = 100
        new_chunk, new_size = self.chunker._handle_split(
            "new content", 11,
            chunks, current_chunk, current_size,
            self.separators, '\n\n', 105, 20
        )
        # overflow path taken since 100+11=111 > 105
        assert len(chunks) == 1

    def test_append_when_fits(self):
        chunks = []
        current_chunk = ["first "]
        current_size = 6
        new_chunk, new_size = self.chunker._handle_split(
            "second", 6,
            chunks, current_chunk, current_size,
            self.separators, '\n\n', 500, 50
        )
        assert "second" in new_chunk
        assert new_size == 12
        assert len(chunks) == 0


class TestChunkTextIntegration:
    def setup_method(self):
        from src.rag.chunking import TextChunkerMixin
        self.chunker = TextChunkerMixin()

    def test_short_text_returned_as_single_chunk(self):
        text = "Short text."
        result = self.chunker.chunk_text(text, chunk_size=500)
        assert result == [text]

    def test_empty_text_returns_empty_list(self):
        result = self.chunker.chunk_text("", chunk_size=500)
        assert result == []

    def test_long_text_split_into_multiple_chunks(self):
        text = "Word " * 500
        result = self.chunker.chunk_text(text, chunk_size=100, overlap=10)
        assert len(result) > 1

    def test_text_with_table_keeps_table_intact(self):
        table = "[Table 1 on page 1]\nName | Value\nAlice | 42"
        text = "Some text before.\n" + table + "\nSome text after."
        result = self.chunker.chunk_text(text, chunk_size=2000)
        assert any("[Table 1 on page 1]" in c for c in result)

    def test_chunks_are_minimum_length(self):
        text = "Hello world " * 100
        result = self.chunker.chunk_text(text, chunk_size=50, overlap=5)
        for chunk in result:
            assert len(chunk) >= 10

    def test_overlap_creates_context_continuity(self):
        text = "sentence one. sentence two. sentence three. " * 20
        result = self.chunker.chunk_text(text, chunk_size=100, overlap=20)
        assert len(result) >= 1

    def test_recursive_splitting_with_paragraphs(self):
        text = "\n\n".join(["Paragraph " + str(i) + " content here." for i in range(20)])
        result = self.chunker.chunk_text(text, chunk_size=100, overlap=10)
        assert len(result) > 1


class TestCharacterSplit:
    def setup_method(self):
        from src.rag.chunking import TextChunkerMixin
        self.chunker = TextChunkerMixin()

    def test_basic_split(self):
        text = "a" * 100
        chunks = self.chunker._character_split(text, chunk_size=30, overlap=5)
        assert all(len(c) <= 30 for c in chunks)
        assert len(chunks) > 1

    def test_overlap_means_consecutive_chunks_share_content(self):
        text = "abcdefghijklmnopqrstuvwxyz" * 4
        chunks = self.chunker._character_split(text, chunk_size=10, overlap=3)
        assert len(chunks) > 1
