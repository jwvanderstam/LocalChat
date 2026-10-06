"""GR-1c — the Documents page shows which documents were flagged at ingest.

Runs the real `static/js/ingestion.js` under node. A flag nobody sees is the failure this
ticket exists to avoid: the scan's whole output is this badge and a log line.
"""

from __future__ import annotations

import pytest

from tests.utils.js_harness import NODE_MISSING, run_js

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(NODE_MISSING, reason="node is not installed"),
]


def _documents_html(*documents: dict) -> str:
    result = run_js(
        "ingestion.js",
        routes=[
            ("/api/documents/list", {"success": True, "documents": list(documents)}),
            ("/api/documents/stats", {"success": True}),
        ],
    )
    return result["html"]["documents-list"]


def _doc(filename: str, flags: list[str] | None) -> dict:
    doc = {"id": 1, "filename": filename, "created_at": "2026-10-05T10:00:00", "chunk_count": 3}
    if flags is not None:
        doc["injection_flags"] = flags
    return doc


def test_a_flagged_document_carries_the_badge_and_names_what_was_found():
    html = _documents_html(_doc("evil.pdf", ["override-instructions", "role-marker"]))

    assert html.count("data-injection-flags") == 1
    assert "override-instructions, role-marker" in html


@pytest.mark.parametrize("flags", [[], None])
def test_an_unflagged_document_has_none(flags):
    """None is a document ingested before the scan existed."""
    assert "data-injection-flags" not in _documents_html(_doc("clean.pdf", flags))


def test_only_the_flagged_one_of_two_is_marked():
    html = _documents_html(_doc("clean.pdf", []), _doc("evil.pdf", ["chat-template"]))

    assert html.count("data-injection-flags") == 1
    assert html.index("evil.pdf") < html.index("data-injection-flags")
    assert html.index("clean.pdf") < html.index("evil.pdf")


def test_a_flag_value_is_escaped_into_its_attribute():
    """The kinds are the server's own names, but the attribute is escaped regardless."""
    html = _documents_html(_doc("x.pdf", ['a" onmouseover="alert(1)']))

    assert 'onmouseover="alert' not in html
    assert "a&quot; onmouseover=&quot;alert(1)" in html
