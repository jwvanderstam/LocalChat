"""GR-1c — flag documents that carry instruction-shaped text, at ingest.

A heuristic, and it says so: it will miss an injection phrased in a way these patterns
do not know, and it will flag a document *about* prompt injection — this repository's
own ROADMAP among them. It never blocks an ingest. It exists so that a person looking at
the Documents page can see which documents carry text written to address the model
rather than the reader, and decide.

Measured before shipping (2026-10-05): on `docs/` it flags one file of 24, the ROADMAP's
own description of the attack; on a private business corpus, none of 273.
"""

from __future__ import annotations

import re

#: Pattern kind -> what it matches. The kind is what the Documents page shows, so each
#: name says what was found rather than how.
PATTERNS: dict[str, re.Pattern[str]] = {
    "override-instructions": re.compile(
        r"\b(ignore|disregard|forget|override)\s+(all\s+|any\s+|the\s+|your\s+)?"
        r"(previous|prior|above|earlier|preceding|system)\s+(instructions|prompts?|rules|messages)\b",
        re.IGNORECASE,
    ),
    # A line opening as a chat role, followed by words. Words, not a value: "System: 2"
    # is a field label in a spreadsheet, and was the one hit on the business corpus.
    "role-marker": re.compile(
        r"^[ \t]*(system|assistant|developer)[ \t]*:[ \t]*[^\W\d_]{2,}", re.IGNORECASE | re.MULTILINE
    ),
    "chat-template": re.compile(
        r"<\|im_start\|>|<\|im_end\|>|<\|system\|>|\[/?INST\]|<<SYS>>|<\|start_header_id\|>",
        re.IGNORECASE,
    ),
    # Not a bare "you are now": that is how software tells a reader they are logged in.
    "persona-reset": re.compile(
        r"\bnew instructions\s*:|\bfrom now on,? you (will|must|should|are)\b"
        r"|\byou are no longer (an?|the) (ai|assistant|model|language model)\b",
        re.IGNORECASE,
    ),
    "tool-call": re.compile(
        r"\"tool_calls\"\s*:|\{\s*\"name\"\s*:\s*\"[^\"]+\"\s*,\s*\"arguments\"\s*:",
        re.IGNORECASE,
    ),
}


def scan(texts: list[str]) -> list[str]:
    """The pattern kinds found anywhere in *texts*, sorted; empty when none."""
    return sorted(kind for kind, pattern in PATTERNS.items() if any(pattern.search(t) for t in texts))
