"""Workspace routes — CRUD, members, presence SSE, ontology, suggestions."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncGenerator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .. import config
from ..security_fastapi import (
    check_workspace_access,
    get_current_user_id,
    require_admin_dep,
    require_auth,
)
from ..services.errors import ServiceError
from ..services.workspaces import WorkspacesService
from ..utils.logging_config import get_logger
from ..utils.workspace import get_scope, get_workspace_id
from ._authz import deny as _deny
from ._services import workspaces_service

logger = get_logger(__name__)
router = APIRouter()

_NOT_FOUND = "Workspace not found"
_ERR_INTERNAL = "Internal server error"

Workspaces = Annotated[WorkspacesService, Depends(workspaces_service)]

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
def list_workspaces(request: Request, workspaces_svc: Workspaces) -> Any:
    """List the workspaces this caller may actually use; a global admin sees all of them."""
    user_id = require_auth(request)
    try:
        workspaces = workspaces_svc.visible_to(user_id)
        active_id = get_workspace_id(request)
        for ws in workspaces:
            ws["active"] = ws["id"] == active_id
        return {"success": True, "workspaces": workspaces}
    except Exception:
        logger.exception("[Workspaces] list error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.post("/workspaces", status_code=201)
async def create_workspace(request: Request, workspaces_svc: Workspaces) -> Any:
    require_auth(request)
    data = await request.json() if await request.body() else {}
    name = (data.get("name") or "").strip()
    if not name:
        return JSONResponse({"success": False, "message": "name is required"}, status_code=400)
    try:
        workspace = workspaces_svc.create(
            name=name,
            description=data.get("description", ""),
            system_prompt=data.get("system_prompt", ""),
            model_class=data.get("model_class"),
            creator=get_current_user_id(request),
        )
        return JSONResponse({"success": True, "workspace": workspace}, status_code=201)
    except Exception:
        logger.exception("[Workspaces] create error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.get("/workspaces/active")
def get_active_workspace(request: Request, workspaces_svc: Workspaces) -> Any:
    require_auth(request)
    active_id = get_workspace_id(request)
    if not active_id:
        return {"success": True, "workspace": None}
    try:
        workspace = workspaces_svc.get(active_id)
        return {"success": True, "workspace": workspace}
    except Exception:
        logger.exception("[Workspaces] get active error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.post("/workspaces/switch")
async def switch_workspace(request: Request, workspaces_svc: Workspaces) -> Any:
    require_auth(request)
    data = await request.json() if await request.body() else {}
    workspace_id = (data.get("workspace_id") or "").strip()
    if not workspace_id:
        return JSONResponse({"success": False, "message": "workspace_id is required"}, status_code=400)
    try:
        workspace = workspaces_svc.get(workspace_id)
        if workspace is None:
            return JSONResponse({"success": False, "message": _NOT_FOUND}, status_code=404)
        from ..utils.logging_config import sanitize_log_value as _slv
        logger.info("[Workspaces] Switched to workspace: %s (%s)", _slv(workspace["name"]), _slv(workspace_id))
        return {"success": True, "workspace": workspace}
    except Exception:
        logger.exception("[Workspaces] switch error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.get("/workspaces/{workspace_id}")
def get_workspace(workspace_id: str, request: Request, workspaces_svc: Workspaces) -> Any:
    denied = _deny(request, workspace_id, "viewer")
    if denied:
        return denied
    try:
        workspace = workspaces_svc.get(workspace_id)
        if workspace is None:
            return JSONResponse({"success": False, "message": _NOT_FOUND}, status_code=404)
        workspace["active"] = workspace_id == get_workspace_id(request)
        return {"success": True, "workspace": workspace}
    except Exception:
        logger.exception("[Workspaces] get error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.put("/workspaces/{workspace_id}")
async def update_workspace(workspace_id: str, request: Request, workspaces_svc: Workspaces) -> Any:
    denied = _deny(request, workspace_id, "owner")
    if denied:
        return denied
    data = await request.json() if await request.body() else {}
    allowed = {"name", "description", "system_prompt", "model_class"}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return JSONResponse({"success": False, "message": "No valid fields provided"}, status_code=400)
    try:
        workspace = workspaces_svc.update(workspace_id, fields)
        if workspace is None:
            return JSONResponse({"success": False, "message": _NOT_FOUND}, status_code=404)
        return {"success": True, "workspace": workspace}
    except Exception:
        logger.exception("[Workspaces] update error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.delete("/workspaces/{workspace_id}/purge")
def purge_workspace(
    workspace_id: str,
    workspaces_svc: Workspaces,
    _admin: Annotated[str, Depends(require_admin_dep)],
) -> Any:
    try:
        purged = workspaces_svc.purge(workspace_id)
        if not purged:
            return JSONResponse(
                {
                    "success": False,
                    "message": (
                        "Workspace cannot be purged: it still contains active documents "
                        "or conversations. Soft-delete or purge those first."
                    ),
                },
                status_code=409,
            )
        return {"success": True}
    except Exception:
        logger.exception("[Workspaces] purge error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.delete("/workspaces/{workspace_id}")
def delete_workspace(workspace_id: str, request: Request, workspaces_svc: Workspaces) -> Any:
    denied = _deny(request, workspace_id, "owner")
    if denied:
        return denied
    try:
        if not workspaces_svc.retire(workspace_id, actor=get_current_user_id(request)):
            return JSONResponse({"success": False, "message": _NOT_FOUND}, status_code=404)
        return {"success": True, "fallback_workspace_id": workspaces_svc.default_id()}
    except Exception:
        logger.exception("[Workspaces] delete error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.get("/workspaces/{workspace_id}/members")
def list_workspace_members(workspace_id: str, request: Request, workspaces_svc: Workspaces) -> Any:
    denied = _deny(request, workspace_id, "viewer")
    if denied:
        return denied
    try:
        members = workspaces_svc.members(workspace_id)
        return {"success": True, "members": members}
    except Exception:
        logger.exception("[Workspaces] list members error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.post("/workspaces/{workspace_id}/members")
async def add_workspace_member(workspace_id: str, request: Request, workspaces_svc: Workspaces) -> Any:
    denied = _deny(request, workspace_id, "owner")
    if denied:
        return denied
    data = await request.json() if await request.body() else {}
    user_id = (data.get("user_id") or "").strip()
    role = data.get("role", "viewer")
    if not user_id:
        return JSONResponse({"success": False, "message": "user_id is required"}, status_code=400)
    if role not in ("viewer", "editor", "owner"):
        return JSONResponse({"success": False, "message": "role must be viewer, editor, or owner"}, status_code=400)
    try:
        workspaces_svc.set_member(workspace_id, user_id, role)
        return {"success": True}
    except Exception:
        logger.exception("[Workspaces] add member error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.put("/workspaces/{workspace_id}/members/{user_id}")
async def update_workspace_member(
    workspace_id: str, user_id: str, request: Request, workspaces_svc: Workspaces
) -> Any:
    denied = _deny(request, workspace_id, "owner")
    if denied:
        return denied
    data = await request.json() if await request.body() else {}
    role = data.get("role", "")
    if role not in ("viewer", "editor", "owner"):
        return JSONResponse({"success": False, "message": "role must be viewer, editor, or owner"}, status_code=400)
    try:
        workspaces_svc.set_member(workspace_id, user_id, role)
        return {"success": True}
    except Exception:
        logger.exception("[Workspaces] update member error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.delete("/workspaces/{workspace_id}/members/{user_id}")
def remove_workspace_member(
    workspace_id: str, user_id: str, request: Request, workspaces_svc: Workspaces
) -> Any:
    denied = _deny(request, workspace_id, "owner")
    if denied:
        return denied
    try:
        removed = workspaces_svc.remove_member(workspace_id, user_id)
        if not removed:
            return JSONResponse({"success": False, "message": "Member not found"}, status_code=404)
        return {"success": True}
    except ServiceError as exc:
        return JSONResponse({"success": False, "message": exc.message}, status_code=exc.status_code)
    except Exception:
        logger.exception("[Workspaces] remove member error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.get("/workspaces/{workspace_id}/presence")
async def workspace_presence(workspace_id: str, request: Request) -> StreamingResponse:
    # Raised, not returned: this route's contract is a stream, and refusing before
    # the generator starts keeps the failure a plain 403 rather than an SSE error event.
    denial = check_workspace_access(request, workspace_id, "viewer")
    if denial is not None:
        code, message = denial
        raise HTTPException(code, detail={"message": message})
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
def workspace_suggestions(
    workspace_id: str, request: Request, workspaces_svc: Workspaces, top_k: int = 10
) -> Any:
    denied = _deny(request, workspace_id, "viewer")
    if denied:
        return denied
    top_k = min(top_k, 50)
    try:
        suggestions = workspaces_svc.suggestions(get_scope(request), top_k)
        return {"success": True, "workspace_id": workspace_id, "suggestions": suggestions}
    except Exception:
        logger.exception("[Workspaces] suggestions error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.get("/workspaces/{workspace_id}/ontology")
def workspace_ontology(
    workspace_id: str, request: Request, workspaces_svc: Workspaces, top_n: int = 20
) -> Any:
    denied = _deny(request, workspace_id, "viewer")
    if denied:
        return denied
    top_n = min(top_n, 100)
    try:
        ontology = workspaces_svc.ontology(top_n, get_scope(request))
        return {"success": True, "workspace_id": workspace_id, **ontology}
    except Exception:
        logger.exception("[Workspaces] ontology error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


# ── Workspace API keys ─────────────────────────────────────────────────────────
# A key addresses one workspace programmatically: a chatbot bridge, a scheduled
# job, an n8n flow. It is not a user — no password, no session — so it is created,
# used and revoked, and the audit trail names the key rather than borrowing a
# person's account.


@router.get("/workspaces/{workspace_id}/keys")
def list_workspace_keys(workspace_id: str, request: Request, workspaces_svc: Workspaces) -> Any:
    denied = _deny(request, workspace_id, "owner")
    if denied:
        return denied
    try:
        keys = workspaces_svc.keys(workspace_id)
        return {"success": True, "keys": keys}
    except Exception:
        logger.exception("[WorkspaceKeys] list error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.post("/workspaces/{workspace_id}/keys", status_code=201)
async def create_workspace_key(workspace_id: str, request: Request, workspaces_svc: Workspaces) -> Any:
    denied = _deny(request, workspace_id, "owner")
    if denied:
        return denied
    data = await request.json() if await request.body() else {}
    name = (data.get("name") or "").strip()
    role = data.get("role", "viewer")
    if not name:
        return JSONResponse({"success": False, "message": "name is required"}, status_code=400)
    # owner is deliberately not offered: a key that can hand out further keys turns
    # one leaked credential into permanent control of the workspace.
    if role not in ("viewer", "editor"):
        return JSONResponse(
            {"success": False, "message": "role must be viewer or editor"}, status_code=400
        )
    try:
        full_key, row = workspaces_svc.create_key(
            workspace_id, name, role, creator=get_current_user_id(request)
        )
        # The only time the plaintext key exists outside the caller's hands.
        return JSONResponse({"success": True, "key": full_key, "info": row}, status_code=201)
    except Exception:
        logger.exception("[WorkspaceKeys] create error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.delete("/workspaces/{workspace_id}/keys/{key_id}")
def revoke_workspace_key(
    workspace_id: str, key_id: str, request: Request, workspaces_svc: Workspaces
) -> Any:
    denied = _deny(request, workspace_id, "owner")
    if denied:
        return denied
    try:
        revoked = workspaces_svc.revoke_key(
            workspace_id, key_id, actor=get_current_user_id(request)
        )
        if not revoked:
            return JSONResponse({"success": False, "message": "Key not found"}, status_code=404)
        return {"success": True}
    except Exception:
        logger.exception("[WorkspaceKeys] revoke error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)
