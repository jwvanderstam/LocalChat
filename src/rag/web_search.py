"""
Web Search Module
=================

Provides internet search capabilities to enrich RAG context with
primary sources from the web. Uses DuckDuckGo via the duckduckgo-search
library (no API key required).

Classes:
    WebSearchResult: Data class for a single search result.
    WebSearchProvider: Performs web searches and optional page fetching.

Author: LocalChat Team
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from html import unescape
from typing import List, Optional
from urllib.parse import urlparse

import requests

from .. import config
from ..utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class WebSearchResult:
    """A single web search result."""

    title: str
    url: str
    snippet: str
    page_text: Optional[str] = field(default=None, repr=False)


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
        max_results: Optional[int] = None,
        timeout: Optional[int] = None,
        fetch_pages: Optional[bool] = None,
        max_page_chars: Optional[int] = None,
    ) -> None:
        self.max_results = max_results or config.WEB_SEARCH_MAX_RESULTS
        self.timeout = timeout or config.WEB_SEARCH_TIMEOUT
        self.fetch_pages = fetch_pages if fetch_pages is not None else config.WEB_SEARCH_FETCH_PAGES
        self.max_page_chars = max_page_chars or config.WEB_SEARCH_MAX_PAGE_CHARS

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(self, query: str) -> List[WebSearchResult]:
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

    def format_web_context(self, results: List[WebSearchResult], max_length: int = 4000) -> str:
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

        parts: List[str] = []
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

    def _search_duckduckgo(self, query: str) -> List[WebSearchResult]:
        """Search via the duckduckgo-search library."""
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            logger.warning("[WEB SEARCH] duckduckgo-search library not installed")
            return []

        try:
            with DDGS() as ddgs:
                raw = ddgs.text(query, max_results=self.max_results)
        except Exception as exc:
            logger.warning(f"[WEB SEARCH] DuckDuckGo search failed: {exc}")
            return []

        results: List[WebSearchResult] = []
        for item in raw or []:
            title = item.get("title") or ""
            url = item.get("href") or item.get("url") or ""
            snippet = item.get("body") or ""
            if title and url:
                results.append(WebSearchResult(title=title, url=url, snippet=snippet))

        return results

    def _fetch_page_texts(self, results: List[WebSearchResult]) -> None:
        """Fetch and extract plain text from each result URL."""
        for r in results:
            if not self._is_safe_url(r.url):
                logger.warning(f"[WEB SEARCH] Skipping unsafe URL: {r.url!r}")
                continue
            try:
                resp = requests.get(
                    r.url,
                    headers=self._HEADERS,
                    timeout=self.timeout,
                    allow_redirects=True,
                )
                resp.raise_for_status()
                text = self._extract_body_text(resp.text)
                r.page_text = text[: self.max_page_chars] if text else None
            except requests.RequestException as exc:
                logger.debug(f"[WEB SEARCH] Could not fetch {r.url}: {exc}")

    @staticmethod
    def _is_safe_url(url: str) -> bool:
        """Return True only for http/https URLs targeting a non-private hostname.

        Blocks loopback, private IP ranges, link-local addresses, and
        well-known cloud metadata endpoints to prevent SSRF attacks.
        """
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                return False
            hostname = (parsed.hostname or "").lower()
            if not hostname:
                return False
            # Block well-known internal / cloud-metadata hostnames
            _BLOCKED_HOSTS = {
                "localhost", "127.0.0.1", "::1", "0.0.0.0",
                "169.254.169.254",           # AWS / GCP / Azure IMDS
                "metadata.google.internal",
            }
            if hostname in _BLOCKED_HOSTS:
                return False
            # Block IP literals that fall in private / loopback / link-local ranges
            try:
                addr = ipaddress.ip_address(hostname)
                if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                    return False
            except ValueError:
                pass  # hostname is a DNS name, not an IP literal — proceed
            return True
        except Exception:
            return False

    @staticmethod
    def _extract_body_text(html: str) -> str:
        """Best-effort plain-text extraction from an HTML page."""
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return unescape(text)

