"""Admin statistics for the settings page: documents, caches, health, system, metrics.

Moved out of ``settings_routes`` (QP-5): it reads the database and every subsystem, which
is a service's job, not a route module's. Each part degrades on its own, so the page
renders with what could be determined.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .. import config
from ..utils.logging_config import get_logger
from ..utils.scope import ALL_WORKSPACES

logger = get_logger(__name__)


def _collect_document_stats(app_state: Any) -> dict:
    db = getattr(app_state, "db", None)
    if not db:
        return {"document_count": 0, "chunk_count": 0, "db_available": False}
    try:
        return {
            # Admin-only (settings_stats_api): the installation's totals by design.
            "document_count": db.documents.count(scope=ALL_WORKSPACES),
            "chunk_count": db.documents.chunk_count(scope=ALL_WORKSPACES),
            "db_available": True,
        }
    except Exception as exc:  # noqa: BLE001 — the panel renders with zeros and db_available=False rather than failing
        logger.warning("Settings: could not fetch document stats: %s", exc)
        return {"document_count": 0, "chunk_count": 0, "db_available": False}


def _collect_cache_stats(app_state: Any) -> dict:
    result = {
        "embedding_cache": {"available": False, "hit_rate": 0.0, "usage_percent": 0.0},
        "query_cache":     {"available": False, "hit_rate": 0.0, "usage_percent": 0.0},
    }
    for attr, key in (("embedding_cache", "embedding_cache"), ("query_cache", "query_cache")):
        cache = getattr(app_state, attr, None)
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
        except Exception as exc:  # noqa: BLE001 — one stats block out of several; the others still render
            logger.warning("Settings: could not fetch %s stats: %s", key, exc)
    return result


def _get_loaded_models(ollama_client: Any) -> list:
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
    except Exception as exc:  # noqa: BLE001 — GPU stats are decoration on this page
        logger.debug("Settings: could not fetch running model GPU stats: %s", exc)
        return []


def _get_gpu_info(ollama_client: Any) -> list:
    if not ollama_client:
        return []
    try:
        return ollama_client.get_gpu_info()
    except Exception as exc:  # noqa: BLE001 — same, for hardware info
        logger.debug("Settings: could not fetch GPU hardware info: %s", exc)
        return []


def _collect_system_info(app_state: Any) -> dict:
    active_model = "—"
    try:
        active_model = config.app_state.get_active_model() or "—"
    except Exception:  # noqa: BLE001 — the active model is display-only here; the em dash is the honest default
        logger.debug("Could not read active model for system info", exc_info=True)

    ollama_client = getattr(app_state, "ollama_client", None)
    return {
        "app_version": config.APP_VERSION,
        "active_model": active_model,
        "ollama_url": config.OLLAMA_BASE_URL,
        "ollama_available": getattr(app_state, "startup_status", {}).get("ollama", False),
        "timestamp": datetime.now().isoformat(),
        "loaded_models": _get_loaded_models(ollama_client),
        "gpu_info": _get_gpu_info(ollama_client),
    }


def gather_admin_stats(app_state: Any) -> dict:
    from ..monitoring import compute_health_status, get_metrics
    _, _, health_checks = compute_health_status(app_state)
    metrics_snapshot = get_metrics().get_metrics()

    return {
        "documents": _collect_document_stats(app_state),
        "cache":     _collect_cache_stats(app_state),
        "health":    health_checks,
        "system":    _collect_system_info(app_state),
        "metrics": {
            "uptime_seconds": metrics_snapshot.get("uptime_seconds", 0),
            "request_count": sum(
                v for k, v in metrics_snapshot.get("counters", {}).items()
                if "http_requests_total" in k
            ),
        },
        "rag": {
            "TOP_K_RESULTS":       config.app_state.get_rag_param("TOP_K_RESULTS"),
            "RERANK_TOP_K":        config.app_state.get_rag_param("RERANK_TOP_K"),
            "DIVERSITY_THRESHOLD": config.app_state.get_rag_param("DIVERSITY_THRESHOLD"),
            "SEMANTIC_WEIGHT":     config.app_state.get_rag_param("SEMANTIC_WEIGHT"),
            "CHUNK_SIZE":          config.CHUNK_SIZE,
            "CHUNK_OVERLAP":       config.CHUNK_OVERLAP,
        },
    }
