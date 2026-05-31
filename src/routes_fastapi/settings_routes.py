"""Settings routes — admin stats, RAG params, reranker management, health, metrics."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from .. import config
from ..security_fastapi import require_admin_dep
from ..utils.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter()

_RAG_LIMITS: dict[str, dict] = {
    "TOP_K_RESULTS":       {"min": 10,   "max": 50,   "type": int,   "default": 30},
    "RERANK_TOP_K":        {"min": 4,    "max": 20,   "type": int,   "default": 12},
    "DIVERSITY_THRESHOLD": {"min": 0.50, "max": 0.90, "type": float, "default": 0.70},
    "SEMANTIC_WEIGHT":     {"min": 0.30, "max": 0.90, "type": float, "default": 0.70},
}


def _collect_document_stats(app_state: Any) -> dict:
    db = getattr(app_state, "db", None)
    if not db:
        return {"document_count": 0, "chunk_count": 0, "db_available": False}
    try:
        return {
            "document_count": db.get_document_count(),
            "chunk_count": db.get_chunk_count(),
            "db_available": True,
        }
    except Exception as exc:
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
        except Exception as exc:
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
    except Exception as exc:
        logger.debug("Settings: could not fetch running model GPU stats: %s", exc)
        return []


def _get_gpu_info(ollama_client: Any) -> list:
    if not ollama_client:
        return []
    try:
        return ollama_client.get_gpu_info()
    except Exception as exc:
        logger.debug("Settings: could not fetch GPU hardware info: %s", exc)
        return []


def _collect_system_info(app_state: Any) -> dict:
    active_model = "—"
    try:
        active_model = config.app_state.get_active_model() or "—"
    except Exception:
        pass

    ollama_client = getattr(app_state, "ollama_client", None)
    return {
        "app_version": config.APP_VERSION,
        "active_model": active_model,
        "demo_mode": config.DEMO_MODE,
        "ollama_url": config.OLLAMA_BASE_URL,
        "ollama_available": getattr(app_state, "startup_status", {}).get("ollama", False),
        "timestamp": datetime.now().isoformat(),
        "loaded_models": _get_loaded_models(ollama_client),
        "gpu_info": _get_gpu_info(ollama_client),
    }


def gather_admin_stats(app_state: Any) -> dict:
    from ..monitoring import _compute_health_status, get_metrics
    _, _, health_checks = _compute_health_status(app_state)
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
            "TOP_K_RESULTS":       config.TOP_K_RESULTS,
            "RERANK_TOP_K":        config.RERANK_TOP_K,
            "DIVERSITY_THRESHOLD": config.DIVERSITY_THRESHOLD,
            "SEMANTIC_WEIGHT":     config.SEMANTIC_WEIGHT,
            "CHUNK_SIZE":          config.CHUNK_SIZE,
            "CHUNK_OVERLAP":       config.CHUNK_OVERLAP,
        },
    }


@router.get("/health")
def health_check(request: Request) -> Any:
    from ..monitoring import _compute_health_status
    status, status_code, checks = _compute_health_status(request.app.state)
    return JSONResponse(
        {"status": status, "checks": checks, "timestamp": datetime.now().isoformat()},
        status_code=status_code,
    )


@router.get("/metrics", response_class=PlainTextResponse)
def metrics_endpoint(request: Request) -> Any:
    from ..monitoring import _check_metrics_auth_request, export_prometheus_metrics
    if not _check_metrics_auth_request(request):
        return Response("Forbidden", status_code=403,
                        headers={"WWW-Authenticate": 'Bearer realm="metrics"'})
    return PlainTextResponse(
        export_prometheus_metrics(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@router.get("/metrics.json")
def metrics_json_endpoint(request: Request) -> Any:
    from ..monitoring import _check_metrics_auth_request, get_metrics
    if not _check_metrics_auth_request(request):
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    return get_metrics().get_metrics()


@router.get("/settings/stats")
def settings_stats_api(request: Request) -> Any:
    return gather_admin_stats(request.app.state)


@router.get("/settings/rag")
def rag_params_get(request: Request, _admin: Annotated[str, Depends(require_admin_dep)]) -> Any:
    params = {}
    for key, meta in _RAG_LIMITS.items():
        params[key] = {
            "value":   meta["type"](getattr(config, key, meta["default"])),
            "min":     meta["min"],
            "max":     meta["max"],
            "type":    meta["type"].__name__,
            "default": meta["default"],
        }
    return {"success": True, "params": params}


@router.post("/settings/rag")
async def rag_params_set(request: Request, _admin: Annotated[str, Depends(require_admin_dep)]) -> Any:
    body = await request.json() if await request.body() else {}
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
            errors.append(f"{key}: {value} out of range [{meta['min']}, {meta['max']}]")
            continue
        updates[key] = value

    if errors:
        return JSONResponse({"success": False, "errors": errors}, status_code=400)

    top_k    = updates.get("TOP_K_RESULTS", config.TOP_K_RESULTS)
    rerank_k = updates.get("RERANK_TOP_K",  config.RERANK_TOP_K)
    if rerank_k > top_k:
        return JSONResponse(
            {"success": False, "errors": [f"RERANK_TOP_K ({rerank_k}) cannot exceed TOP_K_RESULTS ({top_k})"]},
            status_code=400,
        )

    for key, value in updates.items():
        setattr(config, key, value)
        logger.info("RAG param updated: %s = %s", key, value)

    return {"success": True, "updated": updates}


@router.get("/reranker/status")
def reranker_status(request: Request, _admin: Annotated[str, Depends(require_admin_dep)]) -> Any:
    from ..rag.reranker import get_reranker
    reranker = get_reranker()
    versions: list[dict] = []
    if request.app.state.startup_status.get("database"):
        versions = request.app.state.db.get_reranker_versions()
    return {
        "available": reranker.is_available(),
        "model_path": reranker.model_path,
        "enabled": config.RERANKER_ENABLED,
        "versions": versions,
    }


@router.post("/reranker/train")
def reranker_train(request: Request, _admin: Annotated[str, Depends(require_admin_dep)]) -> Any:
    import threading

    if not request.app.state.startup_status.get("database"):
        return JSONResponse({"success": False, "message": "Database unavailable"}, status_code=503)

    app_state = request.app.state

    def _train() -> None:
        try:
            from ..rag.feedback_pipeline import (
                export_training_pairs,
                finetune_reranker,
                persist_reranker_version,
                promote_model,
            )
            pairs = export_training_pairs(app_state.db, days=30)
            if len(pairs) < config.FEEDBACK_FINETUNE_MIN_PAIRS:
                logger.info("[Reranker] Only %d pairs — skipping fine-tune", len(pairs))
                return
            result = finetune_reranker(pairs)
            if not result.get("skipped"):
                version_id = persist_reranker_version(app_state.db, result)
                if version_id and result.get("ndcg_after", 0) > result.get("ndcg_before", 0):
                    promote_model(app_state.db, version_id)
        except Exception:
            logger.exception("[Reranker] Background training failed")

    threading.Thread(target=_train, daemon=True, name="reranker-train").start()
    return {"success": True, "message": "Fine-tune started in background"}


@router.post("/reranker/promote/{version_id}")
def reranker_promote(version_id: str, request: Request, _admin: Annotated[str, Depends(require_admin_dep)]) -> Any:
    from ..rag.feedback_pipeline import promote_model
    ok = promote_model(request.app.state.db, version_id)
    if not ok:
        return JSONResponse({"success": False, "message": "Version not found"}, status_code=404)
    return {"success": True}


@router.post("/reranker/rollback/{version_id}")
def reranker_rollback(version_id: str, request: Request, _admin: Annotated[str, Depends(require_admin_dep)]) -> Any:
    from ..rag.feedback_pipeline import rollback_model
    ok = rollback_model(request.app.state.db, version_id)
    if not ok:
        return JSONResponse({"success": False, "message": "Version not found"}, status_code=404)
    return {"success": True}
