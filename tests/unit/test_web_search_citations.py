"""
BUG-2 regression suite — web-search results must reach the citation list.

Before the fix, `get_web_context()` returned only a formatted text blob: the
title/url/snippet that `WebSearchProvider.search()` produced were discarded, and
`retrieve_contexts()` built `sources` solely from local documents. The answer was
genuinely grounded in fetched web content, but nothing attributed it.

The same omission existed independently in the aggregator path
(`ToolRouter._web_search` returned `"sources": []` on both branches), so both are
covered here — fixing only one leaves the bug reachable by flipping
AGGREGATOR_AGENT_ENABLED.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class _Result:
    def __init__(self, title, url, snippet="snip"):
        self.title = title
        self.url = url
        self.snippet = snippet


# ---------------------------------------------------------------------------
# The shared shape
# ---------------------------------------------------------------------------

class TestToSourceDict:
    def test_title_becomes_the_grouping_key(self):
        from src.rag.web_search import to_source_dict

        assert to_source_dict("A Page", "https://e.com")["filename"] == "A Page"

    def test_url_is_preserved(self):
        from src.rag.web_search import to_source_dict

        assert to_source_dict("A Page", "https://e.com")["url"] == "https://e.com"

    def test_url_is_the_fallback_label_when_title_is_empty(self):
        from src.rag.web_search import to_source_dict

        assert to_source_dict("", "https://e.com")["filename"] == "https://e.com"

    def test_chunk_id_is_null_so_no_chunk_link_is_offered(self):
        from src.rag.web_search import to_source_dict

        assert to_source_dict("A", "https://e.com")["chunk_id"] is None

    def test_carries_the_document_source_keys(self):
        from src.rag.web_search import to_source_dict

        assert set(to_source_dict("A", "https://e.com")) == {
            "filename", "url", "chunk_index", "page_number", "section_title", "chunk_id",
        }


# ---------------------------------------------------------------------------
# Direct path
# ---------------------------------------------------------------------------

class TestGetWebContextReturnsSources:
    def test_returns_one_source_per_result(self, monkeypatch):
        from src.services import chat

        monkeypatch.setattr(chat.config, "MCP_ENABLED", False)
        provider = MagicMock()
        provider.search.return_value = [
            _Result("First", "https://a.example"),
            _Result("Second", "https://b.example"),
        ]
        provider.format_web_context.return_value = "ctx"
        monkeypatch.setattr(
            "src.rag.web_search.WebSearchProvider", MagicMock(return_value=provider)
        )

        context, sources = chat.get_web_context("q")
        assert context == "ctx"
        assert [s["filename"] for s in sources] == ["First", "Second"]
        assert [s["url"] for s in sources] == ["https://a.example", "https://b.example"]

    def test_results_without_a_url_are_dropped(self, monkeypatch):
        from src.services import chat

        monkeypatch.setattr(chat.config, "MCP_ENABLED", False)
        provider = MagicMock()
        provider.search.return_value = [_Result("Good", "https://a.example"), _Result("Bad", "")]
        provider.format_web_context.return_value = "ctx"
        monkeypatch.setattr(
            "src.rag.web_search.WebSearchProvider", MagicMock(return_value=provider)
        )

        _, sources = chat.get_web_context("q")
        assert [s["filename"] for s in sources] == ["Good"]

    def test_no_results_yields_no_sources(self, monkeypatch):
        from src.services import chat

        monkeypatch.setattr(chat.config, "MCP_ENABLED", False)
        provider = MagicMock()
        provider.search.return_value = []
        monkeypatch.setattr(
            "src.rag.web_search.WebSearchProvider", MagicMock(return_value=provider)
        )

        assert chat.get_web_context("q") == ("", [])


class TestGetWebContextMcpPath:
    """The MCP branch parses a different payload and had no coverage at all."""

    def test_mcp_results_become_sources(self, monkeypatch):
        from src.services import chat

        monkeypatch.setattr(chat.config, "MCP_ENABLED", True)
        registry = MagicMock()
        registry.web_search.call_tool.return_value = {
            "context": "mcp ctx",
            "results": [
                {"title": "MCP One", "url": "https://m1.example", "snippet": "s"},
                {"title": "MCP Two", "url": "https://m2.example", "snippet": "s"},
            ],
        }
        monkeypatch.setattr("src.mcp_client.mcp_registry", registry)

        context, sources = chat.get_web_context("q")
        assert context == "mcp ctx"
        assert [s["filename"] for s in sources] == ["MCP One", "MCP Two"]
        assert [s["url"] for s in sources] == ["https://m1.example", "https://m2.example"]

    def test_mcp_result_without_a_url_is_dropped(self, monkeypatch):
        from src.services import chat

        monkeypatch.setattr(chat.config, "MCP_ENABLED", True)
        registry = MagicMock()
        registry.web_search.call_tool.return_value = {
            "context": "mcp ctx",
            "results": [
                {"title": "Good", "url": "https://m1.example"},
                {"title": "No URL", "url": ""},
            ],
        }
        monkeypatch.setattr("src.mcp_client.mcp_registry", registry)

        _, sources = chat.get_web_context("q")
        assert [s["filename"] for s in sources] == ["Good"]

    def test_mcp_missing_results_key_yields_context_without_sources(self, monkeypatch):
        from src.services import chat

        monkeypatch.setattr(chat.config, "MCP_ENABLED", True)
        registry = MagicMock()
        registry.web_search.call_tool.return_value = {"context": "mcp ctx"}
        monkeypatch.setattr("src.mcp_client.mcp_registry", registry)

        assert chat.get_web_context("q") == ("mcp ctx", [])

    def test_mcp_empty_context_returns_nothing(self, monkeypatch):
        from src.services import chat

        monkeypatch.setattr(chat.config, "MCP_ENABLED", True)
        registry = MagicMock()
        registry.web_search.call_tool.return_value = {"context": "", "results": []}
        monkeypatch.setattr("src.mcp_client.mcp_registry", registry)

        assert chat.get_web_context("q") == ("", [])

    def test_mcp_failure_falls_back_to_the_direct_provider(self, monkeypatch):
        from src.services import chat

        monkeypatch.setattr(chat.config, "MCP_ENABLED", True)
        registry = MagicMock()
        registry.web_search.call_tool.side_effect = RuntimeError("mcp down")
        monkeypatch.setattr("src.mcp_client.mcp_registry", registry)

        provider = MagicMock()
        provider.search.return_value = [_Result("Fallback", "https://f.example")]
        provider.format_web_context.return_value = "direct ctx"
        monkeypatch.setattr(
            "src.rag.web_search.WebSearchProvider", MagicMock(return_value=provider)
        )

        context, sources = chat.get_web_context("q")
        assert context == "direct ctx"
        assert [s["filename"] for s in sources] == ["Fallback"]


# ---------------------------------------------------------------------------
# retrieve_contexts — where the bug was actually visible
# ---------------------------------------------------------------------------

class TestRetrieveContextsAppendsWebSources:
    def test_web_sources_appear_alongside_document_sources(self, monkeypatch):
        from src.services import chat

        monkeypatch.setattr(chat.config, "AGGREGATOR_AGENT_ENABLED", False)
        monkeypatch.setattr(
            chat, "get_rag_context",
            lambda *a, **k: ("local ctx", [{"filename": "doc.pdf", "chunk_id": 7}]),
        )
        monkeypatch.setattr(chat, "get_filename_filter", lambda *a, **k: [])
        monkeypatch.setattr(
            chat, "get_web_context",
            lambda *a, **k: ("web ctx", [{"filename": "Page", "url": "https://e.com", "chunk_id": None}]),
        )

        fields = {"message": "q", "use_rag": True, "enhance": True}
        local_ctx, web_ctx, sources, _ = chat.retrieve_contexts(
            fields, MagicMock(), MagicMock(), [0]
        )

        assert local_ctx == "local ctx"
        assert web_ctx == "web ctx"
        assert [s["filename"] for s in sources] == ["doc.pdf", "Page"]

    def test_enhance_off_produces_no_web_sources(self, monkeypatch):
        from src.services import chat

        monkeypatch.setattr(chat.config, "AGGREGATOR_AGENT_ENABLED", False)
        monkeypatch.setattr(
            chat, "get_rag_context",
            lambda *a, **k: ("local ctx", [{"filename": "doc.pdf", "chunk_id": 7}]),
        )
        monkeypatch.setattr(chat, "get_filename_filter", lambda *a, **k: [])

        fields = {"message": "q", "use_rag": True, "enhance": False}
        _, web_ctx, sources, _ = chat.retrieve_contexts(fields, MagicMock(), MagicMock(), [0])

        assert web_ctx == ""
        assert [s["filename"] for s in sources] == ["doc.pdf"]

    def test_web_search_failure_leaves_document_sources_intact(self, monkeypatch):
        from src.services import chat

        monkeypatch.setattr(chat.config, "AGGREGATOR_AGENT_ENABLED", False)
        monkeypatch.setattr(
            chat, "get_rag_context",
            lambda *a, **k: ("local ctx", [{"filename": "doc.pdf", "chunk_id": 7}]),
        )
        monkeypatch.setattr(chat, "get_filename_filter", lambda *a, **k: [])

        def _boom(*a, **k):
            raise RuntimeError("network down")

        monkeypatch.setattr(chat, "get_web_context", _boom)

        fields = {"message": "q", "use_rag": True, "enhance": True}
        _, web_ctx, sources, _ = chat.retrieve_contexts(fields, MagicMock(), MagicMock(), [0])

        assert web_ctx == ""
        assert [s["filename"] for s in sources] == ["doc.pdf"]


# ---------------------------------------------------------------------------
# Aggregator path — the second, independent instance
# ---------------------------------------------------------------------------

class TestToolRouterWebSearchReturnsSources:
    def test_direct_path_returns_sources(self, monkeypatch):
        from src.agent.tool_router import ToolRouter

        monkeypatch.setattr("src.config.MCP_ENABLED", False)
        provider = MagicMock()
        provider.search.return_value = [_Result("First", "https://a.example")]
        provider.format_web_context.return_value = "ctx"
        monkeypatch.setattr(
            "src.rag.web_search.WebSearchProvider", MagicMock(return_value=provider)
        )

        out = ToolRouter()._web_search("q")
        assert out["context"] == "ctx"
        assert [s["url"] for s in out["sources"]] == ["https://a.example"]

    def test_mcp_path_returns_sources(self, monkeypatch):
        from src.agent.tool_router import ToolRouter

        monkeypatch.setattr("src.config.MCP_ENABLED", True)
        registry = MagicMock()
        registry.web_search.call_tool.return_value = {
            "context": "ctx",
            "results": [{"title": "MCP Page", "url": "https://m.example", "snippet": "s"}],
        }
        monkeypatch.setattr("src.mcp_client.mcp_registry", registry)

        out = ToolRouter()._web_search("q")
        assert out["context"] == "ctx"
        assert [s["filename"] for s in out["sources"]] == ["MCP Page"]


@pytest.mark.parametrize("chunk_id,expected", [(None, True), (5, False)])
def test_only_web_sources_survive_dedup_unkeyed(chunk_id, expected):
    """Aggregator dedup keys on chunk_id; web entries must land in the unkeyed bucket."""
    from src.agent.aggregator import AggregatorAgent

    src = {"filename": "X", "chunk_id": chunk_id, "similarity": 0.5}
    out = AggregatorAgent._dedup_sources([src, src])
    # Unkeyed (web) entries are preserved as-is, so duplicates both survive.
    assert (len(out) == 2) is expected
