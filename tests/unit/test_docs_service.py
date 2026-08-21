"""Unit tests for src/docs/service.py (DocsService)."""

from pathlib import Path

import pytest

from src.docs.service import DocsService


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class TestLoadAll:
    def test_loads_all_catalogued_files(self, tmp_path):
        _write(tmp_path, "a.md", "# Doc A\n\nContent A.\n")
        _write(tmp_path, "sub/b.md", "# Doc B\n\nContent B.\n")
        service = DocsService(root_dir=tmp_path, catalogue=[("doc-a", "a.md"), ("doc-b", "sub/b.md")])

        count = service.load_all()

        assert count == 2
        assert service.list_docs() == [
            {"slug": "doc-a", "title": "Doc A", "path": str(tmp_path / "a.md")},
            {"slug": "doc-b", "title": "Doc B", "path": str(tmp_path / "sub/b.md")},
        ]

    def test_missing_catalogue_file_is_skipped_without_raising(self, tmp_path):
        service = DocsService(root_dir=tmp_path, catalogue=[("missing", "does-not-exist.md")])

        count = service.load_all()

        assert count == 0
        assert service.list_docs() == []

    def test_title_falls_back_to_filename_stem_when_no_h1(self, tmp_path):
        _write(tmp_path, "no-heading.md", "Just a paragraph, no heading at all.\n")
        service = DocsService(root_dir=tmp_path, catalogue=[("no-heading", "no-heading.md")])
        service.load_all()

        entry = service.get_doc("no-heading")

        assert entry.title == "no-heading"


class TestGetDoc:
    def test_returns_none_for_unknown_slug(self, tmp_path):
        service = DocsService(root_dir=tmp_path, catalogue=[])
        service.load_all()

        assert service.get_doc("does-not-exist") is None

    def test_returns_full_rendered_html(self, tmp_path):
        _write(tmp_path, "doc.md", "# Title\n\nSome **bold** text.\n")
        service = DocsService(root_dir=tmp_path, catalogue=[("doc", "doc.md")])
        service.load_all()

        entry = service.get_doc("doc")

        assert entry is not None
        assert "<strong>bold</strong>" in entry.html


class TestGetFragment:
    def test_returns_none_for_unknown_doc_slug(self, tmp_path):
        service = DocsService(root_dir=tmp_path, catalogue=[])
        service.load_all()

        assert service.get_fragment("no-such-doc", "anything") is None

    def test_returns_none_for_unknown_fragment_slug(self, tmp_path):
        _write(tmp_path, "doc.md", "# Title\n\n## Section A\ntext\n")
        service = DocsService(root_dir=tmp_path, catalogue=[("doc", "doc.md")])
        service.load_all()

        assert service.get_fragment("doc", "no-such-fragment") is None

    def test_returns_fragment_html_for_known_heading(self, tmp_path):
        _write(tmp_path, "doc.md", "# Title\n\n## Section A\nContent A.\n\n## Section B\nContent B.\n")
        service = DocsService(root_dir=tmp_path, catalogue=[("doc", "doc.md")])
        service.load_all()

        fragment = service.get_fragment("doc", "section-a")

        assert fragment is not None
        assert "Content A." in fragment
        assert "Content B." not in fragment

    def test_duplicate_headings_get_numeric_suffix(self, tmp_path):
        _write(
            tmp_path, "doc.md",
            "# Title\n\n## Section A\nFirst.\n\n## Section A\nSecond.\n",
        )
        service = DocsService(root_dir=tmp_path, catalogue=[("doc", "doc.md")])
        service.load_all()

        first = service.get_fragment("doc", "section-a")
        second = service.get_fragment("doc", "section-a-1")

        assert first is not None and "First." in first
        assert second is not None and "Second." in second

    def test_nested_heading_included_up_to_next_equal_or_higher_level(self, tmp_path):
        _write(
            tmp_path, "doc.md",
            "# Title\n\n## Section A\nouter\n\n### Sub A1\ninner\n\n## Section B\nother\n",
        )
        service = DocsService(root_dir=tmp_path, catalogue=[("doc", "doc.md")])
        service.load_all()

        fragment = service.get_fragment("doc", "section-a")

        assert "outer" in fragment
        assert "inner" in fragment
        assert "other" not in fragment


