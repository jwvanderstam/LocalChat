"""
Tool Router
===========

Maps logical tool names (from QueryPlan.tools) to concrete handler
callables.  Each handler returns a normalised result dict:

    {"context": str, "sources": list[dict]}

When MCP_ENABLED=true every handler first tries its corresponding MCP
server and silently falls back to a direct Python import on failure.
When MCP_ENABLED=false (default) the MCP path is skipped entirely.
"""

from __future__ import annotations

from ..utils.logging_config import get_logger

logger = get_logger(__name__)

# Canonical tool name constants — shared across planner, agent, and MCP servers.
TOOL_LOCAL_DOCS = "local_docs"
TOOL_WEB_SEARCH = "web_search"
TOOL_CLOUD_CONNECTORS = "cloud_connectors"

ALL_TOOLS: frozenset[str] = frozenset({
    TOOL_LOCAL_DOCS,
    TOOL_WEB_SEARCH,
    TOOL_CLOUD_CONNECTORS,
})


class ToolRouter:
    """
    Routes logical tool names to MCP servers or direct Python handlers.

    All methods are synchronous and thread-safe (no shared mutable state).
    """

    def dispatch(
        self,
        tool_name: str,
        query: str,
        filters: dict | None = None,
        top_k: int = 10,
    ) -> dict:
        """
        Invoke the named tool and return a normalised result.

        Args:
            tool_name: One of the TOOL_* constants.
            query:     Search query string.
            filters:   Optional dict — e.g. {"filenames": ["report.pdf"]}.
            top_k:     Maximum number of chunks / results to return.

        Returns:
            dict with keys "context" (str) and "sources" (list[dict]).

        Raises:
            ValueError: tool_name is not recognised.
            RuntimeError: Tool call failed and no fallback succeeded.
        """
        if tool_name == TOOL_LOCAL_DOCS:
            return self._local_docs(query, filters, top_k)
        if tool_name == TOOL_WEB_SEARCH:
            return self._web_search(query)
        if tool_name == TOOL_CLOUD_CONNECTORS:
            return self._cloud_connectors(query, filters, top_k)
        raise ValueError(f"Unknown tool: {tool_name!r}")

    # ------------------------------------------------------------------
    # Per-tool handlers
    # ------------------------------------------------------------------

    def _local_docs(self, query: str, filters: dict | None, top_k: int) -> dict:
        from .. import config  # local import avoids circular dependency at module load

        if config.MCP_ENABLED:
            try:
                from ..mcp_client import mcp_registry
                result = mcp_registry.local_docs.call_tool("search", {
                    "query": query,
                    "filters": filters or {},
                    "top_k": top_k,
                })
                if isinstance(result, dict) and "context" in result:
                    return {"context": result["context"], "sources": result.get("sources") or []}
                logger.warning("[ToolRouter] local_docs MCP returned unexpected shape — falling back")
            except Exception as exc:
                logger.warning(f"[ToolRouter] local_docs MCP failed — falling back to direct: {exc}")

        # Direct path (default when MCP disabled, or MCP fallback)
        from ..rag.processor import doc_processor
        filename_filter = (filters or {}).get("filenames") or []
        results = doc_processor.retrieve_context(query, filename_filter=filename_filter)
        results = results[:top_k]
        if not results:
            return {"context": "", "sources": []}
        context = doc_processor.format_context_for_llm(results, max_length=config.MAX_CONTEXT_LENGTH)
        sources = [
            {
                "filename": r[1],
                "chunk_index": r[2],
                "similarity": round(float(r[3]), 4),
                "page_number": r[4].get("page_number"),
                "section_title": r[4].get("section_title"),
                "chunk_id": r[5] if len(r) > 5 else None,
            }
            for r in results
        ]
        return {"context": context, "sources": sources}

    def _web_search(self, query: str) -> dict:
        from .. import config

        if config.MCP_ENABLED:
            try:
                from ..mcp_client import mcp_registry
                result = mcp_registry.web_search.call_tool("search", {"query": query})
                if isinstance(result, dict):
                    return {"context": result.get("context") or "", "sources": []}
                logger.warning("[ToolRouter] web_search MCP returned unexpected shape — falling back")
            except Exception as exc:
                logger.warning(f"[ToolRouter] web_search MCP failed — falling back to direct: {exc}")

        # Direct path
        from ..rag.web_search import WebSearchProvider
        searcher = WebSearchProvider()
        web_results = searcher.search(query)
        return {
            "context": searcher.format_web_context(web_results, max_length=4000),
            "sources": [],
        }

    def _cloud_connectors(self, query: str, filters: dict | None, top_k: int) -> dict:
        from .. import config

        if config.MCP_ENABLED:
            try:
                from ..mcp_client import mcp_registry
                result = mcp_registry.cloud_connectors.call_tool("search", {
                    "query": query,
                    "filters": filters or {},
                    "top_k": top_k,
                })
                if isinstance(result, dict):
                    return {
                        "context": result.get("context") or "",
                        "sources": result.get("sources") or [],
                    }
            except Exception as exc:
                logger.warning(f"[ToolRouter] cloud_connectors MCP failed: {exc}")

        # No direct path — cloud connectors route through the MCP server
        return {"context": "", "sources": []}
