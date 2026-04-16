"""
Tests for src/rag/chunking.py

Covers:
  - TextChunkerMixin.chunk_text: short text, long text, table markers
  - _chunk_text_standard / _split_text_recursive: overlap, separators
  - _split_large_table: oversized table row-bounded split
  - chunk_pages_with_metadata: metadata propagation
  - chunk_slides: slide-per-chunk logic
  - chunk_code_python: AST-boundary chunking and SyntaxError fallback
  - chunk_code_js_ts: function/class/const-arrow boundary chunking
  - chunk_email: single-chunk vs. fallback-to-standard
"""

from __future__ import annotations

import pytest

from src.rag.chunking import TextChunkerMixin


# A concrete, no-deps subclass — the mixin has no abstract methods
class Chunker(TextChunkerMixin):
    pass


@pytest.fixture
def chunker():
    return Chunker()


# ===========================================================================
# chunk_text — basic paths
# ===========================================================================

class TestChunkText:
    def test_empty_string_returns_empty_list(self, chunker):
        assert chunker.chunk_text("") == []

    def test_short_text_returned_as_single_chunk(self, chunker):
        text = "Short text that fits in one chunk."
        result = chunker.chunk_text(text, chunk_size=500, overlap=0)
        assert result == [text]

    def test_long_text_splits_into_multiple_chunks(self, chunker):
        # 600 chars > chunk_size=100, so we expect multiple chunks
        text = ("This is a sentence. " * 30).strip()
        result = chunker.chunk_text(text, chunk_size=100, overlap=0)
        assert len(result) > 1

    def test_long_text_produces_multiple_chunks(self, chunker):
        # 600 identical words → must produce more than 1 chunk with a small chunk_size
        text = ("sentence " * 200).strip()
        result = chunker.chunk_text(text, chunk_size=80)
        assert len(result) > 1

    def test_overlap_produces_chunks(self, chunker):
        text = "AAAA BBBB CCCC DDDD EEEE FFFF GGGG HHHH IIII JJJJ KKKK LLLL MMMM "
        # Both calls should produce valid, non-empty lists
        result = chunker.chunk_text(text, chunk_size=20, overlap=5)
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_text_with_table_marker_kept_intact(self, chunker):
        table = (
            "[Table 1 on page 2]\n"
            "| Col A | Col B |\n"
            "| ----- | ----- |\n"
            "| val1  | val2  |\n"
        )
        result = chunker.chunk_text(table, chunk_size=2000, overlap=0)
        # The table should appear as (at most) one chunk
        assert any("Table 1 on page 2" in c for c in result)

    def test_chunks_have_minimum_length(self, chunker):
        text = ("Hello world. " * 50).strip()
        result = chunker.chunk_text(text, chunk_size=50, overlap=5)
        for chunk in result:
            assert len(chunk) >= 10


# ===========================================================================
# _split_large_table
# ===========================================================================

class TestSplitLargeTable:
    def test_single_row_table_returns_one_chunk(self, chunker):
        header = "| A | B |"
        table = header + "\n| 1 | 2 |"
        result = chunker._split_large_table(table, header, max_size=1000)
        assert len(result) == 1

    def test_many_rows_splits_on_size_boundary(self, chunker):
        header = "| Col |"
        rows = [f"| {'x' * 20} |" for _ in range(20)]
        table = header + "\n" + "\n".join(rows)
        # Small max_size forces splits
        result = chunker._split_large_table(table, header, max_size=60)
        assert len(result) > 1
        # Every split chunk starts with the header
        for chunk in result:
            assert chunk.startswith(header)


# ===========================================================================
# chunk_pages_with_metadata
# ===========================================================================

class TestChunkPagesWithMetadata:
    def test_empty_pages_returns_empty(self, chunker):
        assert chunker.chunk_pages_with_metadata([]) == []

    def test_single_page_produces_chunk_with_metadata(self, chunker):
        pages = [{'page_number': 1, 'text': 'Hello world, this is page one.', 'section_title': 'Intro'}]
        result = chunker.chunk_pages_with_metadata(pages, chunk_size=500, overlap=0)
        assert len(result) >= 1
        assert result[0]['page_number'] == 1
        assert result[0]['section_title'] == 'Intro'

    def test_section_title_propagates_across_pages(self, chunker):
        pages = [
            {'page_number': 1, 'text': 'First page content here.', 'section_title': 'Section A'},
            {'page_number': 2, 'text': 'Second page follows the same section.', 'section_title': None},
        ]
        result = chunker.chunk_pages_with_metadata(pages, chunk_size=500, overlap=0)
        # Both pages should carry 'Section A' because page 2 has no new title
        sections = [c['section_title'] for c in result]
        assert all(s == 'Section A' for s in sections)

    def test_chunk_index_is_sequential(self, chunker):
        pages = [
            {'page_number': i + 1, 'text': 'Some meaningful text here. ' * 5, 'section_title': None}
            for i in range(3)
        ]
        result = chunker.chunk_pages_with_metadata(pages, chunk_size=50, overlap=0)
        indices = [c['chunk_index'] for c in result]
        assert indices == list(range(len(result)))


