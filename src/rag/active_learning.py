"""
Active Learning — Knowledge Gap Suggestions
============================================

Identifies topics in user queries where the knowledge base has poor coverage,
by comparing query terms against document content and feedback ratings.

Entry point: ``suggest_documents(workspace_id, db) -> list[str]``
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from ..utils.logging_config import get_logger

logger = get_logger(__name__)

# Stop-words to exclude from term extraction
_STOP_WORDS = frozenset({
    'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
    'should', 'may', 'might', 'shall', 'can', 'need', 'dare', 'ought',
    'what', 'which', 'who', 'when', 'where', 'why', 'how',
    'i', 'me', 'my', 'we', 'our', 'you', 'your', 'he', 'she', 'it',
    'they', 'them', 'their', 'this', 'that', 'these', 'those',
    'and', 'but', 'or', 'nor', 'for', 'yet', 'so', 'to', 'of', 'in',
    'on', 'at', 'by', 'with', 'about', 'as', 'into', 'through', 'from',
    'not', 'no', 'any', 'all', 'please', 'tell', 'explain', 'describe',
    'give', 'show', 'find', 'get', 'make', 'use', 'want', 'like', 'know',
})

_TOKEN_RE = re.compile(r'[a-z]{3,}')


def _extract_terms(text: str) -> list[str]:
    """Return lower-cased word tokens longer than 2 chars, minus stop-words."""
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOP_WORDS]


def suggest_documents(
    workspace_id: str | None,
    db: Any,
    top_k: int = 10,
    feedback_threshold: float = 0.5,
) -> list[str]:
    """Return a ranked list of topics/terms the workspace knowledge base lacks.

    Algorithm:
    1. Fetch user queries with low or no positive feedback.
    2. Extract all meaningful terms from those queries.
    3. Return the top-k most frequent terms as suggested document topics.

    Args:
        workspace_id: Workspace to scope queries to, or None for all.
        db: Database instance (must implement get_low_confidence_queries).
        top_k: How many suggestions to return.
        feedback_threshold: Feedback rating below which a query counts as poor.

    Returns:
        List of suggested topic strings ordered by frequency.
    """
    try:
        queries = db.get_low_confidence_queries(
            workspace_id=workspace_id,
            threshold=feedback_threshold,
        )
    except Exception as exc:
        logger.warning(f"[ActiveLearning] could not fetch queries: {exc}")
        return []

    if not queries:
        return []

    term_counts: Counter[str] = Counter()
    for q in queries:
        term_counts.update(_extract_terms(q))

    return [term for term, _ in term_counts.most_common(top_k)]
