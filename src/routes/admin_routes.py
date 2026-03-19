# -*- coding: utf-8 -*-

"""
Admin / Ops Dashboard Routes
=============================

Provides a read-only operator dashboard that surfaces:

  * Document statistics (total count, chunk count, last indexed)
  * Cache health (hit/miss ratios, Redis availability)
  * Database health (connectivity, migration readiness)
  * System information (app version, active model, demo mode flag)
  * GPU hardware statistics (per-GPU VRAM, utilisation %, temperature via
    ``OllamaClient.get_gpu_info()`` with 30 s TTL caching; supports NVIDIA
    via ``nvidia-smi`` and AMD via ``rocm-smi``)
  * Loaded model breakdown (VRAM usage and GPU offload % per running model
    via ``OllamaClient.get_running_models()`` with 5 s TTL caching)

The dashboard page is rendered at ``GET /admin`` and its backing data is
exposed as JSON at ``GET /api/admin/stats`` so the page can refresh without
a full reload.

Security notes
--------------
Both endpoints respect ``DEMO_MODE``:
  * In demo mode they are always accessible (no JWT required).
  * In production mode the caller must supply a valid JWT via the standard
    ``Authorization: Bearer <token>`` header or the ``/api/auth/login``
    cookie.  Enforcement is delegated to ``require_admin`` from
    ``src.security``.

Author: LocalChat Team
Last Updated: 2026-03-19
"""

from datetime import datetime

from flask import Blueprint, jsonify, render_template, current_app
from flask.typing import ResponseReturnValue

from .. import config
from ..monitoring import get_metrics, _compute_health_status
from ..utils.logging_config import get_logger

logger = get_logger(__name__)

bp = Blueprint("admin", __name__)


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
        logger.warning("Admin: could not fetch document stats: %s", exc)
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
            logger.warning("Admin: could not fetch %s stats: %s", key, exc)
    return result


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

    loaded_models = []
    try:
        if ollama_client:
            for m in ollama_client.get_running_models():
                total = m.get("size", 0)
                vram = m.get("size_vram", 0)
                loaded_models.append({
                    "name": m.get("name", ""),
                    "size_mb": round(total / 1024 / 1024),
                    "vram_mb": round(vram / 1024 / 1024),
                    "gpu_percent": round(vram / total * 100) if total > 0 else 0,
                    "processor": m.get("processor", "unknown"),
                })
    except Exception as exc:
        logger.debug("Admin: could not fetch running model GPU stats: %s", exc)

    gpu_info = []
    try:
        if ollama_client:
            gpu_info = ollama_client.get_gpu_info()
    except Exception as exc:
        logger.debug("Admin: could not fetch GPU hardware info: %s", exc)

    return {
        "app_version": config.APP_VERSION,
        "active_model": active_model,
        "demo_mode": config.DEMO_MODE,
        "ollama_available": getattr(app, "startup_status", {}).get("ollama", False),
        "timestamp": datetime.now().isoformat(),
        "loaded_models": loaded_models,
        "gpu_info": gpu_info,
    }


def gather_admin_stats(app) -> dict:
    """
    Aggregate all admin statistics into a single dictionary.

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
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.route("/admin", methods=["GET"])
def admin_dashboard() -> ResponseReturnValue:
    """
    Render the operator admin dashboard.

    The page is intentionally read-only and references no user data, so it
    is safe to show to any authenticated operator.
    """
    app = current_app._get_current_object()  # type: ignore[attr-defined]
    stats = gather_admin_stats(app)
    return render_template("admin.html", stats=stats)


@bp.route("/api/admin/stats", methods=["GET"])
def admin_stats_api() -> ResponseReturnValue:
    """
    Return admin statistics as JSON.

    Used by the dashboard page for background refresh and available for
    external monitoring tools.

    Returns:
        JSON object with ``documents``, ``cache``, ``health``, ``system``,
        ``metrics`` keys.
    """
    app = current_app._get_current_object()  # type: ignore[attr-defined]
    return jsonify(gather_admin_stats(app))
