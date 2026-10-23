"""GKB-3 in the chat, run under node: choosing the tier, sending it, and citing it.

The selector persists like the RAG and Web toggles, so the next answer comes from the
configuration on screen. A citation from a contribution is tagged, and is never folded
into a workspace document that happens to share its filename.
"""

from __future__ import annotations

import json

import pytest

from tests.utils.js_harness import NODE_MISSING, run_js, run_js_snippet

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(NODE_MISSING, reason="node is not installed"),
]

_KEY = "lc-knowledge-scope"


def _selected(**stored: str) -> str:
    return run_js("chat.js", preload=stored)["values"]["knowledge-scope"]


class TestTheSelector:
    def test_a_stored_choice_is_restored(self):
        assert _selected(**{_KEY: "hybrid"}) == "hybrid"

    def test_a_first_visit_shows_the_workspace_alone(self):
        assert _selected() == "local"

    def test_a_stored_value_this_build_does_not_offer_falls_back_to_local(self):
        assert _selected(**{_KEY: "everything"}) == "local"


def _sent_scope(stored: str) -> str:
    result = run_js(
        "chat.js",
        preload={_KEY: stored},
        fields={"chat-input": "what did other projects learn?"},
        routes=[("/api/chat", {})],
    )
    posts = [c for c in result["calls"] if c["url"] == "/api/chat" and c["method"] == "POST"]
    return json.loads(posts[0]["body"])["knowledge_scope"]


@pytest.mark.parametrize("scope", ["local", "hybrid", "global"])
def test_the_request_carries_the_selected_tier(scope):
    assert _sent_scope(scope) == scope


def _groups(sources: list[dict]) -> list[list]:
    return run_js_snippet(
        "const { groupSources } = await import('./ui.js');\n"
        f"const groups = groupSources({json.dumps(sources)});\n"
        "globalThis.result = [...groups.values()].map("
        "g => [g.filename, g.shared, [...g.pages].sort()]);"
    )


class TestGroupingCitations:
    def test_a_contribution_and_a_workspace_document_with_one_name_stay_apart(self):
        assert _groups([
            {"filename": "retro.md", "knowledge_tier": "local", "page_number": 1},
            {"filename": "retro.md", "knowledge_tier": "global", "page_number": 2},
        ]) == [["retro.md", False, [1]], ["retro.md", True, [2]]]

    def test_chunks_of_one_document_still_merge_into_one_citation(self):
        assert _groups([
            {"filename": "plan.pdf", "knowledge_tier": "global", "page_number": 3},
            {"filename": "plan.pdf", "knowledge_tier": "global", "page_number": 1},
        ]) == [["plan.pdf", True, [1, 3]]]

    def test_a_source_without_a_tier_is_this_workspaces(self):
        """Web sources and older servers send none; neither is a contribution."""
        assert _groups([{"filename": "notes.md"}]) == [["notes.md", False, []]]
