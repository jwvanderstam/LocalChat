"""Cross-document links in the Docs viewer must reach the document.

The docs link each other the way the repository does, `[X](X.md)` relative to the
file, and the server renders that href as written. In the viewer it resolved to
/docs/X.md, which nothing serves, so every such link answered with the JSON 404
envelope. Found on the deployed stack on 2026-09-14 by clicking one.

Asserted on the HTML the module put into the content pane, not on the HTML the test
supplied: the rewrite is the whole change, and the pane holds the input verbatim
when it does nothing.
"""

from __future__ import annotations

import pytest

from tests.utils.js_harness import NODE_MISSING, run_js

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(NODE_MISSING, reason="node is not installed"),
]

CATALOGUE = [
    {"slug": "docs-deployment-log", "title": "Deployment log", "path": "/app/docs/DEPLOYMENT_LOG.md"},
    {"slug": "docs-deployment-scaleway", "title": "Scaleway", "path": "/app/docs/DEPLOYMENT_SCALEWAY.md"},
    {"slug": "claude-md", "title": "CLAUDE.md", "path": "/app/CLAUDE.md"},
]


def _render(html: str, catalogue: list[dict] = CATALOGUE) -> str:
    # The specific route first: the harness matches on substring, and the
    # catalogue URL is a prefix of every document URL.
    result = run_js(
        "docs.js",
        routes=[
            ("/api/repo-docs/docs-deployment-log", {"html": html}),
            ("/api/repo-docs", catalogue),
        ],
    )
    return result["html"]["docs-content"]


class TestARelativeMarkdownLinkBecomesTheSlug:
    def test_a_sibling_file_resolves(self):
        out = _render('<a href="DEPLOYMENT_SCALEWAY.md">plan</a>')
        assert 'href="#docs-deployment-scaleway"' in out

    def test_a_parent_directory_link_resolves(self):
        out = _render('<a href="../CLAUDE.md">rules</a>')
        assert 'href="#claude-md"' in out

    def test_a_fragment_is_dropped_but_the_document_is_reached(self):
        """Heading anchors are not carried; the viewer addresses documents by slug."""
        out = _render('<a href="DEPLOYMENT_SCALEWAY.md#10b">§10b</a>')
        assert 'href="#docs-deployment-scaleway"' in out

    def test_a_windows_catalogue_path_still_matches(self):
        """`path` is `str(Path)` on the server, which is backslashed on Windows."""
        catalogue = [
            {"slug": "docs-deployment-log", "title": "L", "path": r"C:\src\docs\DEPLOYMENT_LOG.md"},
            {"slug": "docs-deployment-scaleway", "title": "S", "path": r"C:\src\docs\DEPLOYMENT_SCALEWAY.md"},
        ]
        out = _render('<a href="DEPLOYMENT_SCALEWAY.md">plan</a>', catalogue)
        assert 'href="#docs-deployment-scaleway"' in out


class TestLinksThatAreNotCataloguedDocsAreLeftAlone:
    def test_an_uncatalogued_markdown_file_keeps_its_href(self):
        out = _render('<a href="../plugins/README.md">plugins</a>')
        assert 'href="../plugins/README.md"' in out

    def test_an_absolute_url_keeps_its_href(self):
        out = _render('<a href="https://example.com/x.md">ext</a>')
        assert 'href="https://example.com/x.md"' in out

    def test_a_hash_link_keeps_its_href(self):
        out = _render('<a href="#section">here</a>')
        assert 'href="#section"' in out
