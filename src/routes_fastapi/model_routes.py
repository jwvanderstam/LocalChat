"""Model routes — list, active get/set, pull (SSE), delete, test."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from .. import config
from ..security_fastapi import require_admin_dep
from ..utils.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter()

_ERR_INTERNAL = "Internal server error"
_ERR_MODEL_REQUIRED = "model is required"


def _validation_error_message(exc: Exception, default: str) -> str:
    """Surface a ModelXRequest field-validator's actual message (e.g. "Model
    name contains invalid characters") instead of a generic fallback that
    doesn't tell the caller what was wrong with the name they entered.

    Only overrides the default for our own @field_validator-raised errors
    (Pydantic's error "type" is "value_error"); a field that's missing
    entirely gets Pydantic's own "Field required", which doesn't name the
    field and is less clear here than the endpoint-specific default.
    """
    if isinstance(exc, ValidationError) and exc.errors():
        error = exc.errors()[0]
        if error["type"] == "value_error":
            return error["msg"].removeprefix("Value error, ")
    return default


@router.get("")
def list_models(request: Request, _admin: Annotated[str, Depends(require_admin_dep)]) -> Any:
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
def get_active_model(request: Request, _admin: Annotated[str, Depends(require_admin_dep)]) -> Any:
    active_model = config.app_state.get_active_model()
    return {"model": active_model}


@router.post("/active")
async def set_active_model(request: Request, _admin: Annotated[str, Depends(require_admin_dep)]) -> Any:
    from ..models import ModelRequest
    from ..utils.sanitization import sanitize_model_name

    data = await request.json() if await request.body() else {}
    try:
        request_data = ModelRequest(**data)
        model_name = sanitize_model_name(request_data.model)
    except Exception as exc:
        message = _validation_error_message(exc, _ERR_MODEL_REQUIRED)
        return JSONResponse({"success": False, "message": message}, status_code=400)

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
async def pull_model(request: Request, _admin: Annotated[str, Depends(require_admin_dep)]) -> Any:
    from ..models import ModelPullRequest
    from ..utils.sanitization import sanitize_model_name

    data = await request.json() if await request.body() else {}
    try:
        request_data = ModelPullRequest(**data)
        model_name = sanitize_model_name(request_data.model)
    except Exception as exc:
        message = _validation_error_message(exc, _ERR_MODEL_REQUIRED)
        return JSONResponse({"success": False, "message": message}, status_code=400)

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
async def delete_model(request: Request, _admin: Annotated[str, Depends(require_admin_dep)]) -> Any:
    from ..models import ModelDeleteRequest
    from ..utils.sanitization import sanitize_model_name

    data = await request.json() if await request.body() else {}
    try:
        request_data = ModelDeleteRequest(**data)
        model_name = sanitize_model_name(request_data.model)
    except Exception as exc:
        message = _validation_error_message(exc, _ERR_MODEL_REQUIRED)
        return JSONResponse({"success": False, "message": message}, status_code=400)

    success, message = request.app.state.ollama_client.delete_model(model_name)
    if not success:
        return JSONResponse({"success": False, "message": f"Failed to delete model: {message}"}, status_code=400)
    return {"success": True, "message": message}


@router.post("/unload")
async def unload_model(request: Request, _admin: Annotated[str, Depends(require_admin_dep)]) -> Any:
    from ..models import ModelRequest
    from ..utils.sanitization import sanitize_model_name

    data = await request.json() if await request.body() else {}
    try:
        request_data = ModelRequest(**data)
        model_name = sanitize_model_name(request_data.model)
    except Exception as exc:
        message = _validation_error_message(exc, _ERR_MODEL_REQUIRED)
        return JSONResponse({"success": False, "message": message}, status_code=400)

    success, message = request.app.state.ollama_client.unload_model(model_name)
    if not success:
        return JSONResponse({"success": False, "message": f"Failed to unload model: {message}"}, status_code=400)
    return {"success": True, "message": message}


@router.post("/test")
async def test_model(request: Request, _admin: Annotated[str, Depends(require_admin_dep)]) -> Any:
    from ..models import ModelRequest
    from ..utils.sanitization import sanitize_model_name

    data = await request.json() if await request.body() else {}
    try:
        request_data = ModelRequest(**data)
        model_name = sanitize_model_name(request_data.model)
    except Exception as exc:
        message = _validation_error_message(exc, _ERR_MODEL_REQUIRED)
        return JSONResponse({"success": False, "message": message}, status_code=400)

    try:
        success, result = await request.app.state.ollama_client.test_model(model_name)
        return {"success": success, "result": result}
    except Exception:
        logger.exception("[Models] test error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)
