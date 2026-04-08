"""
Cloud Connectors MCP Server
============================

Independently deployable MCP server for cloud document sources
(SharePoint, OneDrive, S3, Confluence).  Phase 3 ships a no-op stub
that returns empty results — actual connectors land in Phase 4.

The stub is fully protocol-compliant so the core app can already treat
it as a real MCP server: circuit breaker, health checks, and tool
registration all work; the search tool just returns no results.

Exposes tools:
  - search(query, filters, top_k) — stub: always returns empty
  - list_sources()                 — lists registered cloud connectors

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

# Registry of connectors — populated in Phase 4 when real connectors land.
# Shape: {"name": str, "type": str, "enabled": bool, "description": str}
_CONNECTOR_REGISTRY: list[dict] = [
    {"name": "SharePoint", "type": "sharepoint", "enabled": False,
     "description": "Microsoft SharePoint document library (Phase 4)"},
    {"name": "OneDrive", "type": "onedrive", "enabled": False,
     "description": "Microsoft OneDrive personal/business (Phase 4)"},
    {"name": "S3", "type": "s3", "enabled": False,
     "description": "AWS S3 bucket connector (Phase 4)"},
    {"name": "Confluence", "type": "confluence", "enabled": False,
     "description": "Atlassian Confluence pages (Phase 4)"},
]


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def search(query: str, filters: dict | None = None, top_k: int = 10) -> dict:
    """Stub search — returns empty results until Phase 4 connectors are wired."""
    logger.debug(f"[cloud-connectors] search stub called for: {query[:60]!r}")
    return {"context": "", "sources": [], "stub": True}


def list_sources() -> list[dict]:
    """Return the registry of cloud connectors and their enablement status."""
    return _CONNECTOR_REGISTRY


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
