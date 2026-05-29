"""Workspace routes — CRUD, members, presence SSE, ontology, suggestions."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .. import config
from ..security_fastapi import get_current_user_id
from ..utils.logging_config import get_logger
from ..utils.workspace import get_workspace_id

logger = get_logger(__name__)
router = APIRouter()

_NOT_FOUND = "Workspace not found"
_ERR_INTERNAL = "Internal server error"
_ERR_FORBIDDEN = "Only workspace owners can perform this action"

# In-process presence store: workspace_id → {user_id → expires_at (epoch float)}
_presence: dict[str, dict[str, float]] = {}


def _presence_event(workspace_id: str, user_id: str | None) -> str:
    now = time.time()
    bucket = _presence.setdefault(workspace_id, {})
    if user_id:
        bucket[user_id] = now + config.PRESENCE_TTL_SECONDS
    expired = [uid for uid, exp in bucket.items() if exp < now]
    for uid in expired:
        del bucket[uid]
    payload = json.dumps({"users": list(bucket.keys()), "count": len(bucket)})
    return f"data: {payload}\n\n"


@router.get("/workspaces")
def list_workspaces(request: Request) -> Any:
    try:
        workspaces = request.app.state.db.list_workspaces()
        active_id = get_workspace_id(request)
        for ws in workspaces:
            ws["active"] = ws["id"] == active_id
        return {"success": True, "workspaces": workspaces}
    except Exception as exc:
        logger.error("[Workspaces] list error: %s", exc, exc_info=True)
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.post("/workspaces", status_code=201)
async def create_workspace(request: Request) -> Any:
    data = await request.json() if await request.body() else {}
    name = (data.get("name") or "").strip()
    if not name:
        return JSONResponse({"success": False, "message": "name is required"}, status_code=400)
    try:
        db = request.app.state.db
        workspace_id = db.create_workspace(
            name=name,
            description=data.get("description", ""),
            system_prompt=data.get("system_prompt", ""),
            model_class=data.get("model_class"),
        )
        workspace = db.get_workspace(workspace_id)
        return JSONResponse({"success": True, "workspace": workspace}, status_code=201)
    except Exception as exc:
        logger.error("[Workspaces] create error: %s", exc, exc_info=True)
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.get("/workspaces/active")
def get_active_workspace(request: Request) -> Any:
    active_id = get_workspace_id(request)
    if not active_id:
        return {"success": True, "workspace": None}
    try:
        workspace = request.app.state.db.get_workspace(active_id)
        return {"success": True, "workspace": workspace}
    except Exception as exc:
        logger.error("[Workspaces] get active error: %s", exc, exc_info=True)
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.post("/workspaces/switch")
async def switch_workspace(request: Request) -> Any:
    data = await request.json() if await request.body() else {}
    workspace_id = (data.get("workspace_id") or "").strip()
    if not workspace_id:
        return JSONResponse({"success": False, "message": "workspace_id is required"}, status_code=400)
    try:
        workspace = request.app.state.db.get_workspace(workspace_id)
        if workspace is None:
            return JSONResponse({"success": False, "message": _NOT_FOUND}, status_code=404)
        from ..utils.logging_config import sanitize_log_value as _slv
        logger.info("[Workspaces] Switched to workspace: %s (%s)", _slv(workspace["name"]), _slv(workspace_id))
        return {"success": True, "workspace": workspace}
    except Exception as exc:
        logger.error("[Workspaces] switch error: %s", exc, exc_info=True)
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.get("/workspaces/{workspace_id}")
def get_workspace(workspace_id: str, request: Request) -> Any:
    try:
        workspace = request.app.state.db.get_workspace(workspace_id)
        if workspace is None:
            return JSONResponse({"success": False, "message": _NOT_FOUND}, status_code=404)
        workspace["active"] = workspace_id == get_workspace_id(request)
        return {"success": True, "workspace": workspace}
    except Exception as exc:
        logger.error("[Workspaces] get error: %s", exc, exc_info=True)
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.put("/workspaces/{workspace_id}")
async def update_workspace(workspace_id: str, request: Request) -> Any:
    data = await request.json() if await request.body() else {}
    allowed = {"name", "description", "system_prompt", "model_class"}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return JSONResponse({"success": False, "message": "No valid fields provided"}, status_code=400)
    try:
        db = request.app.state.db
        updated = db.update_workspace(workspace_id, **fields)
        if not updated:
            return JSONResponse({"success": False, "message": _NOT_FOUND}, status_code=404)
        return {"success": True, "workspace": db.get_workspace(workspace_id)}
    except Exception as exc:
        logger.error("[Workspaces] update error: %s", exc, exc_info=True)
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.delete("/workspaces/{workspace_id}")
def delete_workspace(workspace_id: str, request: Request) -> Any:
    caller = get_current_user_id(request) or "admin"
    db = request.app.state.db
    role = db.get_workspace_member_role(workspace_id, caller)
    if role is not None and role != "owner":
        return JSONResponse({"success": False, "message": _ERR_FORBIDDEN}, status_code=403)
    try:
        deleted = db.delete_workspace(workspace_id)
        if not deleted:
            return JSONResponse({"success": False, "message": _NOT_FOUND}, status_code=404)
        fallback_id = db.get_default_workspace_id()
        return {"success": True, "fallback_workspace_id": fallback_id}
    except Exception as exc:
        logger.error("[Workspaces] delete error: %s", exc, exc_info=True)
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.get("/workspaces/{workspace_id}/members")
def list_workspace_members(workspace_id: str, request: Request) -> Any:
    try:
        members = request.app.state.db.list_workspace_members(workspace_id)
        return {"success": True, "members": members}
    except Exception as exc:
        logger.error("[Workspaces] list members error: %s", exc, exc_info=True)
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.post("/workspaces/{workspace_id}/members")
async def add_workspace_member(workspace_id: str, request: Request) -> Any:
    data = await request.json() if await request.body() else {}
    user_id = (data.get("user_id") or "").strip()
    role = data.get("role", "viewer")
    if not user_id:
        return JSONResponse({"success": False, "message": "user_id is required"}, status_code=400)
    if role not in ("viewer", "editor", "owner"):
        return JSONResponse({"success": False, "message": "role must be viewer, editor, or owner"}, status_code=400)
    try:
        request.app.state.db.add_workspace_member(workspace_id, user_id, role)
        return {"success": True}
    except Exception as exc:
        logger.error("[Workspaces] add member error: %s", exc, exc_info=True)
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.put("/workspaces/{workspace_id}/members/{user_id}")
async def update_workspace_member(workspace_id: str, user_id: str, request: Request) -> Any:
    caller = get_current_user_id(request) or "admin"
    role_check = request.app.state.db.get_workspace_member_role(workspace_id, caller)
    if role_check is not None and role_check != "owner":
        return JSONResponse({"success": False, "message": _ERR_FORBIDDEN}, status_code=403)
    data = await request.json() if await request.body() else {}
    role = data.get("role", "")
    if role not in ("viewer", "editor", "owner"):
        return JSONResponse({"success": False, "message": "role must be viewer, editor, or owner"}, status_code=400)
    try:
        request.app.state.db.add_workspace_member(workspace_id, user_id, role)
        return {"success": True}
    except Exception as exc:
        logger.error("[Workspaces] update member error: %s", exc, exc_info=True)
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.delete("/workspaces/{workspace_id}/members/{user_id}")
def remove_workspace_member(workspace_id: str, user_id: str, request: Request) -> Any:
    caller = get_current_user_id(request) or "admin"
    role_check = request.app.state.db.get_workspace_member_role(workspace_id, caller)
    if role_check is not None and role_check != "owner":
        return JSONResponse({"success": False, "message": _ERR_FORBIDDEN}, status_code=403)
    try:
        removed = request.app.state.db.remove_workspace_member(workspace_id, user_id)
        if not removed:
            return JSONResponse({"success": False, "message": "Member not found"}, status_code=404)
        return {"success": True}
    except ValueError as ve:
        return JSONResponse({"success": False, "message": str(ve)}, status_code=409)
    except Exception as exc:
        logger.error("[Workspaces] remove member error: %s", exc, exc_info=True)
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.get("/workspaces/{workspace_id}/presence")
async def workspace_presence(workspace_id: str, request: Request) -> StreamingResponse:
    user_id = get_current_user_id(request)
    heartbeat = config.PRESENCE_TTL_SECONDS

    async def _generate() -> AsyncGenerator[str, None]:
        try:
            yield _presence_event(workspace_id, user_id)
            while True:
                # Use asyncio sleep to avoid blocking the event loop
                import asyncio
                await asyncio.sleep(heartbeat)
                yield _presence_event(workspace_id, user_id)
        finally:
            bucket = _presence.get(workspace_id, {})
            if user_id and user_id in bucket:
                del bucket[user_id]

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/workspaces/{workspace_id}/suggestions")
def workspace_suggestions(workspace_id: str, request: Request, top_k: int = 10) -> Any:
    top_k = min(top_k, 50)
    try:
        from ..rag.active_learning import suggest_documents
        suggestions = suggest_documents(workspace_id, request.app.state.db, top_k=top_k)
        return {"success": True, "workspace_id": workspace_id, "suggestions": suggestions}
    except Exception as exc:
        logger.error("[Workspaces] suggestions error: %s", exc, exc_info=True)
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.get("/workspaces/{workspace_id}/ontology")
def workspace_ontology(workspace_id: str, request: Request, top_n: int = 20) -> Any:
    top_n = min(top_n, 100)
    try:
        ontology = request.app.state.db.get_workspace_ontology(workspace_id, top_n=top_n)
        return {"success": True, "workspace_id": workspace_id, **ontology}
    except Exception as exc:
        logger.error("[Workspaces] ontology error: %s", exc, exc_info=True)
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)
