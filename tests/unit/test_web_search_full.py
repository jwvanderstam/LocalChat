# -*- coding: utf-8 -*-
"""Tests for WebSearchProvider."""

import pytest
from unittest.mock import MagicMock, patch


class TestWebSearchResult:
    def test_dataclass_fields(self):
        from src.rag.web_search import WebSearchResult
        r = WebSearchResult(title="T", url="http://x.com", snippet="S")
        assert r.title == "T"
        assert r.url == "http://x.com"
        assert r.snippet == "S"
        assert r.page_text is None

    def test_page_text_can_be_set(self):
        from src.rag.web_search import WebSearchResult
        r = WebSearchResult(title="T", url="u", snippet="s", page_text="full text")
        assert r.page_text == "full text"


class TestWebSearchProviderInit:
    def test_default_init(self):
        from src.rag.web_search import WebSearchProvider
        provider = WebSearchProvider()
        assert provider.max_results > 0
        assert provider.timeout > 0

    def test_custom_params(self):
        from src.rag.web_search import WebSearchProvider
        p = WebSearchProvider(max_results=3, timeout=5, fetch_pages=False, max_page_chars=1000)
        assert p.max_results == 3
        assert p.timeout == 5
        assert p.fetch_pages is False
        assert p.max_page_chars == 1000


class TestWebSearchProviderSearch:
    def test_search_returns_results_when_ddg_works(self):
        from src.rag.web_search import WebSearchProvider, WebSearchResult

        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text.return_value = [
            {"title": "Result 1", "href": "http://a.com", "body": "Snippet A"},
            {"title": "Result 2", "href": "http://b.com", "body": "Snippet B"},
        ]

        with patch("src.rag.web_search.WebSearchProvider._search_duckduckgo",
                   return_value=[
                       WebSearchResult("Result 1", "http://a.com", "Snippet A"),
                       WebSearchResult("Result 2", "http://b.com", "Snippet B"),
                   ]):
            provider = WebSearchProvider(fetch_pages=False)
            results = provider.search("test query")

        assert len(results) == 2
        assert results[0].title == "Result 1"

    def test_search_returns_empty_on_ddg_library_missing(self):
        from src.rag.web_search import WebSearchProvider

        with patch("src.rag.web_search.WebSearchProvider._search_duckduckgo", return_value=[]):
            provider = WebSearchProvider(fetch_pages=False)
            results = provider.search("test")

        assert results == []

    def test_search_fetches_pages_when_enabled(self):
        from src.rag.web_search import WebSearchProvider, WebSearchResult

        result = WebSearchResult("T", "http://x.com", "S")
        with patch.object(WebSearchProvider, "_search_duckduckgo", return_value=[result]), \
             patch.object(WebSearchProvider, "_fetch_page_texts") as mock_fetch:
            provider = WebSearchProvider(fetch_pages=True)
            provider.search("query")
            mock_fetch.assert_called_once()

    def test_search_does_not_fetch_when_disabled(self):
        from src.rag.web_search import WebSearchProvider, WebSearchResult

        result = WebSearchResult("T", "http://x.com", "S")
        with patch.object(WebSearchProvider, "_search_duckduckgo", return_value=[result]), \
             patch.object(WebSearchProvider, "_fetch_page_texts") as mock_fetch:
            provider = WebSearchProvider(fetch_pages=False)
            provider.search("query")
            mock_fetch.assert_not_called()

    def test_search_empty_results_skips_fetch(self):
        from src.rag.web_search import WebSearchProvider

        with patch.object(WebSearchProvider, "_search_duckduckgo", return_value=[]), \
             patch.object(WebSearchProvider, "_fetch_page_texts") as mock_fetch:
            provider = WebSearchProvider(fetch_pages=True)
            provider.search("query")
            mock_fetch.assert_not_called()


