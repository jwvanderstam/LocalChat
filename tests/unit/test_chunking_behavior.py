"""
Tests for text chunking algorithms in TextChunkerMixin.

Each test targets a specific algorithm — table splitting with header
preservation, overlap creation, chunk filtering, and metadata propagation —
rather than line coverage.
"""

import os
from unittest.mock import patch

import pytest

# src/config.py raises at import time if PG_PASSWORD is missing.
# Set a test sentinel so collection succeeds without a real database.
os.environ.setdefault("PG_PASSWORD", "test-sentinel")

from src.rag.chunking import TextChunkerMixin

# ---------------------------------------------------------------------------
# Minimal concrete class for testing the mixin
# ---------------------------------------------------------------------------

class Chunker(TextChunkerMixin):
    pass


@pytest.fixture
def chunker():
    return Chunker()


def _patch_config(**overrides):
    """Return a context manager that patches config with sensible defaults."""
    defaults = {
        "CHUNK_SIZE": 10_000,
        "CHUNK_OVERLAP": 0,
        "TABLE_CHUNK_SIZE": 20_000,
        "KEEP_TABLES_INTACT": True,
        "CHUNK_SEPARATORS": ["\n\n", "\n", " ", ""],
    }
    defaults.update(overrides)
    return patch("src.rag.chunking.config", **defaults)


# ---------------------------------------------------------------------------
# _filter_valid_chunks
# ---------------------------------------------------------------------------

class TestFilterValidChunks:
    def test_drops_chunks_shorter_than_10_chars(self, chunker):
        assert chunker._filter_valid_chunks(["hi", "short", "long enough text"]) == [
            "long enough text"
        ]

    def test_drops_whitespace_only_chunks(self, chunker):
        assert chunker._filter_valid_chunks(["   ", "\n\n", "valid chunk text"]) == [
            "valid chunk text"
        ]

    def test_keeps_chunks_of_exactly_10_chars(self, chunker):
        assert chunker._filter_valid_chunks(["0123456789"]) == ["0123456789"]

    def test_empty_input_returns_empty(self, chunker):
        assert chunker._filter_valid_chunks([]) == []

    def test_strips_surrounding_whitespace_before_length_check(self, chunker):
        # "  hi  " → stripped "hi" → 2 chars → dropped
        assert chunker._filter_valid_chunks(["  hi  "]) == []


# ---------------------------------------------------------------------------
# _split_large_table
# ---------------------------------------------------------------------------

class TestSplitLargeTable:
    def _make_table(self, n_rows=10):
        header = "| Col1 | Col2 |"
        rows = [f"| val{i:02d} | dat{i:02d} |" for i in range(n_rows)]
        return header, "\n".join([header] + rows)

    def test_small_table_returns_single_chunk(self, chunker):
        header, table = self._make_table(n_rows=2)
        chunks = chunker._split_large_table(table, header, max_size=10_000)
        assert len(chunks) == 1

    def test_oversized_table_is_split_into_multiple_chunks(self, chunker):
        header, table = self._make_table(n_rows=20)
        row_size = len("| val00 | dat00 |") + 1
        # Allow only header + one row per chunk
        max_size = len(header) + row_size + 2
        chunks = chunker._split_large_table(table, header, max_size=max_size)
        assert len(chunks) > 1

    def test_every_chunk_starts_with_table_header(self, chunker):
        header, table = self._make_table(n_rows=20)
        row_size = len("| val00 | dat00 |") + 1
        max_size = len(header) + row_size + 2
        chunks = chunker._split_large_table(table, header, max_size=max_size)
        for i, chunk in enumerate(chunks):
            assert chunk.startswith(header), (
                f"Chunk {i} is missing the header:\n{chunk[:60]}"
            )

    def test_all_rows_appear_across_chunks(self, chunker):
        n_rows = 15
        header, table = self._make_table(n_rows=n_rows)
        max_size = len(header) + 40
        chunks = chunker._split_large_table(table, header, max_size=max_size)
        combined = "\n".join(chunks)
        for i in range(n_rows):
            assert f"val{i:02d}" in combined, f"Row {i} missing from output"


# ---------------------------------------------------------------------------
# _character_split
# ---------------------------------------------------------------------------

