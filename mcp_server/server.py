"""
LocalChat MCP Server
====================

Exposes LocalChat's PostgreSQL database and Ollama instance as tools
that GitHub Copilot can call during a chat session.

Tools
-----
  get_schema          — show every table and column in the public schema
  list_documents      — list ingested documents with chunk counts
  get_stats           — document / chunk / embedding counts
  search_chunks       — full-text ILIKE search across chunk_text
  get_ollama_models   — list models available in Ollama
  run_select_query    — run an arbitrary read-only SELECT query

Transport: SSE (HTTP) on $MCP_PORT (default 3001)
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import Any

import httpx
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from mcp.server.fastmcp import FastMCP


# ---------------------------------------------------------------------------
# Connection pool
# ---------------------------------------------------------------------------

def _conninfo() -> str:
    host     = os.environ.get("PG_HOST", "db")
    port     = os.environ.get("PG_PORT", "5432")
    dbname   = os.environ.get("PG_DB", "rag_db")
    user     = os.environ.get("PG_USER", "postgres")
    password = os.environ.get("PG_PASSWORD", "")
    return f"host={host} port={port} dbname={dbname} user={user} password={password}"


_pool: ConnectionPool | None = None


@asynccontextmanager
async def lifespan(app: Any):
    global _pool
    _pool = ConnectionPool(conninfo=_conninfo(), min_size=2, max_size=10, open=True)
    try:
        yield
    finally:
        _pool.close()


mcp = FastMCP(
    "localchat",
    host="0.0.0.0",
    port=int(os.environ.get("MCP_PORT", "3001")),
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Database helper
# ---------------------------------------------------------------------------

def _query(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    assert _pool is not None
    with _pool.connection() as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return cur.fetchall()


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def get_schema() -> str:
    """
    Return every table name and its columns (name + data type) in the
    public schema.  Call this first when you are unsure of the schema.
    """
    rows = _query("""
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
    """)
    return json.dumps(rows, indent=2, default=str)


@mcp.tool()
def list_documents() -> str:
    """
    List all ingested documents.
    Returns id, filename, created_at and chunk_count for each document,
    ordered newest-first.
    """
    rows = _query("""
        SELECT d.id,
               d.filename,
               d.created_at,
               COUNT(c.id) AS chunk_count
        FROM   documents d
        LEFT   JOIN document_chunks c ON c.document_id = d.id
        GROUP  BY d.id, d.filename, d.created_at
        ORDER  BY d.created_at DESC
    """)
    return json.dumps(rows, indent=2, default=str)


@mcp.tool()
def get_stats() -> str:
    """
    Return a summary of the vector store:
      - total documents
      - total chunks
      - chunks that already have an embedding vector
    """
    row = _query("""
        SELECT
            (SELECT COUNT(*) FROM documents)                                    AS documents,
            (SELECT COUNT(*) FROM document_chunks)                              AS chunks,
            (SELECT COUNT(*) FROM document_chunks WHERE embedding IS NOT NULL)  AS chunks_with_embeddings
    """)[0]
    return json.dumps(dict(row), indent=2)


@mcp.tool()
def search_chunks(query: str, limit: int = 10) -> str:
    """
    Case-insensitive keyword search (ILIKE) across all stored chunk text.

    Args:
        query:  The keyword or phrase to search for.
        limit:  Maximum number of results to return (default 10).

    Returns a list of matching chunks with chunk_index, filename, a
    300-character preview, and stored metadata.
    """
    rows = _query(
        """
        SELECT c.chunk_index,
               d.filename,
               LEFT(c.chunk_text, 300) AS preview,
               c.metadata
        FROM   document_chunks c
        JOIN   documents d ON d.id = c.document_id
        WHERE  c.chunk_text ILIKE %s
        ORDER  BY d.filename, c.chunk_index
        LIMIT  %s
        """,
        (f"%{query}%", limit),
    )
    return json.dumps(rows, indent=2, default=str)


@mcp.tool()
async def get_ollama_models() -> str:
    """
    List all models currently available in the Ollama instance,
    including their sizes and parameter counts.
    """
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434")
    async with httpx.AsyncClient(timeout=5) as client:
        resp = await client.get(f"{base_url}/api/tags")
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)


@mcp.tool()
def run_select_query(sql: str) -> str:
    """
    Execute a read-only SQL SELECT query and return the results as JSON.

    The query runs inside a READ ONLY transaction — any attempt to modify
    data is rejected by PostgreSQL.  Use get_schema() first to confirm
    table and column names before writing the query.

    Args:
        sql: A valid PostgreSQL SELECT statement.
    """
    rows = _query(sql)
    return json.dumps(rows, indent=2, default=str)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="sse")
