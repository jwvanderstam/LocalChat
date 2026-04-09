"""
Tests for src/db/feedback.py and src/routes/feedback_routes.py

Covers:
  - FeedbackMixin.insert_feedback: valid ratings, invalid rating, DB unavailable
  - FeedbackMixin.increment_chunk_retrieved/positive/negative: upsert calls
  - FeedbackMixin.get_feedback_stats: aggregate shape, unavailable DB
  - FeedbackMixin.get_stale_chunks: DB unavailable returns []
  - FeedbackMixin.get_feedback_trend: DB unavailable returns []
  - FeedbackMixin.export_feedback_pairs: DB unavailable returns []
  - feedback_routes POST /api/feedback: valid, invalid rating, missing DB
  - feedback_routes GET /api/feedback/stats: success, DB unavailable
  - feedback_pipeline: export, write_jsonl, _ndcg_at_k
"""

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(connected=True):
    db = MagicMock()
    db.is_connected = connected
    return db


def _make_app(db=None, db_ok=True):
    app = MagicMock()
    app.db = db or _make_db(connected=db_ok)
    app.startup_status = {"database": db_ok}
    return app


# ===========================================================================
# FeedbackMixin — insert_feedback
# ===========================================================================

class TestInsertFeedback:
    def _mixin(self, connected=True):
        from src.db.feedback import FeedbackMixin
        m = FeedbackMixin()
        m.is_connected = connected
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=MagicMock())
        ctx.__exit__ = MagicMock(return_value=False)
        m.get_connection = MagicMock(return_value=ctx)
        return m

    def test_raises_when_db_unavailable(self):
        from src.db.connection import DatabaseUnavailableError
        m = self._mixin(connected=False)
        with pytest.raises(DatabaseUnavailableError):
            m.insert_feedback(1)

    def test_raises_on_invalid_rating(self):
        m = self._mixin()
        with pytest.raises(ValueError, match="rating must be"):
            m.insert_feedback(0)

    def test_raises_on_invalid_rating_positive(self):
        m = self._mixin()
        with pytest.raises(ValueError):
            m.insert_feedback(2)

    def test_returns_uuid_string(self):
        m = self._mixin()
        result = m.insert_feedback(1, message_id=42, conversation_id="conv-1")
        assert isinstance(result, str)
        uuid.UUID(result)  # must be valid UUID

    def test_thumbs_down_accepted(self):
        m = self._mixin()
        result = m.insert_feedback(-1)
        assert isinstance(result, str)


# ===========================================================================
# FeedbackMixin — chunk stats
# ===========================================================================

class TestChunkStats:
    def _mixin(self, connected=True):
        from src.db.feedback import FeedbackMixin
        m = FeedbackMixin()
        m.is_connected = connected
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=MagicMock())
        ctx.__exit__ = MagicMock(return_value=False)
        m.get_connection = MagicMock(return_value=ctx)
        return m

    def test_increment_retrieved_no_op_when_disconnected(self):
        m = self._mixin(connected=False)
        m.increment_chunk_retrieved([1, 2])
        m.get_connection.assert_not_called()

    def test_increment_retrieved_no_op_on_empty_list(self):
        m = self._mixin()
        m.increment_chunk_retrieved([])
        m.get_connection.assert_not_called()

    def test_increment_retrieved_calls_connection(self):
        m = self._mixin()
        m.increment_chunk_retrieved([10, 11])
        m.get_connection.assert_called_once()

    def test_increment_positive_no_op_when_disconnected(self):
        m = self._mixin(connected=False)
        m.increment_chunk_positive([5])
        m.get_connection.assert_not_called()

    def test_increment_negative_no_op_when_disconnected(self):
        m = self._mixin(connected=False)
        m.increment_chunk_negative([5])
        m.get_connection.assert_not_called()


# ===========================================================================
# FeedbackMixin — read operations
# ===========================================================================

