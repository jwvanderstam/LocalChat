"""Annotation routes — CRUD for chunk annotations."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ..security_fastapi import get_current_user_id
from ..services.annotations import AnnotationsService
from ..utils.logging_config import get_logger
from ..utils.workspace import get_scope
from ._authz import deny as _deny
from ._services import annotations_service

logger = get_logger(__name__)
router = APIRouter()

_ERR_INTERNAL = "Internal server error"
_NOT_FOUND = "Chunk not found"

Annotations = Annotated[AnnotationsService, Depends(annotations_service)]


@router.post("/annotations", status_code=201)
async def create_annotation(request: Request, annotations: Annotations) -> Any:
    denied = _deny(request, None, "editor")
    if denied:
        return denied
    data = await request.json() if await request.body() else {}
    chunk_id = data.get("chunk_id")
    text = (data.get("text") or "").strip()
    conversation_id = data.get("conversation_id") or None

    if not chunk_id or not isinstance(chunk_id, int):
        return JSONResponse({"success": False, "message": "chunk_id (integer) is required"}, status_code=400)
    if not text:
        return JSONResponse({"success": False, "message": "text is required"}, status_code=400)

    user_id = get_current_user_id(request)
    try:
        annotation_id = annotations.add(chunk_id, text, user_id, conversation_id, get_scope(request))
        if annotation_id is None:
            return JSONResponse({"success": False, "message": "Chunk not found"}, status_code=404)
        return JSONResponse({"success": True, "id": annotation_id}, status_code=201)
    except ValueError as ve:
        logger.warning("[Annotations] validation error: %s", ve)
        return JSONResponse({"success": False, "message": "Annotation text must not be empty"}, status_code=400)
    except Exception:
        logger.exception("[Annotations] create error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.get("/chunks/{chunk_id}/annotations")
def list_chunk_annotations(chunk_id: int, request: Request, annotations: Annotations) -> Any:
    denied = _deny(request, None, "viewer")
    if denied:
        return denied
    try:
        found = annotations.for_chunk(chunk_id, get_scope(request))
        if found is None:
            return JSONResponse(
                {"success": False, "message": _NOT_FOUND}, status_code=404
            )
        return {"success": True, "annotations": found}
    except Exception:
        logger.exception("[Annotations] list error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.delete("/annotations/{annotation_id}")
def delete_annotation(annotation_id: str, request: Request, annotations: Annotations) -> Any:
    denied = _deny(request, None, "editor")
    if denied:
        return denied
    try:
        deleted = annotations.retire(annotation_id, get_current_user_id(request), get_scope(request))
        if not deleted:
            return JSONResponse({"success": False, "message": "Annotation not found"}, status_code=404)
        return {"success": True}
    except Exception:
        logger.exception("[Annotations] delete error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)
