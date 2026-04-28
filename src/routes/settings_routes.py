
"""
Settings / Ops Dashboard Routes
=================================

Provides the Settings page with two sections:

  * **Observability** — read-only operator dashboard surfacing document
    statistics, cache health, database health, system information, GPU
    hardware statistics, loaded model breakdown, and request metrics.

  * **Appearance** — client-side theme picker (rendered in the template;
    no server-side state required).

The Settings page is rendered at ``GET /settings`` and its backing data is
exposed as JSON at ``GET /api/settings/stats`` so the page can refresh without
a full reload.

Security notes
--------------
Both endpoints respect ``DEMO_MODE``:
  * In demo mode they are always accessible (no JWT required).
  * In production mode the caller must supply a valid JWT via the standard
    ``Authorization: Bearer <token>`` header or the ``/api/auth/login``
    cookie.  Enforcement is delegated to ``require_admin`` from
    ``src.security``.

"""

from datetime import datetime

from flask import Blueprint, current_app, jsonify, render_template, request
from flask.typing import ResponseReturnValue

from .. import config
from ..monitoring import _compute_health_status, get_metrics
from ..security import require_admin
from ..utils.logging_config import get_logger

logger = get_logger(__name__)

bp = Blueprint("settings", __name__)


# ---------------------------------------------------------------------------
# Helpers — pure data-gathering functions (easy to unit-test)
# ---------------------------------------------------------------------------

def _collect_document_stats(app) -> dict:
    """
    Gather document and chunk counts from the database layer.

    Returns a dict with keys: ``document_count``, ``chunk_count``,
    ``db_available``.  Never raises — returns zeros when the DB is down.
    """
    if not getattr(app, "db", None):
        return {"document_count": 0, "chunk_count": 0, "db_available": False}
    try:
        doc_count = app.db.get_document_count()
        chunk_count = app.db.get_chunk_count()
        return {
            "document_count": doc_count,
            "chunk_count": chunk_count,
            "db_available": True,
        }
    except Exception as exc:
        logger.warning("Settings: could not fetch document stats: %s", exc)
        return {"document_count": 0, "chunk_count": 0, "db_available": False}


def _collect_cache_stats(app) -> dict:
    """
    Gather embedding-cache and query-cache statistics.

    Returns a dict with keys: ``embedding_cache``, ``query_cache``.
    Each sub-dict has ``hit_rate``, ``usage_percent``, ``available``.
    """
    result = {
        "embedding_cache": {"available": False, "hit_rate": 0.0, "usage_percent": 0.0},
        "query_cache":     {"available": False, "hit_rate": 0.0, "usage_percent": 0.0},
    }
    for attr, key in (("embedding_cache", "embedding_cache"),
                      ("query_cache", "query_cache")):
        cache = getattr(app, attr, None)
        if cache is None:
            continue
        try:
            stats = cache.get_stats()
            result[key] = {
                "available": True,
                "hit_rate": round(stats.hit_rate, 4),
                "usage_percent": round(stats.usage_percent, 2),
                "hits": stats.hits,
                "misses": stats.misses,
                "size": stats.size,
                "max_size": stats.max_size,
            }
        except Exception as exc:
            logger.warning("Settings: could not fetch %s stats: %s", key, exc)
    return result


def _get_loaded_models(ollama_client) -> list:
    """Return per-model GPU/VRAM stats from the Ollama client, or [] on error."""
    if not ollama_client:
        return []
    try:
        result = []
        for m in ollama_client.get_running_models():
            total = m.get("size", 0)
            vram = m.get("size_vram", 0)
            result.append({
                "name": m.get("name", ""),
                "size_mb": round(total / 1024 / 1024),
                "vram_mb": round(vram / 1024 / 1024),
                "gpu_percent": round(vram / total * 100) if total > 0 else 0,
                "processor": m.get("processor", "unknown"),
            })
        return result
    except Exception as exc:
        logger.debug("Settings: could not fetch running model GPU stats: %s", exc)
        return []


def _get_gpu_info(ollama_client) -> list:
    """Return per-physical-GPU hardware stats, or [] on error."""
    if not ollama_client:
        return []
    try:
        return ollama_client.get_gpu_info()
    except Exception as exc:
        logger.debug("Settings: could not fetch GPU hardware info: %s", exc)
        return []