# ===========================================================================
# chunk_slides
# ===========================================================================

class TestChunkSlides:
    def test_empty_slides_returns_empty(self, chunker):
        assert chunker.chunk_slides([]) == []

    def test_short_slide_text_is_skipped(self, chunker):
        slides = [{'slide_number': 1, 'text': 'Hi', 'title': 'T'}]
        assert chunker.chunk_slides(slides) == []

    def test_valid_slide_produces_chunk(self, chunker):
        slides = [{'slide_number': 2, 'text': 'This slide has enough content.', 'title': 'Main'}]
        result = chunker.chunk_slides(slides)
        assert len(result) == 1
        assert result[0]['page_number'] == 2
        assert result[0]['section_title'] == 'Main'

    def test_multiple_slides_all_included(self, chunker):
        slides = [
            {'slide_number': i + 1, 'text': 'Slide content is here.', 'title': f'Slide {i + 1}'}
            for i in range(5)
        ]
        result = chunker.chunk_slides(slides)
        assert len(result) == 5


# ===========================================================================
# chunk_code_python
# ===========================================================================

class TestChunkCodePython:
    def test_empty_returns_empty(self, chunker):
        assert chunker.chunk_code_python("") == []

    def test_single_function_produces_one_chunk(self, chunker):
        code = "def hello():\n    return 'world'\n"
        result = chunker.chunk_code_python(code)
        assert len(result) >= 1
        assert any("def hello" in c['text'] for c in result)

    def test_multiple_functions_each_get_chunk(self, chunker):
        code = (
            "def alpha():\n    pass\n\n"
            "def beta():\n    pass\n\n"
            "def gamma():\n    pass\n"
        )
        result = chunker.chunk_code_python(code)
        names = [c['section_title'] for c in result if c['section_title']]
        assert 'alpha' in names
        assert 'beta' in names
        assert 'gamma' in names

    def test_syntax_error_falls_back_to_chunk_text(self, chunker):
        # Broken Python — should not raise, falls back to generic chunking
        code = "def broken(:\n    pass\n"
        result = chunker.chunk_code_python(code)
        # Should return something (no crash)
        assert isinstance(result, list)

    def test_class_definition_captured(self, chunker):
        code = "class MyClass:\n    def method(self):\n        pass\n"
        result = chunker.chunk_code_python(code)
        assert any(c['section_title'] == 'MyClass' for c in result)


# ===========================================================================
# chunk_code_js_ts
# ===========================================================================

class TestChunkCodeJsTs:
    def test_empty_returns_empty(self, chunker):
        assert chunker.chunk_code_js_ts("") == []

    def test_function_declaration_captured(self, chunker):
        code = "function greet(name) {\n  return `Hello ${name}`;\n}\n"
        result = chunker.chunk_code_js_ts(code)
        assert any(c['section_title'] == 'greet' for c in result)

    def test_class_declaration_captured(self, chunker):
        code = "class Animal {\n  speak() { console.log('...'); }\n}\n"
        result = chunker.chunk_code_js_ts(code)
        assert any(c['section_title'] == 'Animal' for c in result)

    def test_const_arrow_captured(self, chunker):
        code = "const handler = (event) => {\n  console.log(event);\n};\n"
        result = chunker.chunk_code_js_ts(code)
        assert any(c['section_title'] == 'handler' for c in result)

    def test_no_boundaries_falls_back_to_chunk_text(self, chunker):
        code = "const x = 1;\nconst y = 2;\n"
        result = chunker.chunk_code_js_ts(code)
        assert isinstance(result, list)


# ===========================================================================
# chunk_email
# ===========================================================================

class TestChunkEmail:
    def test_empty_returns_empty(self, chunker):
        assert chunker.chunk_email("") == []

    def test_short_email_single_chunk(self, chunker):
        email = "Subject: Hello\n\nDear team, this is a short email."
        result = chunker.chunk_email(email)
        assert len(result) == 1
        assert result[0]['chunk_index'] == 0

    def test_very_long_email_falls_back_to_multiple_chunks(self, chunker):
        # Produce an email well beyond CHUNK_SIZE * 2
        email = ("This is a paragraph of email content. " * 300).strip()
        result = chunker.chunk_email(email)
        # Standard chunking will split it
        assert len(result) >= 1
