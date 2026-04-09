"""
Model Router
============

Rule-based classifier that selects the optimal model class for a query.
Runs entirely in-process with no I/O — adds < 1 ms to request latency.

Classification priority (first match wins):

    1. VISION   — any retrieved doc is image type, or query mentions images
    2. CODE     — query contains code markers, or any retrieved doc is code type
    3. LARGE    — plan signals multi-hop synthesis (hops ≥ 2 AND synthesis_required)
    4. FAST     — query is short and simple (length < 80 chars, single hop, no synthesis)
    5. BASE     — default for everything else

The router never makes a network call and never raises.  It returns
(model_id, rationale) — model_id is the resolved Ollama model name (may equal
the active model when a class is not configured).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ..utils.logging_config import get_logger
from .models import ModelClass, ModelRegistry, model_registry

if TYPE_CHECKING:
    from ..rag.planner import QueryPlan

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Classification signals
# ---------------------------------------------------------------------------

# Image doc types (from DocType enum in rag/doc_type.py)
_IMAGE_DOC_TYPES: frozenset[str] = frozenset({"IMAGE", "image"})

# Code doc types
_CODE_DOC_TYPES: frozenset[str] = frozenset({
    "CODE_PYTHON", "CODE_JS", "CODE_TS",
    "code_python", "code_js", "code_ts",
})

# Code marker patterns — presence in query text triggers CODE routing
_CODE_PATTERN = re.compile(
    r"\b(def |class |function |import |from .+ import|return |if __name__|"
    r"SELECT |INSERT |UPDATE |DELETE |CREATE TABLE|"
    r"console\.log|print\(|System\.out|#include|<\?php)\b"
    r"|[{};]\s*$"
    r"|\bcode\b|\bscript\b|\bfunction\b|\bclass\b|\bsyntax\b"
    r"|\breview.{0,20}(code|script|function)\b"
    r"|\b(debug|refactor|implement|write a function)\b",
    re.IGNORECASE,
)

# Vision query keywords
_VISION_PATTERN = re.compile(
    r"\b(image|diagram|chart|figure|graph|photo|screenshot|picture|visual|"
    r"what.{0,10}(see|show|depict)|describe.{0,10}image)\b",
    re.IGNORECASE,
)

# Threshold for "short simple query" → FAST routing
_FAST_MAX_CHARS = 80


# ---------------------------------------------------------------------------
# ModelRouter
# ---------------------------------------------------------------------------

class ModelRouter:
    """
    Selects the optimal ModelClass for a query based on signals.

    All classification is synchronous and allocation-free (compiled regex,
    set lookups).  Typical runtime: < 0.5 ms per call.
    """

    def __init__(self, registry: ModelRegistry | None = None) -> None:
        self._registry = registry or model_registry

    def select(
        self,
        query: str,
        plan: QueryPlan | None = None,
        doc_types: list[str] | None = None,
        active_model: str = "",
    ) -> tuple[str, str]:
        """
        Classify the query and return (model_id, rationale).

        Args:
            query:        Cleaned user query string.
            plan:         QueryPlan from the planner (optional).
            doc_types:    List of doc_type values from retrieved sources.
            active_model: Currently active Ollama model (used as fallback).

        Returns:
            (model_id, rationale) — model_id is the Ollama model to use;
            rationale is a short human-readable explanation for logging/UI.
        """
        cls, rationale = self._classify(query, plan, doc_types or [])
        model_id = self._registry.resolve(cls, fallback=active_model)

        if model_id and model_id != active_model:
            logger.info(
                f"[Router] {active_model!r} → {model_id!r} "
                f"({cls.value}): {rationale}"
            )
        else:
            logger.debug(
                f"[Router] {cls.value} → active model ({active_model!r}): {rationale}"
            )

        return model_id or active_model, f"{cls.value}: {rationale}"

    # ------------------------------------------------------------------
    # Classification logic
    # ------------------------------------------------------------------

    def _classify(
        self,
        query: str,
        plan: QueryPlan | None,
        doc_types: list[str],
    ) -> tuple[ModelClass, str]:
        """Return (ModelClass, rationale_string) for the query."""

        doc_type_set = set(doc_types)

        # 1. VISION — image documents or visual language in query
        if doc_type_set & _IMAGE_DOC_TYPES:
            return ModelClass.VISION, "retrieved sources include image documents"
        if _VISION_PATTERN.search(query):
            return ModelClass.VISION, "query contains visual/image language"

        # 2. CODE — code documents or code markers in query
        if doc_type_set & _CODE_DOC_TYPES:
            return ModelClass.CODE, "retrieved sources include code documents"
        if _CODE_PATTERN.search(query):
            return ModelClass.CODE, "query contains code markers or code-related language"

        # 3. LARGE — plan signals multi-hop synthesis
        if plan is not None and plan.estimated_hops >= 2 and plan.synthesis_required:
            return (
                ModelClass.LARGE,
                f"plan requires synthesis across {plan.estimated_hops} hops",
            )

        # 4. FAST — short simple query, no synthesis, single hop
        if self._is_fast(query, plan):
            return ModelClass.FAST, "short single-hop query with no synthesis required"

        # 5. BASE — default
        return ModelClass.BASE, "no specific routing signal matched"

    @staticmethod
    def _is_fast(query: str, plan: QueryPlan | None) -> bool:
        """Return True for queries that qualify for the fast model."""
        if len(query) > _FAST_MAX_CHARS:
            return False
        if plan is None:
            return True
        # Multi-hop or synthesis → not fast
        if plan.estimated_hops > 1 or plan.synthesis_required:
            return False
        return True