class TestFeedbackReadOps:
    def _mixin_with_result(self, query_result, connected=True):
        from src.db.feedback import FeedbackMixin
        m = FeedbackMixin()
        m.is_connected = connected

        cur = MagicMock()
        cur.fetchone.return_value = query_result[0] if query_result else (0, 0, 0)
        cur.fetchall.return_value = query_result
        cur.description = [("col",)]
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)

        conn = MagicMock()
        conn.cursor.return_value = cur
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)

        m.get_connection = MagicMock(return_value=conn)
        return m

    def test_get_feedback_stats_returns_zero_dict_when_disconnected(self):
        from src.db.feedback import FeedbackMixin
        m = FeedbackMixin()
        m.is_connected = False
        stats = m.get_feedback_stats()
        assert stats["total"] == 0
        assert stats["thumbs_up_rate"] is None

    def test_get_stale_chunks_returns_empty_when_disconnected(self):
        from src.db.feedback import FeedbackMixin
        m = FeedbackMixin()
        m.is_connected = False
        assert m.get_stale_chunks() == []

    def test_get_feedback_trend_returns_empty_when_disconnected(self):
        from src.db.feedback import FeedbackMixin
        m = FeedbackMixin()
        m.is_connected = False
        assert m.get_feedback_trend() == []

    def test_export_feedback_pairs_returns_empty_when_disconnected(self):
        from src.db.feedback import FeedbackMixin
        m = FeedbackMixin()
        m.is_connected = False
        assert m.export_feedback_pairs() == []


# ---------------------------------------------------------------------------
# Route test helpers — use real Flask app context so current_app resolves
# ---------------------------------------------------------------------------

def _make_flask_app(db_ok=True, insert_raises=False, stats=None, trend=None, stale=None):
    """Create a real Flask app with mock db attributes on it directly."""
    from flask import Flask

    from src.routes.feedback_routes import bp

    mock_db = _make_db(connected=db_ok)
    if insert_raises:
        mock_db.insert_feedback.side_effect = Exception("DB error")
    else:
        mock_db.insert_feedback.return_value = str(uuid.uuid4())
    mock_db.get_feedback_stats.return_value = stats or {"total": 0, "positive": 0, "negative": 0, "thumbs_up_rate": None, "by_type": {}}
    mock_db.get_feedback_trend.return_value = trend or []
    mock_db.get_stale_chunks.return_value = stale or []

    flask_app = Flask(__name__)
    flask_app.register_blueprint(bp, url_prefix="/api")
    flask_app.config["TESTING"] = True
    # Attach the mock db and startup_status directly to the Flask app object
    # so current_app._get_current_object() returns this Flask app with these attrs
    flask_app.db = mock_db
    flask_app.startup_status = {"database": db_ok}
    return flask_app


# ===========================================================================
# POST /api/feedback
# ===========================================================================

