"""
Built-in Tools
==============

Ready-to-use tools that are registered automatically when the ``tools``
package is imported.

Tools:
    search_documents  - Search the RAG vector database.
    list_documents    - List all ingested documents.
    get_current_datetime - Return the current date and time.
    calculate         - Evaluate a basic arithmetic expression.

"""

from __future__ import annotations

import ast as _ast
import json
import operator as _operator
import re
from datetime import datetime
from typing import Any

_AST_OPS: dict = {
    _ast.Add: _operator.add,
    _ast.Sub: _operator.sub,
    _ast.Mult: _operator.mul,
    _ast.Div: _operator.truediv,
    _ast.FloorDiv: _operator.floordiv,
    _ast.Pow: _operator.pow,
    _ast.Mod: _operator.mod,
    _ast.USub: _operator.neg,
    _ast.UAdd: _operator.pos,
}


def _ast_eval(node: _ast.expr) -> float:
    """Recursively evaluate a parsed arithmetic AST node — no eval() needed."""
    if isinstance(node, _ast.Constant):
        if isinstance(node.value, (int, float)):
            return float(node.value)
        raise ValueError(f"Unsupported literal: {node.value!r}")
    if isinstance(node, _ast.BinOp):
        op = _AST_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        return op(_ast_eval(node.left), _ast_eval(node.right))
    if isinstance(node, _ast.UnaryOp):
        op = _AST_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        return op(_ast_eval(node.operand))
    raise ValueError(f"Unsupported expression: {type(node).__name__}")

from ..utils.logging_config import get_logger
from .registry import tool_registry

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# search_documents
# ---------------------------------------------------------------------------

@tool_registry.register(
    name="search_documents",
    description=(
        "Search the uploaded document database for passages relevant to a "
        "query. Returns the most relevant text excerpts with source information."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to find relevant document passages.",
            },
        },
        "required": ["query"],
    },
)
def search_documents(query: str) -> str:
    """Execute a RAG retrieval and return formatted context."""
    from ..rag import doc_processor

    logger.info(f"[TOOL] search_documents: query={query!r}")
    results = doc_processor.retrieve_context(query, top_k=5)
    if not results:
        return "No relevant documents found for this query."
    return doc_processor.format_context_for_llm(results, max_length=4000)


# ---------------------------------------------------------------------------
# list_documents
# ---------------------------------------------------------------------------

@tool_registry.register(
    name="list_documents",
    description="List all documents that have been uploaded and ingested into the system.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
def list_documents(**_kwargs) -> str:
    """Return a human-readable list of all ingested documents."""
    from ..db import db

    logger.info("[TOOL] list_documents")
    try:
        documents = db.get_all_documents()
    except Exception as exc:
        logger.error(f"[TOOL] list_documents failed: {exc}", exc_info=True)
        return f"Could not retrieve documents: {exc}"

    if not documents:
        return "No documents have been uploaded yet."

    lines = [f"{len(documents)} document(s) in the system:\n"]
    for doc in documents:
        name = doc.get("filename", "unknown")
        chunks = doc.get("chunk_count", "?")
        created = doc.get("created_at", "")
        lines.append(f"  - {name}  ({chunks} chunks, uploaded {created})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# get_current_datetime
# ---------------------------------------------------------------------------

@tool_registry.register(
    name="get_current_datetime",
    description="Get the current date and time.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
def get_current_datetime() -> str:
    """Return the current local date and time as a readable string."""
    logger.info("[TOOL] get_current_datetime")
    now = datetime.now()
    return now.strftime("%A, %B %d, %Y at %H:%M:%S")


# ---------------------------------------------------------------------------
# calculate
# ---------------------------------------------------------------------------

_SAFE_MATH_RE = re.compile(r"^[\d\s\+\-\*\/\.\(\)\%\,]+$")

@tool_registry.register(
    name="calculate",
    description=(
        "Evaluate a mathematical expression and return the result. "
        "Supports basic arithmetic: +, -, *, /, ** (power), % (modulo), "
        "and parentheses."
    ),
    parameters={
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "The math expression to evaluate, e.g. '(12 + 8) * 3'.",
            },
        },
        "required": ["expression"],
    },
)
def calculate(expression: str) -> str:
    """Safely evaluate a math expression."""
    logger.info(f"[TOOL] calculate: {expression!r}")

    if not _SAFE_MATH_RE.match(expression):
        return "Invalid expression - only numbers and basic arithmetic operators (+, -, *, /, **, %, parentheses) are allowed."

    try:
        tree = _ast.parse(expression, mode='eval')
        result = _ast_eval(tree.body)
        return str(int(result) if result == int(result) else result)
    except Exception as exc:
        return f"Calculation error: {exc}"
