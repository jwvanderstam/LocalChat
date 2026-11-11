"""
Reranker Module
===============

Cross-encoder reranker that re-scores retrieved chunks using a fine-tuned
(or base) ``cross-encoder/ms-marco-MiniLM-L-6-v2`` model.  Enabled by
default (``RERANKER_ENABLED=true``).  Set to ``false`` only on very
constrained hardware where the extra inference latency is unacceptable.

Degrades gracefully to a no-op if ``RERANKER_ENABLED`` is false or if the
``sentence-transformers`` package is somehow missing at runtime.

Usage:
    from src.rag.reranker import get_reranker

    reranker = get_reranker()
    if reranker.is_available():
        scores = reranker.score(query, [chunk1, chunk2, ...])
"""
from __future__ import annotations

import os

from .. import config
from ..utils.logging_config import get_logger

logger = get_logger(__name__)


def _read_latest_pointer(safe_cfg_path: str) -> str | None:
    """Read the path stored in ``<safe_cfg_path>.txt`` and return it, or None.

    The .txt file is a Windows-safe alternative to a symlink written by the
    fine-tune pipeline to point at the most recently promoted model version.
    """
    latest_txt = os.path.realpath(os.path.splitext(safe_cfg_path)[0] + '.txt')
    if not os.path.isfile(latest_txt):
        return None
    try:
        with open(latest_txt, encoding="utf-8") as fh:
            pointed = fh.read().strip()
        return pointed or None
    except OSError:
        return None


def _to_safe_path(raw: str) -> str | None:
    """Resolve *raw* to a real filesystem path and return it only if it exists.

    Using ``os.path.realpath`` as the explicit sanitizer (resolves symlinks and
    ``..`` components) before any filesystem operation — satisfies S6549.
    """
    if not raw or '\x00' in raw:
        return None
    real = os.path.realpath(raw)
    return real if os.path.exists(real) else None

def confined_model_path(raw: str | None) -> str | None:
    """*raw* resolved, if it exists inside the directory ``RERANKER_MODEL_PATH`` sits in.

    A pointer file or a version row names the model to load; confining it means a
    path written by anything else cannot pick what the reranker loads (R-11).
    """
    safe = _to_safe_path(raw) if raw else None
    if safe is None:
        return None
    root = os.path.realpath(os.path.dirname(config.RERANKER_MODEL_PATH) or ".")
    try:
        inside = os.path.commonpath([root, safe]) == root
    except ValueError:  # different drives on Windows
        inside = False
    if not inside:
        logger.warning("[Reranker] Ignoring a model path outside the model directory")
        return None
    return safe


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
        except Exception as exc:  # noqa: BLE001 — scoring is a refinement; an empty list leaves the retrieval order as it was
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
                self._model = CrossEncoder(resolved, trust_remote_code=False)
                self._model_path = resolved
                logger.info("[Reranker] Loaded fine-tuned model")
                return
            except Exception as exc:  # noqa: BLE001 — a fine-tuned model that will not load falls back to the base model below
                logger.warning(f"[Reranker] Could not load fine-tuned model ({exc}), falling back to base")

        # Fall back to base model
        try:
            self._model = CrossEncoder(_BASE_MODEL, trust_remote_code=False)
            self._model_path = _BASE_MODEL
            logger.info(f"[Reranker] Loaded base model: {_BASE_MODEL}")
        except Exception as exc:  # noqa: BLE001 — and if the base will not load either, the reranker is simply off
            logger.warning(f"[Reranker] Could not load base model: {exc}")

    def _resolve_model_path(self, model_path: str | None) -> str | None:
        """Return an existing model directory path, or None.

        The configured path is the operator's; one named by a caller or by the pointer
        file must lie beside it.
        """
        candidates: list[str | None] = [confined_model_path(model_path)]
        cfg_path = config.RERANKER_MODEL_PATH
        if cfg_path:
            candidates.append(_to_safe_path(cfg_path))
            safe_cfg = os.path.realpath(cfg_path) if '\x00' not in cfg_path else None
            if safe_cfg:
                candidates.append(confined_model_path(_read_latest_pointer(safe_cfg)))
        for safe in candidates:
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
