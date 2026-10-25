"""Settings routes — admin stats, RAG params, reranker management, health, metrics."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from starlette.concurrency import run_in_threadpool

from .. import config
from ..security_fastapi import require_admin_dep
from ..services.admin_stats import gather_admin_stats
from ..services.feedback import FeedbackService
from ..utils.logging_config import get_logger
from ._services import feedback_service

logger = get_logger(__name__)
router = APIRouter()

Feedback = Annotated[FeedbackService, Depends(feedback_service)]

_RAG_LIMITS: dict[str, dict] = {
    "TOP_K_RESULTS":       {"min": 10,   "max": 50,   "type": int,   "default": 30},
    "RERANK_TOP_K":        {"min": 4,    "max": 20,   "type": int,   "default": 12},
    "DIVERSITY_THRESHOLD": {"min": 0.50, "max": 0.90, "type": float, "default": 0.70},
    "SEMANTIC_WEIGHT":     {"min": 0.30, "max": 0.90, "type": float, "default": 0.70},
}


@router.get("/health")
def health_check(request: Request) -> Any:
    from ..monitoring import compute_health_status
    status, status_code, checks = compute_health_status(request.app.state)
    return JSONResponse(
        {"status": status, "checks": checks, "timestamp": datetime.now().isoformat()},
        status_code=status_code,
    )


@router.get("/metrics", response_class=PlainTextResponse)
def metrics_endpoint(request: Request) -> Any:
    from ..monitoring import _check_metrics_auth, export_prometheus_metrics
    if not _check_metrics_auth(request):
        return Response("Forbidden", status_code=403,
                        headers={"WWW-Authenticate": 'Bearer realm="metrics"'})
    return PlainTextResponse(
        export_prometheus_metrics(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@router.get("/metrics.json")
def metrics_json_endpoint(request: Request) -> Any:
    from ..monitoring import _check_metrics_auth, get_metrics
    if not _check_metrics_auth(request):
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    return get_metrics().get_metrics()


@router.get("/settings/stats")
def settings_stats_api(
    request: Request,
    _admin: Annotated[str, Depends(require_admin_dep)],
) -> Any:
    return gather_admin_stats(request.app.state)


@router.get("/settings/rag")
def rag_params_get(request: Request, _admin: Annotated[str, Depends(require_admin_dep)]) -> Any:
    params = {}
    for key, meta in _RAG_LIMITS.items():
        params[key] = {
            "value":   meta["type"](config.app_state.get_rag_param(key)),
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

    top_k    = updates.get("TOP_K_RESULTS", config.app_state.get_rag_param("TOP_K_RESULTS"))
    rerank_k = updates.get("RERANK_TOP_K",  config.app_state.get_rag_param("RERANK_TOP_K"))
    if rerank_k > top_k:
        return JSONResponse(
            {"success": False, "errors": [f"RERANK_TOP_K ({rerank_k}) cannot exceed TOP_K_RESULTS ({top_k})"]},
            status_code=400,
        )

    for key, value in updates.items():
        config.app_state.set_rag_param(key, value)

    return {"success": True, "updated": updates}


@router.get("/logs")
async def logs_tail(
    request: Request,
    _admin: Annotated[str, Depends(require_admin_dep)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    level: Annotated[str | None, Query(pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> Any:
    """Tail the application log. Admin only — logs carry request paths and user ids.

    The path is never taken from the request: it is always ``config.LOG_FILE``, so
    there is no parameter for a caller to point somewhere else. Reading runs in the
    threadpool because the file is on disk and this handler is async (PERF-1).
    """
    from ..services.logs import read_log_tail

    result = await run_in_threadpool(read_log_tail, config.LOG_FILE, limit, level, q)
    return JSONResponse(result)


@router.get("/reranker/status")
def reranker_status(
    request: Request, feedback: Feedback, _admin: Annotated[str, Depends(require_admin_dep)]
) -> Any:
    from ..rag.reranker import get_reranker
    reranker = get_reranker()
    versions: list[dict] = []
    if request.app.state.startup_status.get("database"):
        versions = feedback.reranker_versions()
    return {
        "available": reranker.is_available(),
        "model_path": reranker.model_path,
        "enabled": config.RERANKER_ENABLED,
        "versions": versions,
    }


@router.post("/reranker/train")
def reranker_train(
    request: Request, feedback: Feedback, _admin: Annotated[str, Depends(require_admin_dep)]
) -> Any:
    import threading

    if not request.app.state.startup_status.get("database"):
        return JSONResponse({"success": False, "message": "Database unavailable"}, status_code=503)

    threading.Thread(target=feedback.retrain, daemon=True, name="reranker-train").start()
    return {"success": True, "message": "Fine-tune started in background"}


@router.post("/reranker/promote/{version_id}")
def reranker_promote(
    version_id: str, feedback: Feedback, _admin: Annotated[str, Depends(require_admin_dep)]
) -> Any:
    ok = feedback.promote(version_id)
    if not ok:
        return JSONResponse({"success": False, "message": "Version not found"}, status_code=404)
    return {"success": True}


@router.post("/reranker/rollback/{version_id}")
def reranker_rollback(
    version_id: str, feedback: Feedback, _admin: Annotated[str, Depends(require_admin_dep)]
) -> Any:
    ok = feedback.rollback(version_id)
    if not ok:
        return JSONResponse({"success": False, "message": "Version not found"}, status_code=404)
    return {"success": True}
