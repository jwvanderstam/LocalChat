"""Feedback routes — POST /api/feedback, GET /api/feedback/stats."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ..models import FeedbackRequest
from ..security_fastapi import check_knowledge_scope_access, require_admin_dep
from ..services.feedback import FeedbackService
from ..utils.logging_config import get_logger
from ..utils.workspace import get_scope
from ._authz import deny as _deny
from ._services import feedback_service

logger = get_logger(__name__)

router = APIRouter()

Feedback = Annotated[FeedbackService, Depends(feedback_service)]


@router.post("/feedback", status_code=201)
async def submit_feedback(request: Request, feedback: Feedback) -> Any:
    denied = _deny(request, None, "viewer")
    if denied:
        return denied
    data = await request.json() if await request.body() else {}
    try:
        body = FeedbackRequest.model_validate(data)
    except ValidationError as exc:
        field = str(exc.errors()[0]["loc"][0]) if exc.errors()[0]["loc"] else "body"
        message = "rating must be 1 or -1" if field == "rating" else f"{field} is invalid"
        return JSONResponse({"error": message}, status_code=400)

    rating = body.rating
    message_id = body.message_id
    conversation_id = body.conversation_id
    feedback_type = body.feedback_type
    correct_doc_ids = body.correct_doc_ids or []
    source_chunk_ids = body.source_chunk_ids or []

    if not request.app.state.startup_status.get("database", False):
        return JSONResponse({"error": "database unavailable"}, status_code=503)

    try:
        feedback_id = feedback.record(
            rating, message_id, conversation_id, feedback_type, correct_doc_ids, source_chunk_ids,
            get_scope(request), check_knowledge_scope_access(request, "global") is None,
        )
        if feedback_id is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        logger.info("[Feedback] Recorded rating and id")
        return JSONResponse({"ok": True, "id": feedback_id}, status_code=201)
    except Exception as exc:  # noqa: BLE001 — turned into a 500 with a fixed message — the exception text is never shown to the caller
        logger.warning(f"[Feedback] insert_feedback failed: {exc}")
        return JSONResponse({"error": "could not record feedback"}, status_code=500)


@router.get("/feedback/stats")
def feedback_stats(
    request: Request,
    feedback: Feedback,
    _admin: Annotated[str, Depends(require_admin_dep)],
    days: int = 7,
) -> Any:
    days = max(1, min(days, 365))
    if not request.app.state.startup_status.get("database", False):
        return JSONResponse({"error": "database unavailable"}, status_code=503)
    try:
        return feedback.stats(days)
    except Exception as exc:  # noqa: BLE001 — same for the stats query
        logger.warning(f"[Feedback] stats query failed: {exc}")
        return JSONResponse({"error": "could not retrieve stats"}, status_code=500)
