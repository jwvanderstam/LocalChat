"""
Web Search Module
=================

Provides internet search capabilities to enrich RAG context with
primary sources from the web. Uses DuckDuckGo via the duckduckgo-search
library (no API key required).

Classes:
    WebSearchResult: Data class for a single search result.
    WebSearchProvider: Performs web searches and optional page fetching.

"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import unescape

import requests

from .. import config
from ..utils.logging_config import get_logger
from ..utils.safe_fetch import UnsafeUrlError, safe_fetch

logger = get_logger(__name__)

#: A search result is a page of text. Bounded so a hostile or broken result cannot
#: hold the fetch open or grow without limit — there was no cap at all (audit M4).
_MAX_PAGE_BYTES = 2 * 1024 * 1024


@dataclass
class WebSearchResult:
    """A single web search result."""

    title: str
    url: str
    snippet: str
    page_text: str | None = field(default=None, repr=False)


def to_source_dict(title: str, url: str) -> dict:
    """Shape a web result like a document source so one renderer handles both.

    The document keys are present but null: `filename` is the grouping key the
    citation panel uses, and a null `chunk_id` stops it offering a chunk-context
    link, which only exists for ingested documents.
    """
    return {
        "filename": title or url,
        "url": url,
        "chunk_index": None,
        "page_number": None,
        "section_title": None,
        "chunk_id": None,
    }


class WebSearchProvider:
    """
    Performs web searches via DuckDuckGo and optionally fetches page content
    for deeper context enrichment.
    """

    _HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }

    def __init__(
        self,
        max_results: int | None = None,
        timeout: int | None = None,
        fetch_pages: bool | None = None,
        max_page_chars: int | None = None,
    ) -> None:
        self.max_results = max_results or config.WEB_SEARCH_MAX_RESULTS
        self.timeout = timeout or config.WEB_SEARCH_TIMEOUT
        self.fetch_pages = fetch_pages if fetch_pages is not None else config.WEB_SEARCH_FETCH_PAGES
        self.max_page_chars = max_page_chars or config.WEB_SEARCH_MAX_PAGE_CHARS

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(self, query: str) -> list[WebSearchResult]:
        """
        Search the web for *query* and return a list of results.

        Args:
            query: The search query string.

        Returns:
            List of ``WebSearchResult`` objects (may be empty on failure).
        """
        logger.info(f"[WEB SEARCH] Searching: {query!r}")
        results = self._search_duckduckgo(query)
        logger.info(f"[WEB SEARCH] Got {len(results)} result(s)")

        if self.fetch_pages and results:
            self._fetch_page_texts(results)

        return results

    def format_web_context(self, results: list[WebSearchResult], max_length: int = 4000) -> str:
        """
        Format search results into a context block for the LLM.

        Args:
            results: List of ``WebSearchResult`` objects.
            max_length: Maximum character length for the combined context.

        Returns:
            Formatted string suitable for inclusion in an LLM prompt.
        """
        if not results:
            return ""

        parts: list[str] = []
        current_length = 0

        for idx, r in enumerate(results, 1):
            body = r.page_text or r.snippet
            entry = f"[Web Source {idx}] {r.title}\nURL: {r.url}\n{body}\n"
            if current_length + len(entry) > max_length:
                remaining = max_length - current_length
                if remaining > 100:
                    parts.append(entry[:remaining] + "...")
                break
            parts.append(entry)
            current_length += len(entry)

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _search_duckduckgo(self, query: str) -> list[WebSearchResult]:
        """Search via the duckduckgo-search library."""
        try:
            from ddgs import DDGS
        except ImportError:
            try:
                from duckduckgo_search import DDGS  # type: ignore[no-redef]
            except ImportError:
                logger.warning("[WEB SEARCH] Neither 'ddgs' nor 'duckduckgo_search' is installed. "
                               "Run: pip install ddgs")
                return []

        try:
            with DDGS() as ddgs:
                raw = ddgs.text(query, max_results=self.max_results)
        except Exception as exc:  # noqa: BLE001 — a third-party search client over the network; no results is a valid outcome
            logger.warning(f"[WEB SEARCH] DuckDuckGo search failed: {exc}")
            return []

        results: list[WebSearchResult] = []
        for item in raw or []:
            title = item.get("title") or ""
            url = item.get("href") or item.get("url") or ""
            snippet = item.get("body") or ""
            if title and url:
                results.append(WebSearchResult(title=title, url=url, snippet=snippet))

        return results

    def _fetch_page_texts(self, results: list[WebSearchResult]) -> None:
        """Fetch and extract plain text from each result URL."""
        session = requests.Session()
        session.max_redirects = 5
        session.headers.update(self._HEADERS)
        for r in results:
            try:
                # safe_fetch resolves each hostname and refuses any address that is
                # not publicly routable, re-validating every redirect. The check it
                # replaces inspected the hostname string and let DNS names straight
                # through, so a name pointing at 10.0.0.5 was fetched (audit M4).
                fetched = safe_fetch(
                    r.url,
                    timeout=self.timeout,
                    max_bytes=_MAX_PAGE_BYTES,
                    session=session,
                )
            except UnsafeUrlError as exc:
                logger.warning("[WEB SEARCH] Refused a search result: %s", exc)
                continue
            except requests.RequestException as exc:
                logger.debug(f"[WEB SEARCH] Could not fetch {r.url}: {exc}")
                continue

            if not fetched.content_type.startswith("text/"):
                logger.debug(
                    "[WEB SEARCH] Skipping non-text response: %r", fetched.content_type
                )
                continue
            text = self._extract_body_text(fetched.text)
            r.page_text = text[: self.max_page_chars] if text else None

    @staticmethod
    def _extract_body_text(html: str) -> str:
        """Best-effort plain-text extraction from an HTML page."""
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return unescape(text)

