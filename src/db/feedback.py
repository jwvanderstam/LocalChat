"""
Feedback Operations Module
==========================

Mixin providing CRUD for the ``answer_feedback`` and ``chunk_stats`` tables.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from ..utils.logging_config import get_logger
from .connection import DatabaseUnavailableError

if TYPE_CHECKING:
    from .connection import DatabaseConnection

logger = get_logger(__name__)


class FeedbackMixin:
    """Mixin that adds answer-feedback and chunk-stats operations to the Database class."""

    is_connected: bool
    get_connection: DatabaseConnection.get_connection  # type: ignore[assignment]

    # ── Feedback write operations ──────────────────────────────────────────────

    def insert_feedback(
        self,
        rating: int,
        *,
        message_id: int | None = None,
        conversation_id: str | None = None,
        feedback_type: str = "answer_quality",
        correct_doc_ids: list[str] | None = None,
    ) -> str:
        """
        Record a thumbs-up (rating=1) or thumbs-down (rating=-1) for one answer.

        Args:
            rating: 1 (positive) or -1 (negative).
            message_id: FK to conversation_messages.id (assistant turn).
            conversation_id: UUID string of the conversation.
            feedback_type: One of 'answer_quality', 'wrong_sources', 'missing_source'.
            correct_doc_ids: User-indicated correct document filenames (optional).

        Returns:
            UUID string of the inserted feedback row.
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot insert feedback: Database not connected")

        if rating not in (1, -1):
            raise ValueError(f"rating must be 1 or -1, got {rating!r}")

        feedback_id = str(uuid.uuid4())
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO answer_feedback
                        (id, message_id, conversation_id, rating, feedback_type, correct_doc_ids)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        feedback_id,
                        message_id,
                        conversation_id,
                        rating,
                        feedback_type,
                        correct_doc_ids or None,  # psycopg3 can't infer type from []
                    ),
                )
            conn.commit()
        logger.debug(f"[Feedback] Inserted feedback {feedback_id}: rating={rating}")
        return feedback_id

    # ── Chunk stats write operations ───────────────────────────────────────────

    def increment_chunk_retrieved(self, chunk_ids: list[int]) -> None:
        """Increment retrieved_count for each chunk in *chunk_ids* (upsert)."""
        if not self.is_connected or not chunk_ids:
            return
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO chunk_stats (chunk_id, retrieved_count, last_retrieved_at)
                    VALUES (%s, 1, NOW())
                    ON CONFLICT (chunk_id) DO UPDATE
                        SET retrieved_count    = chunk_stats.retrieved_count + 1,
                            last_retrieved_at  = NOW()
                    """,
                    [(cid,) for cid in chunk_ids],
                )
            conn.commit()

    def increment_chunk_positive(self, chunk_ids: list[int]) -> None:
        """Increment positive_feedback_count for each chunk (upsert)."""
        if not self.is_connected or not chunk_ids:
            return
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO chunk_stats (chunk_id, positive_feedback_count)
                    VALUES (%s, 1)
                    ON CONFLICT (chunk_id) DO UPDATE
                        SET positive_feedback_count =
                            chunk_stats.positive_feedback_count + 1
                    """,
                    [(cid,) for cid in chunk_ids],
                )
            conn.commit()

    def increment_chunk_negative(self, chunk_ids: list[int]) -> None:
        """Increment negative_feedback_count for each chunk (upsert)."""
        if not self.is_connected or not chunk_ids:
            return
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO chunk_stats (chunk_id, negative_feedback_count)
                    VALUES (%s, 1)
                    ON CONFLICT (chunk_id) DO UPDATE
                        SET negative_feedback_count =
                            chunk_stats.negative_feedback_count + 1
                    """,
                    [(cid,) for cid in chunk_ids],
                )
            conn.commit()

    # ── Feedback read operations ───────────────────────────────────────────────

    def get_feedback_stats(self, days: int = 7) -> dict[str, Any]:
        """
        Return aggregate feedback metrics for the past *days* days.

        Returns a dict with:
          - total: total feedback rows
          - positive: count of rating=1
          - negative: count of rating=-1
          - thumbs_up_rate: positive / total (None when total=0)
          - by_type: {feedback_type: count}
        """
        if not self.is_connected:
            return {"total": 0, "positive": 0, "negative": 0, "thumbs_up_rate": None, "by_type": {}}

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(*)                                   AS total,
                        COUNT(*) FILTER (WHERE rating =  1)        AS positive,
                        COUNT(*) FILTER (WHERE rating = -1)        AS negative
                    FROM answer_feedback
                    WHERE created_at >= NOW() - INTERVAL '%s days'
                    """,
                    (days,),
                )
                row = cur.fetchone()
                total, positive, negative = (row[0] or 0, row[1] or 0, row[2] or 0)

                cur.execute(
                    """
                    SELECT feedback_type, COUNT(*) AS cnt
                    FROM answer_feedback
                    WHERE created_at >= NOW() - INTERVAL '%s days'
                    GROUP BY feedback_type
                    ORDER BY cnt DESC
                    """,
                    (days,),
                )
                by_type = {r[0]: r[1] for r in cur.fetchall()}

        thumbs_up_rate = round(positive / total, 3) if total else None
        return {
            "total": total,
            "positive": positive,
            "negative": negative,
            "thumbs_up_rate": thumbs_up_rate,
            "by_type": by_type,
        }

    def get_stale_chunks(
        self,
        min_retrieved: int = 10,
        max_positive_ratio: float = 0.10,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Return chunks with high retrieval frequency but very low positive feedback —
        candidates for review, update, or re-ingestion.
        """
        if not self.is_connected:
            return []

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        cs.chunk_id,
                        cs.retrieved_count,
                        cs.positive_feedback_count,
                        cs.negative_feedback_count,
                        cs.last_retrieved_at,
                        dc.chunk_index,
                        d.filename
                    FROM chunk_stats cs
                    JOIN document_chunks dc ON dc.id = cs.chunk_id
                    JOIN documents d ON d.id = dc.document_id
                    WHERE cs.retrieved_count >= %s
                      AND (
                        cs.retrieved_count = 0
                        OR cs.positive_feedback_count::float / cs.retrieved_count <= %s
                      )
                    ORDER BY cs.retrieved_count DESC
                    LIMIT %s
                    """,
                    (min_retrieved, max_positive_ratio, limit),
                )
                cols = [desc[0] for desc in cur.description]
                return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def get_feedback_trend(self, days: int = 30) -> list[dict[str, Any]]:
        """
        Return rolling thumbs-up counts bucketed by *bucket_days* for charting.
        Each element: {bucket_start: date-string, positive: int, negative: int}.
        """
        if not self.is_connected:
            return []

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        date_trunc('day', created_at)::date            AS day,
                        COUNT(*) FILTER (WHERE rating =  1)            AS positive,
                        COUNT(*) FILTER (WHERE rating = -1)            AS negative
                    FROM answer_feedback
                    WHERE created_at >= NOW() - INTERVAL '%s days'
                    GROUP BY day
                    ORDER BY day
                    """,
                    (days,),
                )
                return [
                    {"day": str(r[0]), "positive": r[1], "negative": r[2]}
                    for r in cur.fetchall()
                ]

    def export_feedback_pairs(self, days: int = 7) -> list[dict[str, Any]]:
        """
        Export (query, chunk_text, label) triples for reranker fine-tuning.

        label = 1 for chunks cited in positively-rated answers,
                0 for chunks cited in negatively-rated answers.
        """
        if not self.is_connected:
            return []

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        cm_user.content   AS query,
                        dc.chunk_text     AS chunk_text,
                        CASE WHEN af.rating = 1 THEN 1 ELSE 0 END AS label
                    FROM answer_feedback af
                    JOIN conversation_messages cm_asst
                        ON cm_asst.id = af.message_id
                    JOIN conversation_messages cm_user
                        ON cm_user.conversation_id = cm_asst.conversation_id
                        AND cm_user.role = 'user'
                        AND cm_user.id = (
                            SELECT id FROM conversation_messages
                            WHERE conversation_id = cm_asst.conversation_id
                              AND role = 'user'
                              AND id < cm_asst.id
                            ORDER BY id DESC
                            LIMIT 1
                        )
                    JOIN chunk_stats cs ON TRUE
                    JOIN document_chunks dc ON dc.id = cs.chunk_id
                    WHERE af.created_at >= NOW() - INTERVAL '%s days'
                    ORDER BY af.created_at DESC
                    LIMIT 10000
                    """,
                    (days,),
                )
                cols = [desc[0] for desc in cur.description]
                return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def get_reranker_versions(self) -> list[dict[str, Any]]:
        """Return all reranker version rows ordered by trained_at DESC."""
        if not self.is_connected:
            return []
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, trained_at, base_model, ndcg_before, ndcg_after, "
                        "pair_count, model_path, active FROM reranker_versions ORDER BY trained_at DESC"
                    )
                    rows = cur.fetchall()
            return [
                {
                    'id': str(r[0]),
                    'trained_at': r[1].isoformat() if r[1] else None,
                    'base_model': r[2],
                    'ndcg_before': r[3],
                    'ndcg_after': r[4],
                    'pair_count': r[5],
                    'model_path': r[6],
                    'active': r[7],
                }
                for r in rows
            ]
        except Exception as exc:
            logger.warning(f"[Reranker] version query failed: {exc}")
            return []
