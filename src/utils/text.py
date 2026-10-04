"""Word-level text helpers shared by retrieval and the database layer."""

from __future__ import annotations

import re

#: Function words and question scaffolding: they carry no topic, so a term list built
#: from a question is better without them.
STOP_WORDS: frozenset[str] = frozenset({
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

# Letters and digits only — any script, so Dutch "één" stays one word — matching what
# Postgres' parser keeps as a word, so every term is also a token in the stored tsvector.
# Nothing else gets through, which is also what makes the terms safe to join into a
# to_tsquery expression: no operator, quote or parenthesis can appear in one.
_TERM_RE = re.compile(r"[^\W_]+")


def content_terms(text: str) -> list[str]:
    """The distinct topic words of *text*, in order: lower-cased, stop words dropped."""
    seen: dict[str, None] = {}
    for term in _TERM_RE.findall(text.lower()):
        if len(term) > 1 and term not in STOP_WORDS:
            seen.setdefault(term, None)
    return list(seen)