def _collect_system_info(app) -> dict:
    """
    Collect static / near-static system information.

    Returns a dict with: ``app_version``, ``active_model``,
    ``demo_mode``, ``ollama_available``, ``timestamp``,
    ``loaded_models`` (GPU/VRAM breakdown per loaded model),
    ``gpu_info`` (per-physical-GPU hardware stats).
    """
    active_model = "—"
    try:
        active_model = config.app_state.get_active_model() or "—"
    except Exception:
        pass

    ollama_client = getattr(app, "ollama_client", None)

    return {
        "app_version": config.APP_VERSION,
        "active_model": active_model,
        "demo_mode": config.DEMO_MODE,
        "ollama_url": config.OLLAMA_BASE_URL,
        "ollama_available": getattr(app, "startup_status", {}).get("ollama", False),
        "timestamp": datetime.now().isoformat(),
        "loaded_models": _get_loaded_models(ollama_client),
        "gpu_info": _get_gpu_info(ollama_client),
    }


def gather_admin_stats(app) -> dict:
    """
    Aggregate all settings statistics into a single dictionary.

    This is the single entry-point called by both the JSON API and the
    template renderer.  Keeping it separate makes it trivial to unit-test.

    Args:
        app: Flask application (``current_app._get_current_object()``).

    Returns:
        Dict with keys: ``documents``, ``cache``, ``health``, ``system``,
        ``metrics``.
    """
    _, _, health_checks = _compute_health_status(app)
    metrics_snapshot = get_metrics().get_metrics()

    return {
        "documents": _collect_document_stats(app),
        "cache":     _collect_cache_stats(app),
        "health":    health_checks,
        "system":    _collect_system_info(app),
        "metrics": {
            "uptime_seconds": metrics_snapshot.get("uptime_seconds", 0),
            "request_count": sum(
                v for k, v in metrics_snapshot.get("counters", {}).items()
                if "http_requests_total" in k
            ),
        },
        "rag": {
            "TOP_K_RESULTS":       config.TOP_K_RESULTS,
            "RERANK_TOP_K":        config.RERANK_TOP_K,
            "DIVERSITY_THRESHOLD": config.DIVERSITY_THRESHOLD,
            "SEMANTIC_WEIGHT":     config.SEMANTIC_WEIGHT,
            "CHUNK_SIZE":          config.CHUNK_SIZE,
            "CHUNK_OVERLAP":       config.CHUNK_OVERLAP,
        },
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.route("/settings", methods=["GET"])
def settings_dashboard() -> ResponseReturnValue:
    """
    Render the Settings page (Observability + Appearance tabs).

    The page is intentionally read-only and references no user data, so it
    is safe to show to any authenticated operator.
    """
    app = current_app._get_current_object()  # type: ignore[attr-defined]
    stats = gather_admin_stats(app)
    return render_template("settings.html", stats=stats)


# ---------------------------------------------------------------------------
# Reranker management (Feature 5.2)
# ---------------------------------------------------------------------------

@bp.route("/api/reranker/status", methods=["GET"])
@require_admin
def reranker_status() -> ResponseReturnValue:
    """Return reranker availability and version history."""
    from ..rag.reranker import get_reranker
    reranker = get_reranker()
    versions: list[dict] = []
    if current_app.startup_status.get('database'):
        versions = current_app.db.get_reranker_versions()
    return jsonify({
        'available': reranker.is_available(),
        'model_path': reranker.model_path,
        'enabled': config.RERANKER_ENABLED,
        'versions': versions,
    })


@bp.route("/api/reranker/train", methods=["POST"])
@require_admin
def reranker_train() -> ResponseReturnValue:
    """Trigger an immediate reranker fine-tune in a background thread."""
    import threading

    from .. import config as _cfg

    if not current_app.startup_status.get('database'):
        return jsonify({'success': False, 'message': 'Database unavailable'}), 503

    app = current_app._get_current_object()  # type: ignore[attr-defined]

    def _train():
        try:
            from ..rag.feedback_pipeline import (
                export_training_pairs,
                finetune_reranker,
                persist_reranker_version,
                promote_model,
            )
            pairs = export_training_pairs(app.db, days=30)
            if len(pairs) < _cfg.FEEDBACK_FINETUNE_MIN_PAIRS:
                logger.info(f"[Reranker] Only {len(pairs)} pairs — skipping fine-tune")
                return
            result = finetune_reranker(pairs)
            if not result.get('skipped'):
                version_id = persist_reranker_version(app.db, result)
                if version_id and result.get('ndcg_after', 0) > result.get('ndcg_before', 0):
                    promote_model(app.db, version_id)
        except Exception as exc:
            logger.error(f"[Reranker] Background training failed: {exc}", exc_info=True)

    threading.Thread(target=_train, daemon=True, name="reranker-train").start()
    return jsonify({'success': True, 'message': 'Fine-tune started in background'})


@bp.route("/api/reranker/promote/<version_id>", methods=["POST"])
@require_admin
def reranker_promote(version_id: str) -> ResponseReturnValue:
    """Promote a reranker version to active."""
    from ..rag.feedback_pipeline import promote_model
    ok = promote_model(current_app.db, version_id)
    if not ok:
        return jsonify({'success': False, 'message': 'Version not found'}), 404
    return jsonify({'success': True})


@bp.route("/api/reranker/rollback/<version_id>", methods=["POST"])
@require_admin
def reranker_rollback(version_id: str) -> ResponseReturnValue:
    """Roll back to a previous reranker version."""
    from ..rag.feedback_pipeline import rollback_model
    ok = rollback_model(current_app.db, version_id)
    if not ok:
        return jsonify({'success': False, 'message': 'Version not found'}), 404
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# RAG parameter limits — enforced on both GET and POST
# ---------------------------------------------------------------------------

_RAG_LIMITS: dict = {
    "TOP_K_RESULTS":       {"min": 10,   "max": 50,   "type": int,   "default": 30},
    "RERANK_TOP_K":        {"min": 4,    "max": 20,   "type": int,   "default": 12},
    "DIVERSITY_THRESHOLD": {"min": 0.50, "max": 0.90, "type": float, "default": 0.70},
    "SEMANTIC_WEIGHT":     {"min": 0.30, "max": 0.90, "type": float, "default": 0.70},
}


@bp.route("/api/settings/rag", methods=["GET"])
@require_admin
def rag_params_get() -> ResponseReturnValue:
    """Return current live RAG parameter values and their allowed ranges."""
    params = {}
    for key, meta in _RAG_LIMITS.items():
        params[key] = {
            "value":   meta["type"](getattr(config, key, meta["default"])),
            "min":     meta["min"],
            "max":     meta["max"],
            "type":    meta["type"].__name__,
            "default": meta["default"],
        }
    return jsonify({"success": True, "params": params})


@bp.route("/api/settings/rag", methods=["POST"])
@require_admin
def rag_params_set() -> ResponseReturnValue:
    """
    Update one or more RAG parameters at runtime.

    Body: ``{"TOP_K_RESULTS": 25, "RERANK_TOP_K": 10, ...}``

    Validation rules
    ----------------
    * Each value must be within the declared ``[min, max]`` range.
    * ``RERANK_TOP_K`` must not exceed ``TOP_K_RESULTS`` (after both are
      resolved, using the submitted value or the current live value).
    """
    body = request.get_json(silent=True) or {}
    errors: list[str] = []
    updates: dict = {}

    for key, raw in body.items():
        if key not in _RAG_LIMITS:
            errors.append(f"Unknown parameter: {key!r}")
            continue
        meta = _RAG_LIMITS[key]
        try:
            value = meta["type"](raw)
        except (TypeError, ValueError):
            errors.append(f"{key}: cannot convert {raw!r} to {meta['type'].__name__}")
            continue
        if not (meta["min"] <= value <= meta["max"]):
            errors.append(
                f"{key}: {value} out of range [{meta['min']}, {meta['max']}]"
            )
            continue
        updates[key] = value

    if errors:
        return jsonify({"success": False, "errors": errors}), 400

    # Cross-parameter constraint: RERANK_TOP_K <= TOP_K_RESULTS
    top_k    = updates.get("TOP_K_RESULTS",  config.TOP_K_RESULTS)
    rerank_k = updates.get("RERANK_TOP_K",   config.RERANK_TOP_K)
    if rerank_k > top_k:
        return jsonify({
            "success": False,
            "errors": [f"RERANK_TOP_K ({rerank_k}) cannot exceed TOP_K_RESULTS ({top_k})"],
        }), 400

    for key, value in updates.items():
        setattr(config, key, value)
        logger.info("RAG param updated: %s = %s", key, value)

    return jsonify({"success": True, "updated": updates})


@bp.route("/api/settings/stats", methods=["GET"])
def settings_stats_api() -> ResponseReturnValue:
    """
    Return settings statistics as JSON.

    Used by the dashboard page for background refresh and available for
    external monitoring tools.

    Returns:
        JSON object with ``documents``, ``cache``, ``health``, ``system``,
        ``metrics`` keys.
    """
    app = current_app._get_current_object()  # type: ignore[attr-defined]
    return jsonify(gather_admin_stats(app))
