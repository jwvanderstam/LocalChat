"""Answer feedback and the reranker it trains: the use cases behind two route modules.

QP-4's last aggregate. ``feedback_routes`` records ratings and reads their statistics;
``settings_routes`` lists, promotes, rolls back and retrains reranker versions. Who may
call is the route's ``deny()`` or ``require_admin_dep``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .. import config
from ..utils.logging_config import get_logger

if TYPE_CHECKING:
    from ..db import Database

logger = get_logger(__name__)


class FeedbackService:
    """Ratings, their statistics, and reranker versions over one database."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def record(
        self,
        rating: int,
        message_id: int | None,
        conversation_id: str | None,
        feedback_type: str,
        correct_doc_ids: list[str],
        source_chunk_ids: list[int],
    ) -> str:
        """Store a rating and credit or debit the chunks it was about; returns its id."""
        feedback_id = self._db.feedback.insert(
            rating,
            message_id=message_id,
            conversation_id=conversation_id,
            feedback_type=feedback_type,
            correct_doc_ids=correct_doc_ids,
        )
        if source_chunk_ids:
            if rating == 1:
                self._db.feedback.count_positive(source_chunk_ids)
            else:
                self._db.feedback.count_negative(source_chunk_ids)
        return feedback_id

    def stats(self, days: int) -> dict[str, Any]:
        return {
            "period_days": days,
            "stats": self._db.feedback.stats(days=days),
            "trend": self._db.feedback.trend(days=days),
            "stale_chunks": self._db.feedback.stale_chunks(limit=20),
        }

    def reranker_versions(self) -> list[dict[str, Any]]:
        return self._db.feedback.reranker_versions()

    def promote(self, version_id: str) -> bool:
        from ..rag.feedback_pipeline import promote_model

        return promote_model(self._db, version_id)

    def rollback(self, version_id: str) -> bool:
        from ..rag.feedback_pipeline import rollback_model

        return rollback_model(self._db, version_id)

    def retrain(self) -> None:
        """Fine-tune on the last 30 days of feedback and promote the result if it scores better.

        Blocking: the route runs it on a background thread.
        """
        try:
            from ..rag.feedback_pipeline import (
                export_training_pairs,
                finetune_reranker,
                persist_reranker_version,
                promote_model,
            )
            pairs = export_training_pairs(self._db, days=30)
            if len(pairs) < config.FEEDBACK_FINETUNE_MIN_PAIRS:
                logger.info("[Reranker] Only %d pairs — skipping fine-tune", len(pairs))
                return
            result = finetune_reranker(pairs)
            if not result.get("skipped"):
                version_id = persist_reranker_version(self._db, result)
                if version_id and result.get("ndcg_after", 0) > result.get("ndcg_before", 0):
                    promote_model(self._db, version_id)
        except Exception:
            logger.exception("[Reranker] Background training failed")
