"""
Cloud Connectors MCP Server
============================

Independently deployable MCP server for cloud and local document sources.

Exposes tools:
  - search(query, filters, top_k) — searches all enabled connectors' documents
  - list_sources()                 — lists registered connectors and their status

Run standalone:
    python -m mcp_servers.cloud_connectors [--port 5003]

Run via gunicorn:
    gunicorn "mcp_servers.cloud_connectors.server:flask_app" --bind 0.0.0.0:5003
"""

import argparse
import logging

from ..base import MCPServer

logger = logging.getLogger(__name__)

_server = MCPServer("cloud-connectors")


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def search(query: str, filters: dict | None = None, top_k: int = 10) -> dict:
    """Search documents from all enabled connectors via the core retrieval pipeline."""
    try:
        from src.db import db
        from src.rag import doc_processor
        results = doc_processor.retrieve_context(query, top_k=top_k)
        if not results:
            return {"context": "", "sources": []}
        context = doc_processor.format_context_for_llm(results, max_length=6000)
        sources = [
            {"filename": r[1], "chunk_index": r[2], "similarity": round(r[3], 4)}
            for r in results
        ]
        return {"context": context, "sources": sources}
    except Exception as exc:
        logger.warning(f"[cloud-connectors] search error: {exc}")
        return {"context": "", "sources": [], "error": str(exc)}


def list_sources() -> list[dict]:
    """Return all configured connectors from the database."""
    try:
        from src.db import db
        return db.list_connectors() if db.is_connected else []
    except Exception as exc:
        logger.warning(f"[cloud-connectors] list_sources error: {exc}")
        return []


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

_server.register_tool(
    name="search",
    description="Search cloud document sources (SharePoint, OneDrive, S3, Confluence)",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "filters": {"type": "object"},
            "top_k": {"type": "integer", "default": 10},
        },
        "required": ["query"],
    },
    handler=search,
)

_server.register_tool(
    name="list_sources",
    description="List registered cloud connectors and their status",
    input_schema={"type": "object", "properties": {}},
    handler=list_sources,
)

flask_app = _server.get_wsgi_app()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _main() -> None:
    parser = argparse.ArgumentParser(description="LocalChat cloud-connectors MCP server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5003)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    _server.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    _main()
