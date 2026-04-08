"""
Local Documents MCP Server
==========================

Independently deployable MCP server that wraps the LocalChat pgvector
retrieval pipeline.  The core app communicates with this server via
JSON-RPC 2.0 over HTTP when MCP_ENABLED=true.

Exposes tools:
  - search(query, filters, top_k) — hybrid semantic + BM25 retrieval
  - list_sources()                 — list all ingested documents

Run standalone:
    python -m mcp_servers.local_docs [--port 5001]

Run via gunicorn:
    gunicorn "mcp_servers.local_docs.server:flask_app" --bind 0.0.0.0:5001
"""

import argparse
import logging

from ..base import MCPServer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy-initialize heavy services so the module can be imported without
# side-effects during testing.
# ---------------------------------------------------------------------------

_server = MCPServer("local-docs")


def _get_services():
    """Import and return (doc_processor, db) on first use."""
    from src.rag.processor import doc_processor  # noqa: PLC0415
    from src.db import db  # noqa: PLC0415
    return doc_processor, db


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def search(query: str, filters: dict | None = None, top_k: int = 10) -> dict:
    """
    Search local documents using hybrid semantic + BM25 retrieval.

    Returns a pre-formatted context block and source list so the caller
    does not need to re-implement formatting logic.
    """
    doc_processor, _ = _get_services()
    filename_filter = (filters or {}).get("filenames", [])
    results = doc_processor.retrieve_context(query, filename_filter=filename_filter)
    results = results[:top_k]
    logger.info(f"[local-docs] search '{query[:60]}' → {len(results)} chunks")

    if not results:
        return {"context": "", "sources": []}

    context = doc_processor.format_context_for_llm(results, max_length=6000)
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


def list_sources() -> list[dict]:
    """List all ingested documents."""
    _, db = _get_services()
    docs = db.get_all_documents()
    return [
        {
            "id": d["id"],
            "filename": d["filename"],
            "chunk_count": d.get("chunk_count", 0),
            "doc_type": d.get("doc_type"),
        }
        for d in docs
    ]


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

_server.register_tool(
    name="search",
    description="Search local documents using hybrid semantic + BM25 retrieval",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "filters": {
                "type": "object",
                "description": "Optional filters — e.g. {\"filenames\": [\"report.pdf\"]}",
            },
            "top_k": {"type": "integer", "default": 10, "description": "Max chunks to return"},
        },
        "required": ["query"],
    },
    handler=search,
)

_server.register_tool(
    name="list_sources",
    description="List all ingested documents and their chunk counts",
    input_schema={"type": "object", "properties": {}},
    handler=list_sources,
)

# WSGI entry point for gunicorn
flask_app = _server.get_wsgi_app()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _main() -> None:
    parser = argparse.ArgumentParser(description="LocalChat local-docs MCP server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    parser.add_argument("--port", type=int, default=5001, help="Bind port")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    _server.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    _main()