class TestWebSearchDuckDuckGo:
    def test_duckduckgo_missing_library_returns_empty(self):
        from src.rag.web_search import WebSearchProvider

        with patch.dict("sys.modules", {"duckduckgo_search": None}):
            provider = WebSearchProvider()
            results = provider._search_duckduckgo("test")
            assert results == []

    def test_duckduckgo_exception_returns_empty(self):
        from src.rag.web_search import WebSearchProvider

        mock_ddgs_cls = MagicMock()
        mock_ddgs_cls.return_value.__enter__.side_effect = Exception("network error")

        mock_module = MagicMock()
        mock_module.DDGS = mock_ddgs_cls

        with patch.dict("sys.modules", {"duckduckgo_search": mock_module}):
            provider = WebSearchProvider()
            results = provider._search_duckduckgo("test")
            assert results == []

    def test_duckduckgo_filters_items_without_title_or_url(self):
        from src.rag.web_search import WebSearchProvider

        mock_ddgs_cls = MagicMock()
        ctx = MagicMock()
        mock_ddgs_cls.return_value.__enter__.return_value = ctx
        mock_ddgs_cls.return_value.__exit__.return_value = False
        ctx.text.return_value = [
            {"title": "", "href": "http://x.com", "body": "S"},   # no title → skipped
            {"title": "Good", "href": "", "body": "S"},             # no url → skipped
            {"title": "Good", "href": "http://y.com", "body": "S"}, # OK
        ]

        mock_module = MagicMock()
        mock_module.DDGS = mock_ddgs_cls

        with patch.dict("sys.modules", {"duckduckgo_search": mock_module}):
            provider = WebSearchProvider()
            results = provider._search_duckduckgo("test")
            assert len(results) == 1
            assert results[0].url == "http://y.com"


class TestWebSearchFetchPages:
    def test_fetch_page_texts_sets_page_text(self):
        import requests as req_mod
        from src.rag.web_search import WebSearchProvider, WebSearchResult

        result = WebSearchResult("T", "http://x.com", "S")

        mock_response = MagicMock()
        mock_response.text = "<html><body><p>Hello world</p></body></html>"
        mock_response.raise_for_status = MagicMock()

        with patch("src.rag.web_search.requests.get", return_value=mock_response):
            provider = WebSearchProvider(max_page_chars=500)
            provider._fetch_page_texts([result])

        assert result.page_text is not None
        assert "Hello" in result.page_text

    def test_fetch_page_request_error_leaves_page_text_none(self):
        import requests as req_mod
        from src.rag.web_search import WebSearchProvider, WebSearchResult

        result = WebSearchResult("T", "http://x.com", "S")

        with patch("src.rag.web_search.requests.get",
                   side_effect=req_mod.RequestException("timeout")):
            provider = WebSearchProvider()
            provider._fetch_page_texts([result])

        assert result.page_text is None


class TestWebSearchExtractBodyText:
    def test_strips_html_tags(self):
        from src.rag.web_search import WebSearchProvider
        text = WebSearchProvider._extract_body_text("<p>Hello <b>world</b></p>")
        assert "Hello" in text
        assert "<" not in text

    def test_removes_script_tags(self):
        from src.rag.web_search import WebSearchProvider
        text = WebSearchProvider._extract_body_text(
            "<script>alert('xss')</script><p>Content</p>"
        )
        assert "alert" not in text
        assert "Content" in text

    def test_removes_style_tags(self):
        from src.rag.web_search import WebSearchProvider
        text = WebSearchProvider._extract_body_text(
            "<style>.x{color:red}</style><p>Text</p>"
        )
        assert "color" not in text
        assert "Text" in text

    def test_unescapes_html_entities(self):
        from src.rag.web_search import WebSearchProvider
        text = WebSearchProvider._extract_body_text("<p>AT&amp;T &lt;rocks&gt;</p>")
        assert "AT&T" in text


class TestFormatWebContext:
    def test_format_empty_results(self):
        from src.rag.web_search import WebSearchProvider
        result = WebSearchProvider().format_web_context([])
        assert result == ""

    def test_format_basic_results(self):
        from src.rag.web_search import WebSearchProvider, WebSearchResult

        results = [WebSearchResult("Title A", "http://a.com", "Snippet A")]
        output = WebSearchProvider().format_web_context(results)
        assert "Title A" in output
        assert "URL: http://a.com" in output

    def test_respects_max_length(self):
        from src.rag.web_search import WebSearchProvider, WebSearchResult

        results = [WebSearchResult("T" * 50, "http://a.com", "S" * 100)] * 10
        output = WebSearchProvider().format_web_context(results, max_length=300)
        assert len(output) <= 350  # allow slight overrun from truncation logic

    def test_uses_page_text_over_snippet(self):
        from src.rag.web_search import WebSearchProvider, WebSearchResult

        r = WebSearchResult("T", "http://a.com", "fallback snippet", page_text="full page text")
        output = WebSearchProvider().format_web_context([r])
        assert "full page text" in output