class TestReloadAll:
    def test_picks_up_file_edit(self, tmp_path):
        path = _write(tmp_path, "doc.md", "# Title\n\nOriginal content.\n")
        service = DocsService(root_dir=tmp_path, catalogue=[("doc", "doc.md")])
        service.load_all()
        assert "Original content." in service.get_doc("doc").html

        path.write_text("# Title\n\nUpdated content.\n", encoding="utf-8")
        service.reload_all()

        assert "Updated content." in service.get_doc("doc").html
        assert "Original content." not in service.get_doc("doc").html


@pytest.mark.unit
class TestFragmentBody:
    """QA-9 — the settings sliders rendered their own label a second time.

    A fragment includes its heading, which the docs viewer needs. The settings page
    already has a label saying the same thing, so the heading arrived directly
    beneath it at page-heading size and read as a broken heading level.
    """

    def _service(self, tmp_path):
        from src.docs.service import DocsService

        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "SETTINGS.md").write_text(
            "# Settings Reference\n\n"
            "## Retrieval candidates (TOP_K_RESULTS)\n\n"
            "Initial number of chunks fetched.\n\n"
            "## Chunks sent to LLM (RERANK_TOP_K)\n\n"
            "How many survive reranking.\n",
            encoding="utf-8",
        )
        service = DocsService(
            root_dir=tmp_path, catalogue=[("docs-settings", "docs/SETTINGS.md")]
        )
        service.load_all()
        return service

    def test_the_body_omits_the_heading(self, tmp_path):
        body = self._service(tmp_path).get_fragment_body(
            "docs-settings", "retrieval-candidates-top_k_results"
        )
        assert "Initial number of chunks fetched." in body
        assert "<h2" not in body
        assert "Retrieval candidates" not in body

    def test_the_full_fragment_still_carries_its_heading(self, tmp_path):
        """The docs viewer needs it — this must not strip it there too."""
        html = self._service(tmp_path).get_fragment(
            "docs-settings", "retrieval-candidates-top_k_results"
        )
        assert "<h2" in html
        assert "Retrieval candidates" in html

    def test_only_the_leading_heading_goes(self, tmp_path):
        """A heading later in a fragment is content, not a duplicated label."""
        service = self._service(tmp_path)
        body = service.get_fragment_body("docs-settings", "settings-reference")
        assert "<h2" in body, "a nested heading was removed along with the leading one"

    def test_an_unknown_fragment_is_none_rather_than_empty(self, tmp_path):
        assert self._service(tmp_path).get_fragment_body("docs-settings", "nope") is None

    def test_an_unknown_document_is_none(self, tmp_path):
        assert self._service(tmp_path).get_fragment_body("nope", "nope") is None


@pytest.mark.unit
class TestCatalogueOrder:
    """QA-10 — an AI coding-agent instruction file led the Documentation list."""

    def test_product_documentation_comes_before_contributor_material(self):
        from src.docs.service import _CATALOGUE

        slugs = [slug for slug, _ in _CATALOGUE]
        assert slugs.index("readme") < slugs.index("claude-md")
        assert slugs.index("docs-deployment") < slugs.index("claude-md")
        assert slugs.index("docs-troubleshooting") < slugs.index("rules-python")

    def test_the_first_entry_is_the_product_readme(self):
        from src.docs.service import _CATALOGUE

        assert _CATALOGUE[0][0] == "readme"

    def test_no_document_was_dropped_in_the_reorder(self):
        """Reordering a list is exactly where an entry goes missing unnoticed."""
        from src.docs.service import _CATALOGUE

        slugs = [slug for slug, _ in _CATALOGUE]
        assert len(slugs) == len(set(slugs)), "duplicate slug in the catalogue"
        assert len(slugs) == 28
