"""Memory routes — conversation CRUD, export, document filter."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from ..security_fastapi import get_current_user_id, require_admin_dep
from ..utils.logging_config import get_logger
from ..utils.workspace import get_workspace_id

logger = get_logger(__name__)
router = APIRouter()

_CONVERSATION_NOT_FOUND = "Conversation not found"


@router.get("/conversations")
def list_conversations(request: Request, limit: int = 50, offset: int = 0) -> Any:
    try:
        limit = min(limit, 200)
        offset = max(offset, 0)
    except (ValueError, TypeError):
        return JSONResponse({"success": False, "message": "limit and offset must be integers"}, status_code=400)
    conversations = request.app.state.db.list_conversations(
        limit=limit, offset=offset, workspace_id=get_workspace_id(request)
    )
    return {"conversations": conversations, "limit": limit, "offset": offset}


@router.post("/conversations", status_code=201)
async def create_conversation(request: Request) -> Any:
    data = await request.json() if await request.body() else {}
    title = str(data.get("title", "New Conversation"))[:255].strip() or "New Conversation"
    conversation_id = request.app.state.db.create_conversation(title, workspace_id=get_workspace_id(request))
    return JSONResponse({"id": conversation_id, "title": title}, status_code=201)


@router.delete("/conversations")
def delete_all_conversations(request: Request) -> Any:
    actor = get_current_user_id(request)
    deleted_by = actor if actor and actor != "anonymous" else None
    deleted = request.app.state.db.delete_all_conversations(
        workspace_id=get_workspace_id(request), deleted_by=deleted_by
    )
    return {"success": True, "deleted": deleted}


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, request: Request) -> Any:
    messages = request.app.state.db.get_conversation_messages(conversation_id)
    if messages is None:
        return JSONResponse({"error": _CONVERSATION_NOT_FOUND}, status_code=404)
    return {"id": conversation_id, "messages": messages}


def _build_markdown_export(conversation_id: str, messages: list) -> str:
    lines = [f"# Conversation {conversation_id}", ""]
    for msg in messages:
        role_label = "You" if msg["role"] == "user" else "Assistant"
        ts = msg.get("timestamp") or ""
        lines.append(f'### {role_label}{" — " + ts if ts else ""}')
        lines.append("")
        lines.append(msg["content"])
        lines.append("")
    return "\n".join(lines)


def _build_binary_export(fmt: str, title: str, messages: list) -> bytes:
    from ..utils.export import export_conversation_docx, export_conversation_pdf
    if fmt == "docx":
        return export_conversation_docx(title, messages)
    return export_conversation_pdf(title, messages)


@router.get("/conversations/{conversation_id}/export")
def export_conversation(conversation_id: str, request: Request, format: str = "json") -> Any:
    fmt = format.lower()
    if fmt not in ("json", "markdown", "pdf", "docx"):
        return JSONResponse({"error": "Invalid format. Use json, markdown, pdf, or docx."}, status_code=400)

    messages = request.app.state.db.get_conversation_messages(conversation_id)
    if messages is None:
        return JSONResponse({"error": _CONVERSATION_NOT_FOUND}, status_code=404)

    if fmt == "json":
        payload = {"id": conversation_id, "messages": messages}
        return Response(
            json.dumps(payload, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="conversation-{conversation_id}.json"'},
        )

    if fmt == "markdown":
        return Response(
            _build_markdown_export(conversation_id, messages),
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="conversation-{conversation_id}.md"'},
        )

    title = f"Conversation {conversation_id}"
    _mime = {
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pdf": "application/pdf",
    }
    try:
        data = _build_binary_export(fmt, title, messages)
        return Response(
            data,
            media_type=_mime[fmt],
            headers={"Content-Disposition": f'attachment; filename="conversation-{conversation_id}.{fmt}"'},
        )
    except ImportError:
        logger.warning("[Export] optional dependency not installed for format: %s", fmt)
        return JSONResponse({"error": "Export format not available"}, status_code=501)
    except Exception:
        logger.exception("[Export] %s export failed", fmt)
        return JSONResponse({"error": "Export failed"}, status_code=500)


@router.get("/conversations/{conversation_id}/documents")
def get_conversation_documents(conversation_id: str, request: Request) -> Any:
    filenames = request.app.state.db.get_conversation_document_filter(conversation_id)
    if filenames is None:
        return JSONResponse({"error": _CONVERSATION_NOT_FOUND}, status_code=404)
    return {"conversation_id": conversation_id, "document_filter": filenames}


@router.put("/conversations/{conversation_id}/documents")
async def set_conversation_documents(conversation_id: str, request: Request) -> Any:
    data = await request.json() if await request.body() else {}
    filenames = data.get("filenames")
    if not isinstance(filenames, list) or not all(isinstance(f, str) for f in filenames):
        return JSONResponse({"error": '"filenames" must be an array of strings'}, status_code=400)

    updated = request.app.state.db.set_conversation_document_filter(conversation_id, filenames)
    if not updated:
        return JSONResponse({"error": _CONVERSATION_NOT_FOUND}, status_code=404)
    return {"conversation_id": conversation_id, "document_filter": filenames}


@router.patch("/conversations/{conversation_id}")
async def update_conversation(conversation_id: str, request: Request) -> Any:
    data = await request.json() if await request.body() else {}
    title = str(data.get("title", "")).strip()
    if not title:
        return JSONResponse({"error": "Title is required"}, status_code=400)

    updated = request.app.state.db.update_conversation_title(conversation_id, title)
    if not updated:
        return JSONResponse({"error": _CONVERSATION_NOT_FOUND}, status_code=404)
    return {"id": conversation_id, "title": title}


@router.delete("/conversations/{conversation_id}/purge")
def purge_conversation(
    conversation_id: str,
    request: Request,
    _admin: Annotated[str, Depends(require_admin_dep)],
) -> Any:
    purged = request.app.state.db.purge_conversation(conversation_id)
    if not purged:
        return JSONResponse(
            {
                "success": False,
                "message": (
                    "Conversation cannot be purged: one or more memories cite it. "
                    "Remove those memories first or leave the conversation soft-deleted."
                ),
            },
            status_code=409,
        )
    return {"success": True}


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, request: Request) -> Any:
    actor = get_current_user_id(request)
    deleted_by = actor if actor and actor != "anonymous" else None
    deleted = request.app.state.db.delete_conversation(conversation_id, deleted_by=deleted_by)
    if not deleted:
        return JSONResponse({"error": _CONVERSATION_NOT_FOUND}, status_code=404)
    return {"success": True}
