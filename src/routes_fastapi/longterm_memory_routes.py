"""Long-term memory routes — GET/DELETE /api/memory/, POST /api/memory/extract."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .. import config
from ..security_fastapi import get_current_user_id
from ..services.memories import MemoriesService
from ..utils.logging_config import get_logger
from ..utils.workspace import get_scope
from ._authz import deny as _deny
from ._services import memories_service

logger = get_logger(__name__)
router = APIRouter()

_ERR_INTERNAL = "Internal server error"

Memories = Annotated[MemoriesService, Depends(memories_service)]


@router.get("/")
def list_memories(
    request: Request, memories_svc: Memories, limit: int = 100, offset: int = 0
) -> Any:
    denied = _deny(request, None, "viewer")
    if denied:
        return denied
    limit = min(limit, 500)
    offset = max(offset, 0)
    try:
        memories = memories_svc.list_page(limit, offset, get_scope(request))
        return {"success": True, "memories": memories, "count": len(memories)}
    except Exception:
        logger.exception("[Memory] list_memories error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.post("/extract")
async def extract_memories(request: Request, memories_svc: Memories) -> Any:
    denied = _deny(request, None, "editor")
    if denied:
        return denied
    body = await request.json() if await request.body() else {}
    limit = min(int(body.get("limit", 10)), 50)
    app = request.app

    if not app.state.startup_status.get("database", False):
        return JSONResponse({"success": False, "message": "Database not available"}, status_code=503)

    active_model = config.app_state.get_active_model()
    if not active_model:
        return JSONResponse({"success": False, "message": "No active model"}, status_code=400)

    try:
        counts = await memories_svc.extract(
            limit, get_scope(request), active_model, app.state.ollama_client
        )
        return {"success": True, **counts}
    except Exception:
        logger.exception("[Memory] extract_memories error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.delete("/{memory_id}")
def delete_memory(memory_id: str, request: Request, memories_svc: Memories) -> Any:
    denied = _deny(request, None, "editor")
    if denied:
        return denied
    try:
        deleted = memories_svc.retire(memory_id, get_current_user_id(request), get_scope(request))
        if not deleted:
            return JSONResponse({"success": False, "message": "Memory not found"}, status_code=404)
        return {"success": True}
    except Exception:
        logger.exception("[Memory] delete_memory error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.delete("/")
def delete_all_memories(request: Request, memories_svc: Memories) -> Any:
    """Retire every memory in the caller's own workspace. Reversible.

    ``owner``, not ``editor``: clearing a whole workspace's memory is a different
    decision from retiring one memory. It used to retire every user's memories in
    every workspace (C2).
    """
    denied = _deny(request, None, "owner")
    if denied:
        return denied
    try:
        count = memories_svc.retire_all(get_current_user_id(request), get_scope(request))
        return {"success": True, "deleted": count}
    except Exception:
        logger.exception("[Memory] delete_all_memories error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)
