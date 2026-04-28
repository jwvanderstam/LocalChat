"""
Feedback Routes
===============

POST /api/feedback   — submit thumbs-up / thumbs-down for an answer
GET  /api/feedback/stats — rolling quality metrics (admin use)
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request
from flask.typing import ResponseReturnValue

from ..utils.logging_config import get_logger

logger = get_logger(__name__)

bp = Blueprint("feedback", __name__)


@bp.post("/feedback")
def submit_feedback() -> ResponseReturnValue:
    """
    Record user feedback for one assistant answer.

    JSON body:
        rating          int    required  1 (thumbs up) or -1 (thumbs down)
        message_id      int    optional  conversation_messages.id of the assistant turn
        conversation_id str    optional  UUID of the conversation
        feedback_type   str    optional  'answer_quality'|'wrong_sources'|'missing_source'
        correct_doc_ids list   optional  filenames the user says are correct
        source_chunk_ids list  optional  chunk IDs that were in the answer (for chunk_stats)
    """
    app = current_app._get_current_object()  # type: ignore[attr-defined]
    data = request.get_json(silent=True) or {}

    rating = data.get("rating")
    if rating not in (1, -1):
        return jsonify({"error": "rating must be 1 or -1"}), 400

    message_id: int | None = data.get("message_id")
    conversation_id: str | None = data.get("conversation_id")
    feedback_type: str = data.get("feedback_type", "answer_quality")
    correct_doc_ids: list[str] = data.get("correct_doc_ids") or []
    source_chunk_ids: list[int] = data.get("source_chunk_ids") or []

    if not app.startup_status.get("database", False):
        return jsonify({"error": "database unavailable"}), 503

    try:
        feedback_id = app.db.insert_feedback(
            rating,
            message_id=message_id,
            conversation_id=conversation_id,
            feedback_type=feedback_type,
            correct_doc_ids=correct_doc_ids,
        )

        # Update chunk stats for the chunks cited in this answer
        if source_chunk_ids:
            if rating == 1:
                app.db.increment_chunk_positive(source_chunk_ids)
            else:
                app.db.increment_chunk_negative(source_chunk_ids)

        logger.info("[Feedback] Recorded rating and id")
        return jsonify({"ok": True, "id": feedback_id}), 201

    except Exception as exc:
        logger.warning(f"[Feedback] insert_feedback failed: {exc}")
        return jsonify({"error": "could not record feedback"}), 500


@bp.get("/feedback/stats")
def feedback_stats() -> ResponseReturnValue:
    """Return rolling answer-quality metrics for the admin dashboard."""
    app = current_app._get_current_object()  # type: ignore[attr-defined]

    if not app.startup_status.get("database", False):
        return jsonify({"error": "database unavailable"}), 503

    days = request.args.get("days", 7, type=int)
    days = max(1, min(days, 365))

    try:
        stats = app.db.get_feedback_stats(days=days)
        trend = app.db.get_feedback_trend(days=days)
        stale = app.db.get_stale_chunks(limit=20)
        return jsonify({
            "period_days": days,
            "stats": stats,
            "trend": trend,
            "stale_chunks": stale,
        })
    except Exception as exc:
        logger.warning(f"[Feedback] stats query failed: {exc}")
        return jsonify({"error": "could not retrieve stats"}), 500
