"""Long-term memory routes — GET/DELETE /api/memory/, POST /api/memory/extract."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import config
from ..utils.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter()

_ERR_INTERNAL = "Internal server error"


@router.get("/")
def list_memories(request: Request, limit: int = 100, offset: int = 0) -> Any:
    limit = min(limit, 500)
    offset = max(offset, 0)
    try:
        memories = request.app.state.db.get_all_memories(limit=limit, offset=offset)
        return {"success": True, "memories": memories, "count": len(memories)}
    except Exception:
        logger.exception("[Memory] list_memories error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.post("/extract")
async def extract_memories(request: Request) -> Any:
    body = await request.json() if await request.body() else {}
    limit = min(int(body.get("limit", 10)), 50)
    app = request.app

    if not app.state.startup_status.get("database", False):
        return JSONResponse({"success": False, "message": "Database not available"}, status_code=503)

    active_model = config.app_state.get_active_model()
    if not active_model:
        return JSONResponse({"success": False, "message": "No active model"}, status_code=400)

    try:
        from ..memory.extractor import MemoryExtractor
        extractor = MemoryExtractor()
        conversations = app.state.db.get_unextracted_conversations(limit=limit)
        total_new = processed = 0

        for conv in conversations:
            try:
                messages = app.state.db.get_conversation_messages(conv["id"])
                msg_list = []
                for m in messages:
                    if isinstance(m, dict):
                        msg_list.append({"role": m.get("role", ""), "content": m.get("content", "")})
                    elif isinstance(m, (list, tuple)) and len(m) >= 2:
                        msg_list.append({"role": m[0], "content": m[1]})
                total_new += extractor.extract(
                    conversation_id=conv["id"],
                    messages=msg_list,
                    model=active_model,
                    ollama_client=app.state.ollama_client,
                    db=app.state.db,
                )
                processed += 1
            except Exception:
                logger.warning("[Memory] Extraction failed for conv %s", conv["id"], exc_info=True)

        return {"success": True, "conversations_processed": processed, "new_memories": total_new}
    except Exception:
        logger.exception("[Memory] extract_memories error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.delete("/{memory_id}")
def delete_memory(memory_id: str, request: Request) -> Any:
    try:
        request.app.state.db.delete_memory(memory_id)
        return {"success": True}
    except Exception:
        logger.exception("[Memory] delete_memory error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.delete("/")
def delete_all_memories(request: Request) -> Any:
    try:
        count = request.app.state.db.delete_all_memories()
        return {"success": True, "deleted": count}
    except Exception:
        logger.exception("[Memory] delete_all_memories error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)
