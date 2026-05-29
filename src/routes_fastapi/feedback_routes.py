"""Feedback routes — POST /api/feedback, GET /api/feedback/stats."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..utils.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.post("/feedback", status_code=201)
async def submit_feedback(request: Request) -> Any:
    data = await request.json() if await request.body() else {}

    rating = data.get("rating")
    if rating not in (1, -1):
        return JSONResponse({"error": "rating must be 1 or -1"}, status_code=400)

    message_id: int | None = data.get("message_id")
    conversation_id: str | None = data.get("conversation_id")
    feedback_type: str = data.get("feedback_type", "answer_quality")
    correct_doc_ids: list[str] = data.get("correct_doc_ids") or []
    source_chunk_ids: list[int] = data.get("source_chunk_ids") or []

    if not request.app.state.startup_status.get("database", False):
        return JSONResponse({"error": "database unavailable"}, status_code=503)

    try:
        feedback_id = request.app.state.db.insert_feedback(
            rating,
            message_id=message_id,
            conversation_id=conversation_id,
            feedback_type=feedback_type,
            correct_doc_ids=correct_doc_ids,
        )
        if source_chunk_ids:
            if rating == 1:
                request.app.state.db.increment_chunk_positive(source_chunk_ids)
            else:
                request.app.state.db.increment_chunk_negative(source_chunk_ids)
        logger.info("[Feedback] Recorded rating and id")
        return JSONResponse({"ok": True, "id": feedback_id}, status_code=201)
    except Exception as exc:
        logger.warning(f"[Feedback] insert_feedback failed: {exc}")
        return JSONResponse({"error": "could not record feedback"}, status_code=500)


@router.get("/feedback/stats")
def feedback_stats(request: Request, days: int = 7) -> Any:
    days = max(1, min(days, 365))
    if not request.app.state.startup_status.get("database", False):
        return JSONResponse({"error": "database unavailable"}, status_code=503)
    try:
        db = request.app.state.db
        return {
            "period_days": days,
            "stats": db.get_feedback_stats(days=days),
            "trend": db.get_feedback_trend(days=days),
            "stale_chunks": db.get_stale_chunks(limit=20),
        }
    except Exception as exc:
        logger.warning(f"[Feedback] stats query failed: {exc}")
        return JSONResponse({"error": "could not retrieve stats"}, status_code=500)
