"""PDF table extraction, tested against a real PDF.

This file previously held six tests, all skipped: *"pdfplumber/PyPDF2 imported
inside function, cannot mock. Functionality verified manually."* Two things were
wrong with that. The patch target (`src.rag.pdfplumber`) never existed — the
loader imports pdfplumber *inside* `_try_pdfplumber_import()` so it can fall
back — so the tests could not have passed as written. And "verified manually" is
a claim with no expiry and no enforcement, on the ingest path the product is
built on.

`reportlab` is already a dependency, so a real PDF containing a real table costs
nothing to build. Two layers are covered, deliberately:

* what a caller gets from `load_pdf_file()`, asserted without naming an
  extractor — the loader tries pymupdf4llm, then pdfplumber, then pypdf, and
  which one wins depends on what is installed;
* `_format_table_rows()`, which pins the pipe-delimited shape the chunker
  downstream depends on, and needs no PDF at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.rag import DocumentProcessor

TABLE_ROWS = [
    ["Name", "Age", "City"],
    ["John", "25", "New York"],
    ["Mary", "30", "Boston"],
]


@pytest.fixture
def pdf_with_a_table(tmp_path) -> Path:
    """A one-page PDF whose table is drawn with ruling lines, which is what the
    table detectors look for."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

    path = tmp_path / "with_table.pdf"
    table = Table(TABLE_ROWS)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
    ]))
    SimpleDocTemplate(str(path), pagesize=A4).build([table])
    return path


@pytest.mark.unit
class TestTableContentSurvivesExtraction:
    def test_every_cell_of_the_table_reaches_the_extracted_text(self, pdf_with_a_table):
        """The property that matters to ingest: nothing in the table is dropped.
        Asserted per cell rather than on a formatted row, because the row
        separator differs between extractors and the cell values do not."""
        success, content = DocumentProcessor().load_pdf_file(str(pdf_with_a_table))

        assert success is True
        missing = [cell for row in TABLE_ROWS for cell in row if cell not in content]
        assert missing == [], f"cells lost during extraction: {missing}"


@pytest.mark.unit
class TestFormatTableRows:
    """The pdfplumber arm's formatter. A pure function over rows — the thing the
    old tests were reaching for through three layers of mock."""

    def test_cells_are_joined_with_pipes_and_rows_with_newlines(self):
        formatted = DocumentProcessor()._format_table_rows(TABLE_ROWS)

        assert formatted == (
            "Name | Age | City\n"
            "John | 25 | New York\n"
            "Mary | 30 | Boston\n"
        )

    def test_an_empty_cell_becomes_an_empty_column_rather_than_vanishing(self):
        """Dropping a `None` would shift every later cell into the wrong column."""
        formatted = DocumentProcessor()._format_table_rows([["Name", None, "City"]])

        assert formatted == "Name |  | City\n"

    def test_a_structurally_empty_row_is_skipped_but_an_all_blank_one_is_not(self):
        """Pinning what the code does, which is not what its guard suggests.
        `[]` is dropped by the `if not row` check, but `["", None]` joins to
        `" | "`, and `" | ".strip()` is `"|"` — truthy — so the separators
        survive into the chunk. Asserted as-is rather than corrected: changing
        the output would change what the chunker sees, which is a decision, not
        a test fix."""
        formatted = DocumentProcessor()._format_table_rows([["a"], [], ["", None], ["b"]])

        assert formatted == "a\n | \nb\n"
