"""
Web Search MCP Server
=====================

Independently deployable MCP server that wraps the LocalChat DuckDuckGo
web search provider.  The core app communicates with this server via
JSON-RPC 2.0 over HTTP when MCP_ENABLED=true.

Exposes tools:
  - search(query, max_results) — web search with optional page fetching
  - list_sources()              — lists configured search providers

Run standalone:
    python -m mcp_servers.web_search [--port 5002]

Run via gunicorn:
    gunicorn "mcp_servers.web_search.server:flask_app" --bind 0.0.0.0:5002
"""

import argparse
import logging

from ..base import MCPServer

logger = logging.getLogger(__name__)

_server = MCPServer("web-search")


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def search(query: str, max_results: int | None = None) -> dict:
    """
    Search the web and return a pre-formatted context block.

    Brave Search is used as the primary provider when available; falls back
    to DuckDuckGo automatically (both are handled by WebSearchProvider).
    """
    from src.rag.web_search import WebSearchProvider  # noqa: PLC0415

    provider = WebSearchProvider(max_results=max_results)
    results = provider.search(query)
    logger.info(f"[web-search] search '{query[:60]}' → {len(results)} results")
    context = provider.format_web_context(results, max_length=4000)
    return {
        "context": context,
        "result_count": len(results),
        "results": [
            {"title": r.title, "url": r.url, "snippet": r.snippet}
            for r in results
        ],
    }


def list_sources() -> list[dict]:
    """Return the configured web search providers."""
    return [
        {
            "name": "DuckDuckGo",
            "type": "web_search",
            "status": "active",
            "requires_api_key": False,
        }
    ]


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

_server.register_tool(
    name="search",
    description="Search the web via DuckDuckGo and return formatted context",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results (default: from config)",
            },
        },
        "required": ["query"],
    },
    handler=search,
)

_server.register_tool(
    name="list_sources",
    description="List configured web search providers",
    input_schema={"type": "object", "properties": {}},
    handler=list_sources,
)

flask_app = _server.get_wsgi_app()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _main() -> None:
    parser = argparse.ArgumentParser(description="LocalChat web-search MCP server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5002)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    _server.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    _main()
