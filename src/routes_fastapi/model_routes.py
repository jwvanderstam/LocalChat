"""Model routes — list, active get/set, pull (SSE), delete, test."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .. import config
from ..utils.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter()

_ERR_INTERNAL = "Internal server error"
_ERR_MODEL_REQUIRED = "model is required"


@router.get("")
def list_models(request: Request) -> Any:
    from ..gpu.backends import detect

    success, models = request.app.state.ollama_client.list_models()
    if not success:
        return {"success": False, "models": []}

    try:
        backend = detect(force=config.GPU_BACKEND)
        if backend.memory_model == "dedicated":
            budget_mb = backend.free_mb
        else:
            budget_mb = max(0, backend.total_mb - config.SHARED_POOL_OS_RESERVE_MB)

        loaded_names = {
            m["name"] for m in request.app.state.ollama_client.get_running_models()
        }

        enriched = []
        for m in models:
            footprint_mb = request.app.state.ollama_client.estimate_model_footprint(m["name"])
            fits = footprint_mb <= budget_mb
            enriched.append(
                {
                    **m,
                    "fits": fits,
                    "loaded": m["name"] in loaded_names,
                    "footprint_mb": footprint_mb,
                    "budget_mb": budget_mb,
                    "reason": (
                        None
                        if fits
                        else (
                            f"requires ~{footprint_mb:,} MB, "
                            f"{budget_mb:,} MB available on {backend.backend_name}"
                        )
                    ),
                }
            )
    except Exception:
        logger.exception("GPU budget check failed — serving models without fit information")
        loaded_names = {
            m["name"] for m in request.app.state.ollama_client.get_running_models()
        }
        enriched = [
            {**m, "fits": True, "loaded": m["name"] in loaded_names, "footprint_mb": 0, "budget_mb": 0, "reason": None}
            for m in models
        ]

    return {"success": success, "models": enriched}


@router.get("/active")
def get_active_model(request: Request) -> Any:
    active_model = config.app_state.get_active_model()
    return {"model": active_model}


@router.post("/active")
async def set_active_model(request: Request) -> Any:
    from ..models import ModelRequest
    from ..utils.sanitization import sanitize_model_name

    data = await request.json() if await request.body() else {}
    try:
        request_data = ModelRequest(**data)
        model_name = sanitize_model_name(request_data.model)
    except Exception:
        return JSONResponse({"success": False, "message": _ERR_MODEL_REQUIRED}, status_code=400)

    success, models = request.app.state.ollama_client.list_models()
    if not success:
        return JSONResponse({"success": False, "message": "Failed to list models"}, status_code=503)

    model_names = [m["name"] for m in models]
    if model_name not in model_names:
        return JSONResponse(
            {"success": False, "message": f"Model '{model_name}' not found", "available": model_names[:10]},
            status_code=404,
        )

    config.app_state.set_active_model(model_name)
    logger.info("Active model changed to: %s", model_name)
    return {"success": True, "model": model_name}


@router.post("/pull")
async def pull_model(request: Request) -> Any:
    from ..models import ModelPullRequest
    from ..utils.sanitization import sanitize_model_name

    data = await request.json() if await request.body() else {}
    try:
        request_data = ModelPullRequest(**data)
        model_name = sanitize_model_name(request_data.model)
    except Exception:
        return JSONResponse({"success": False, "message": "Model name required"}, status_code=400)

    ollama_client = request.app.state.ollama_client

    async def _generate() -> AsyncGenerator[str, None]:
        try:
            for progress in ollama_client.pull_model(model_name):
                yield f"data: {json.dumps(progress)}\n\n"
        except Exception:
            logger.exception("Error pulling model")
            yield f"data: {json.dumps({'error': 'Failed to pull model'})}\n\n"
        finally:
            pass  # ensures cleanup runs on client disconnect

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/delete")
async def delete_model(request: Request) -> Any:
    from ..models import ModelDeleteRequest
    from ..utils.sanitization import sanitize_model_name

    data = await request.json() if await request.body() else {}
    try:
        request_data = ModelDeleteRequest(**data)
        model_name = sanitize_model_name(request_data.model)
    except Exception:
        return JSONResponse({"success": False, "message": _ERR_MODEL_REQUIRED}, status_code=400)

    success, message = request.app.state.ollama_client.delete_model(model_name)
    if not success:
        return JSONResponse({"success": False, "message": f"Failed to delete model: {message}"}, status_code=400)
    return {"success": True, "message": message}


@router.post("/unload")
async def unload_model(request: Request) -> Any:
    from ..models import ModelRequest
    from ..utils.sanitization import sanitize_model_name

    data = await request.json() if await request.body() else {}
    try:
        request_data = ModelRequest(**data)
        model_name = sanitize_model_name(request_data.model)
    except Exception:
        return JSONResponse({"success": False, "message": _ERR_MODEL_REQUIRED}, status_code=400)

    success, message = request.app.state.ollama_client.unload_model(model_name)
    if not success:
        return JSONResponse({"success": False, "message": f"Failed to unload model: {message}"}, status_code=400)
    return {"success": True, "message": message}


@router.post("/test")
async def test_model(request: Request) -> Any:
    from ..models import ModelRequest
    from ..utils.sanitization import sanitize_model_name

    data = await request.json() if await request.body() else {}
    try:
        request_data = ModelRequest(**data)
        model_name = sanitize_model_name(request_data.model)
    except Exception:
        return JSONResponse({"success": False, "message": _ERR_MODEL_REQUIRED}, status_code=400)

    try:
        success, result = await request.app.state.ollama_client.test_model(model_name)
        return {"success": success, "result": result}
    except Exception:
        logger.exception("[Models] test error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)
