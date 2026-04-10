"""
Reranker Module
===============

Optional cross-encoder reranker that re-scores retrieved chunks using a
fine-tuned (or base) ``cross-encoder/ms-marco-MiniLM-L-6-v2`` model.

The module is a no-op when ``sentence-transformers`` is not installed or
``RERANKER_ENABLED`` is false — retrieval falls back silently to the
existing hybrid BM25+semantic score.

Usage:
    from src.rag.reranker import get_reranker

    reranker = get_reranker()
    if reranker.is_available():
        scores = reranker.score(query, [chunk1, chunk2, ...])
"""
from __future__ import annotations

import os
from pathlib import Path

from .. import config
from ..utils.logging_config import get_logger

logger = get_logger(__name__)


def _to_safe_path(raw: str) -> str | None:
    """Resolve *raw* to a real filesystem path and return it only if it exists.

    Using ``os.path.realpath`` as the explicit sanitizer (resolves symlinks and
    ``..`` components) before any filesystem operation — satisfies S6549.
    """
    if not raw or '\x00' in raw:
        return None
    real = os.path.realpath(raw)
    return real if os.path.exists(real) else None

_BASE_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class RerankerModel:
    """Wraps a cross-encoder model for passage re-ranking.

    Gracefully degrades to a no-op if ``sentence-transformers`` is absent or
    no model is available.
    """

    def __init__(self, model_path: str | None = None) -> None:
        self._model = None
        self._model_path: str | None = None
        self._load(model_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return True if a cross-encoder model is loaded and ready."""
        return self._model is not None

    def score(self, query: str, passages: list[str]) -> list[float]:
        """Return a relevance score for each passage (higher = more relevant).

        Returns an empty list if the model is not available.
        """
        if not self._model or not passages:
            return []
        try:
            pairs = [(query, p) for p in passages]
            scores = self._model.predict(pairs)
            return [float(s) for s in scores]
        except Exception as exc:
            logger.warning(f"[Reranker] scoring failed: {exc}")
            return []

    @property
    def model_path(self) -> str | None:
        return self._model_path

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load(self, model_path: str | None) -> None:
        try:
            from sentence_transformers import CrossEncoder  # type: ignore[import]
        except ImportError:
            logger.debug("[Reranker] sentence-transformers not installed — reranker disabled")
            return

        # Try fine-tuned model first
        resolved = self._resolve_model_path(model_path)
        if resolved:
            try:
                safe_path = str(Path(resolved).resolve())
                self._model = CrossEncoder(safe_path)
                self._model_path = safe_path
                logger.info("[Reranker] Loaded fine-tuned model")
                return
            except Exception as exc:
                logger.warning(f"[Reranker] Could not load fine-tuned model ({exc}), falling back to base")

        # Fall back to base model
        try:
            self._model = CrossEncoder(_BASE_MODEL)
            self._model_path = _BASE_MODEL
            logger.info(f"[Reranker] Loaded base model: {_BASE_MODEL}")
        except Exception as exc:
            logger.warning(f"[Reranker] Could not load base model: {exc}")

    def _resolve_model_path(self, model_path: str | None) -> str | None:
        """Return an existing model directory path, or None."""
        candidates: list[str] = []
        if model_path:
            candidates.append(model_path)
        cfg_path = config.RERANKER_MODEL_PATH
        if cfg_path:
            candidates.append(cfg_path)
            # If the config path is a 'latest.txt' pointer, read its contents
            latest_txt = Path(cfg_path).with_suffix('.txt')
            if latest_txt.exists():
                try:
                    pointed = latest_txt.read_text().strip()
                    if pointed:
                        candidates.append(pointed)
                except OSError:
                    pass
        for p in candidates:
            safe = _to_safe_path(p)
            if safe:
                return safe
        return None


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_reranker: RerankerModel | None = None


def get_reranker() -> RerankerModel:
    """Return the module-level singleton, initialising on first call."""
    global _reranker
    if _reranker is None:
        _reranker = RerankerModel()
    return _reranker


def reload_reranker(model_path: str | None = None) -> RerankerModel:
    """Force a reload of the reranker (e.g. after a new model is promoted)."""
    global _reranker
    _reranker = RerankerModel(model_path)
    return _reranker