class TestFeedbackRoute:
    def test_valid_thumbs_up_returns_201(self):
        app = _make_flask_app()
        with app.test_client() as client:
            resp = client.post(
                "/api/feedback",
                data=json.dumps({"rating": 1, "message_id": 42}),
                content_type="application/json",
            )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["ok"] is True
        assert "id" in data

    def test_valid_thumbs_down_returns_201(self):
        app = _make_flask_app()
        with app.test_client() as client:
            resp = client.post("/api/feedback", data=json.dumps({"rating": -1}), content_type="application/json")
        assert resp.status_code == 201

    def test_invalid_rating_returns_400(self):
        app = _make_flask_app()
        with app.test_client() as client:
            resp = client.post("/api/feedback", data=json.dumps({"rating": 0}), content_type="application/json")
        assert resp.status_code == 400

    def test_db_unavailable_returns_503(self):
        app = _make_flask_app(db_ok=False)
        with app.test_client() as client:
            resp = client.post("/api/feedback", data=json.dumps({"rating": 1}), content_type="application/json")
        assert resp.status_code == 503

    def test_db_exception_returns_500(self):
        app = _make_flask_app(insert_raises=True)
        with app.test_client() as client:
            resp = client.post("/api/feedback", data=json.dumps({"rating": 1}), content_type="application/json")
        assert resp.status_code == 500

    def test_positive_increments_chunk_positive(self):
        app = _make_flask_app()
        payload = {"rating": 1, "message_id": 1, "source_chunk_ids": [10, 11]}
        with app.test_client() as client:
            client.post("/api/feedback", data=json.dumps(payload), content_type="application/json")
        app.db.increment_chunk_positive.assert_called_once_with([10, 11])

    def test_negative_increments_chunk_negative(self):
        app = _make_flask_app()
        payload = {"rating": -1, "message_id": 1, "source_chunk_ids": [5]}
        with app.test_client() as client:
            client.post("/api/feedback", data=json.dumps(payload), content_type="application/json")
        app.db.increment_chunk_negative.assert_called_once_with([5])

    def test_no_chunk_ids_no_stat_update(self):
        app = _make_flask_app()
        with app.test_client() as client:
            client.post("/api/feedback", data=json.dumps({"rating": 1}), content_type="application/json")
        app.db.increment_chunk_positive.assert_not_called()


# ===========================================================================
# GET /api/feedback/stats
# ===========================================================================

class TestFeedbackStatsRoute:
    def test_returns_200_with_stats_structure(self):
        app = _make_flask_app(stats={"total": 10, "positive": 7, "negative": 3, "thumbs_up_rate": 0.7, "by_type": {}})
        with app.test_client() as client:
            resp = client.get("/api/feedback/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "stats" in data
        assert "trend" in data
        assert "stale_chunks" in data
        assert "period_days" in data

    def test_db_unavailable_returns_503(self):
        app = _make_flask_app(db_ok=False)
        with app.test_client() as client:
            resp = client.get("/api/feedback/stats")
        assert resp.status_code == 503


# ===========================================================================
# feedback_pipeline helpers
# ===========================================================================

class TestFeedbackPipeline:
    def test_ndcg_at_k_perfect_ranking(self):
        from src.rag.feedback_pipeline import _ndcg_at_k
        assert _ndcg_at_k([1, 1, 0, 0]) == pytest.approx(1.0)

    def test_ndcg_at_k_no_relevant(self):
        from src.rag.feedback_pipeline import _ndcg_at_k
        assert _ndcg_at_k([0, 0, 0]) == 0.0

    def test_ndcg_at_k_worst_ranking(self):
        from src.rag.feedback_pipeline import _ndcg_at_k
        # Relevant items at the end → lower score than perfect
        assert _ndcg_at_k([0, 0, 1, 1]) < 1.0

    def test_export_training_pairs_calls_db(self):
        from src.rag.feedback_pipeline import export_training_pairs
        db = MagicMock()
        db.export_feedback_pairs.return_value = [{"query": "q", "chunk_text": "c", "label": 1}]
        pairs = export_training_pairs(db, days=3)
        db.export_feedback_pairs.assert_called_once_with(days=3)
        assert len(pairs) == 1

    def test_write_jsonl_creates_file(self, tmp_path):
        from src.rag.feedback_pipeline import write_jsonl
        pairs = [{"query": "q1", "chunk_text": "c1", "label": 1}]
        out = tmp_path / "pairs.jsonl"
        write_jsonl(pairs, out)
        lines = out.read_text().strip().split("\n")
        assert len(lines) == 1
        assert json.loads(lines[0]) == pairs[0]

    def test_run_exports_and_returns_count(self):
        from src.rag.feedback_pipeline import run
        db = MagicMock()
        db.export_feedback_pairs.return_value = [
            {"query": "q", "chunk_text": "c", "label": 1}
        ] * 5
        result = run(db, days=7)
        assert result["pairs_exported"] == 5
        assert result["days"] == 7