class TestCharacterSplit:
    def test_creates_overlap_between_consecutive_chunks(self, chunker):
        text = "abcdefghijklmnopqrstuvwxyz" * 4  # 104 chars
        overlap = 10
        chunks = chunker._character_split(text, chunk_size=30, overlap=overlap)

        assert len(chunks) > 1
        # The first `overlap` chars of chunk[1] must equal the last `overlap` of chunk[0]
        assert chunks[1][:overlap] == chunks[0][-overlap:]

    def test_text_shorter_than_chunk_size_is_one_chunk(self, chunker):
        text = "short text"
        chunks = chunker._character_split(text, chunk_size=100, overlap=10)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_no_empty_chunks_produced(self, chunker):
        text = "x" * 200
        chunks = chunker._character_split(text, chunk_size=30, overlap=5)
        assert all(c.strip() for c in chunks)


# ---------------------------------------------------------------------------
# chunk_text
# ---------------------------------------------------------------------------

class TestChunkText:
    def test_text_shorter_than_chunk_size_is_returned_as_single_chunk(self, chunker):
        with _patch_config(CHUNK_SIZE=1000, CHUNK_OVERLAP=100):
            result = chunker.chunk_text("This is a short text.")
        assert result == ["This is a short text."]

    def test_empty_text_returns_empty_list(self, chunker):
        with _patch_config(CHUNK_SIZE=1000, CHUNK_OVERLAP=100):
            result = chunker.chunk_text("")
        assert result == []

    def test_long_text_is_split_into_multiple_chunks(self, chunker):
        long_text = "word " * 500  # 2500 chars
        with _patch_config(CHUNK_SIZE=200, CHUNK_OVERLAP=20):
            result = chunker.chunk_text(long_text)
        assert len(result) > 1

    def test_all_chunks_pass_minimum_length_filter(self, chunker):
        long_text = "word " * 500
        with _patch_config(CHUNK_SIZE=200, CHUNK_OVERLAP=20):
            result = chunker.chunk_text(long_text)
        assert all(len(c) >= 10 for c in result)


# ---------------------------------------------------------------------------
# chunk_pages_with_metadata
# ---------------------------------------------------------------------------

class TestChunkPagesWithMetadata:
    def _pages(self, texts, titles=None):
        titles = titles or [None] * len(texts)
        return [
            {"page_number": i + 1, "text": t, "section_title": s}
            for i, (t, s) in enumerate(zip(texts, titles, strict=False))
        ]

    def test_chunk_index_is_globally_sequential(self, chunker):
        pages = self._pages(["First page content here", "Second page content here"])
        with _patch_config():
            result = chunker.chunk_pages_with_metadata(pages)
        indices = [c["chunk_index"] for c in result]
        assert indices == list(range(len(result)))

    def test_page_number_is_preserved_in_each_chunk(self, chunker):
        pages = self._pages(["Page seven content here"], titles=[None])
        pages[0]["page_number"] = 7
        with _patch_config():
            result = chunker.chunk_pages_with_metadata(pages)
        assert all(c["page_number"] == 7 for c in result)

    def test_section_title_carries_forward_when_next_page_has_none(self, chunker):
        """A section title set on page N should apply to page N+1 if it has no title."""
        pages = self._pages(
            ["Introduction content here", "More introduction content here"],
            titles=["Introduction", None],
        )
        with _patch_config():
            result = chunker.chunk_pages_with_metadata(pages)

        page2_chunks = [c for c in result if c["page_number"] == 2]
        assert page2_chunks, "Expected at least one chunk from page 2"
        assert all(c["section_title"] == "Introduction" for c in page2_chunks)

    def test_new_section_title_overrides_carried_forward_title(self, chunker):
        """A fresh title on page N+1 must replace the one carried from page N."""
        pages = self._pages(
            ["Intro content here", "Methods content here"],
            titles=["Introduction", "Methods"],
        )
        with _patch_config():
            result = chunker.chunk_pages_with_metadata(pages)

        page2_chunks = [c for c in result if c["page_number"] == 2]
        assert all(c["section_title"] == "Methods" for c in page2_chunks)

    def test_short_chunks_below_minimum_are_excluded(self, chunker):
        pages = self._pages(["ok", "this text is long enough to be a real chunk"])
        with _patch_config():
            result = chunker.chunk_pages_with_metadata(pages)
        # "ok" has 2 chars — should be dropped
        assert all(len(c["text"].strip()) >= 10 for c in result)
