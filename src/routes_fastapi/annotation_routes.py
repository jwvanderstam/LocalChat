"""Annotation routes — CRUD for chunk annotations."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ..security_fastapi import get_current_user_id
from ..utils.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter()

_ERR_INTERNAL = "Internal server error"


@router.post("/annotations", status_code=201)
async def create_annotation(request: Request) -> Any:
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
        annotation_id = request.app.state.db.add_annotation(
            chunk_id=chunk_id, text=text, user_id=user_id, conversation_id=conversation_id,
        )
        return JSONResponse({"success": True, "id": annotation_id}, status_code=201)
    except ValueError:
        return JSONResponse({"success": False, "message": "Annotation text must not be empty"}, status_code=400)
    except Exception:
        logger.exception("[Annotations] create error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.get("/chunks/{chunk_id}/annotations")
def list_chunk_annotations(chunk_id: int, request: Request) -> Any:
    try:
        annotations = request.app.state.db.get_annotations_for_chunk(chunk_id)
        return {"success": True, "annotations": annotations}
    except Exception:
        logger.exception("[Annotations] list error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.delete("/annotations/{annotation_id}")
def delete_annotation(annotation_id: str, request: Request) -> Any:
    user_id = get_current_user_id(request)
    try:
        deleted = request.app.state.db.delete_annotation(annotation_id, user_id=user_id)
        if not deleted:
            return JSONResponse({"success": False, "message": "Annotation not found"}, status_code=404)
        return {"success": True}
    except Exception:
        logger.exception("[Annotations] delete error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)
