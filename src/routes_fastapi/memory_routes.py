"""Memory routes — conversation CRUD, export, document filter."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

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
    deleted = request.app.state.db.delete_all_conversations(workspace_id=get_workspace_id(request))
    return {"success": True, "deleted": deleted}


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, request: Request) -> Any:
    messages = request.app.state.db.get_conversation_messages(conversation_id)
    if messages is None:
        return JSONResponse({"error": _CONVERSATION_NOT_FOUND}, status_code=404)
    return {"id": conversation_id, "messages": messages}


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
        lines = [f"# Conversation {conversation_id}", ""]
        for msg in messages:
            role_label = "You" if msg["role"] == "user" else "Assistant"
            ts = msg.get("timestamp") or ""
            lines.append(f'### {role_label}{" — " + ts if ts else ""}')
            lines.append("")
            lines.append(msg["content"])
            lines.append("")
        return Response(
            "\n".join(lines),
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="conversation-{conversation_id}.md"'},
        )

    title = f"Conversation {conversation_id}"
    from ..utils.export import export_conversation_docx, export_conversation_pdf
    try:
        if fmt == "docx":
            data = export_conversation_docx(title, messages)
            return Response(
                data,
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                headers={"Content-Disposition": f'attachment; filename="conversation-{conversation_id}.docx"'},
            )
        data = export_conversation_pdf(title, messages)
        return Response(
            data,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="conversation-{conversation_id}.pdf"'},
        )
    except ImportError as ie:
        return JSONResponse({"error": str(ie)}, status_code=501)
    except Exception as exc:
        logger.error("[Export] %s export failed: %s", fmt, exc, exc_info=True)
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


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, request: Request) -> Any:
    deleted = request.app.state.db.delete_conversation(conversation_id)
    if not deleted:
        return JSONResponse({"error": _CONVERSATION_NOT_FOUND}, status_code=404)
    return {"success": True}
