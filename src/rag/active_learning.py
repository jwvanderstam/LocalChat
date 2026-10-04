"""
Active Learning — Knowledge Gap Suggestions
============================================

Identifies topics in user queries where the knowledge base has poor coverage,
by comparing query terms against document content and feedback ratings.

Entry point: ``suggest_documents(scope, db) -> list[str]``
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from ..utils.logging_config import get_logger
from ..utils.scope import Scope
from ..utils.text import STOP_WORDS as _STOP_WORDS

logger = get_logger(__name__)

_TOKEN_RE = re.compile(r'[a-z]{3,}')


def _extract_terms(text: str) -> list[str]:
    """Return lower-cased word tokens longer than 2 chars, minus stop-words."""
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOP_WORDS]


def suggest_documents(
    scope: Scope,
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
        scope: Workspace to scope queries to, or ALL_WORKSPACES.
        db: Database instance (must implement get_low_confidence_queries).
        top_k: How many suggestions to return.
        feedback_threshold: Feedback rating below which a query counts as poor.

    Returns:
        List of suggested topic strings ordered by frequency.
    """
    try:
        queries = db.get_low_confidence_queries(
            threshold=feedback_threshold,
            scope=scope,
        )
    except Exception as exc:  # noqa: BLE001 — a suggestions query; an empty list is a valid answer
        logger.warning(f"[ActiveLearning] could not fetch queries: {exc}")
        return []

    if not queries:
        return []

    term_counts: Counter[str] = Counter()
    for q in queries:
        term_counts.update(_extract_terms(q))

    return [term for term, _ in term_counts.most_common(top_k)]
