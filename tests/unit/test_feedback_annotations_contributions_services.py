"""QP-4's last aggregate: FeedbackService, AnnotationsService, ContributionsService.

The routes keep the guards; these prove what the services decide: a rating credits or
debits its chunks by sign, a chunk outside the scope reads as not found before any
annotation is fetched, and a contribution is refused whole when its workspace or any of
its documents is missing.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.services.annotations import AnnotationsService
from src.services.contributions import ContributionsService
from src.services.errors import ServiceError
from src.services.feedback import FeedbackService
from src.services.workspaces import WorkspacesService

pytestmark = pytest.mark.unit

USER = "33333333-3333-3333-3333-333333333333"
SCOPE = "11111111-1111-1111-1111-111111111111"


class TestFeedback:
    @pytest.mark.parametrize(("rating", "credited", "debited"), [(1, [7, 8], None), (-1, None, [7, 8])])
    def test_a_rating_credits_or_debits_its_chunks_by_sign(self, rating, credited, debited):
        db = MagicMock()
        db.feedback.insert.return_value = "fb-1"
        assert FeedbackService(db).record(rating, 5, "c1", "answer_quality", [], [7, 8]) == "fb-1"
        if credited:
            db.feedback.count_positive.assert_called_once_with(credited)
            db.feedback.count_negative.assert_not_called()
        else:
            db.feedback.count_negative.assert_called_once_with(debited)
            db.feedback.count_positive.assert_not_called()

    def test_no_source_chunks_touches_no_chunk_counters(self):
        db = MagicMock()
        FeedbackService(db).record(1, None, None, "answer_quality", [], [])
        db.feedback.count_positive.assert_not_called()
        db.feedback.count_negative.assert_not_called()

    def test_stats_report_the_period_they_cover(self):
        db = MagicMock()
        db.feedback.stats.return_value = {"total": 3}
        db.feedback.trend.return_value = [{"day": "d"}]
        db.feedback.stale_chunks.return_value = []
        assert FeedbackService(db).stats(14) == {
            "period_days": 14, "stats": {"total": 3}, "trend": [{"day": "d"}], "stale_chunks": [],
        }
        db.feedback.stats.assert_called_once_with(days=14)

    def test_retrain_skips_below_the_minimum_and_promotes_nothing(self):
        db = MagicMock()
        with (
            patch("src.rag.feedback_pipeline.export_training_pairs", return_value=[{}]),
            patch("src.rag.feedback_pipeline.finetune_reranker") as finetune,
            patch("src.rag.feedback_pipeline.promote_model") as promote,
            patch("src.services.feedback.config.FEEDBACK_FINETUNE_MIN_PAIRS", 2),
        ):
            FeedbackService(db).retrain()
        finetune.assert_not_called()
        promote.assert_not_called()

    def test_retrain_promotes_only_a_better_model(self):
        db = MagicMock()
        with (
            patch("src.rag.feedback_pipeline.export_training_pairs", return_value=[{}, {}]),
            patch("src.rag.feedback_pipeline.finetune_reranker",
                  return_value={"ndcg_before": 0.5, "ndcg_after": 0.4}),
            patch("src.rag.feedback_pipeline.persist_reranker_version", return_value="v2"),
            patch("src.rag.feedback_pipeline.promote_model") as promote,
            patch("src.services.feedback.config.FEEDBACK_FINETUNE_MIN_PAIRS", 2),
        ):
            FeedbackService(db).retrain()
        promote.assert_not_called()


class TestAnnotations:
    def test_a_chunk_outside_the_scope_is_none_and_no_annotations_are_read(self):
        db = MagicMock()
        db.documents.chunk_by_id.return_value = None
        assert AnnotationsService(db).for_chunk(9, SCOPE) is None
        db.annotations.for_chunk.assert_not_called()

    def test_a_chunk_in_scope_returns_its_annotations(self):
        db = MagicMock()
        db.documents.chunk_by_id.return_value = {"id": 9}
        db.annotations.for_chunk.return_value = [{"id": "a1"}]
        assert AnnotationsService(db).for_chunk(9, SCOPE) == [{"id": "a1"}]
        db.annotations.for_chunk.assert_called_once_with(9, scope=SCOPE)

    @pytest.mark.parametrize(("caller", "recorded"), [(USER, USER), ("anonymous", None), (None, None)])
    def test_retire_records_the_caller_as_deleted_by(self, caller, recorded):
        db = MagicMock()
        AnnotationsService(db).retire("a1", caller, SCOPE)
        db.annotations.retire.assert_called_once_with("a1", user_id=caller, deleted_by=recorded, scope=SCOPE)


class TestContributions:
    def test_a_missing_workspace_is_404_and_contributes_nothing(self):
        db = MagicMock()
        db.workspaces.get.return_value = None
        with pytest.raises(ServiceError) as refused:
            ContributionsService(db).contribute("ws", [1], USER)
        assert (refused.value.status_code, refused.value.message) == (404, "Workspace not found")
        db.contributions.contribute.assert_not_called()

    def test_a_foreign_document_refuses_the_whole_selection(self):
        db = MagicMock()
        db.workspaces.get.return_value = {"id": "ws"}
        db.contributions.contribute.return_value = None
        with pytest.raises(ServiceError) as refused:
            ContributionsService(db).contribute("ws", [1, 2], USER)
        assert refused.value.status_code == 404

    def test_a_valid_selection_returns_what_was_contributed(self):
        db = MagicMock()
        db.workspaces.get.return_value = {"id": "ws"}
        db.contributions.contribute.return_value = [{"id": 1}]
        assert ContributionsService(db).contribute("ws", [1], USER) == [{"id": 1}]
        db.contributions.contribute.assert_called_once_with("ws", [1], USER)


class TestWorkspaceInsights:
    def test_ontology_is_read_in_the_scope(self):
        db = MagicMock()
        WorkspacesService(db).ontology(20, SCOPE)
        db.entities.workspace_ontology.assert_called_once_with(top_n=20, scope=SCOPE)

    def test_suggestions_are_drawn_from_the_scope(self):
        db = MagicMock()
        with patch("src.rag.active_learning.suggest_documents", return_value=["pricing"]) as suggest:
            assert WorkspacesService(db).suggestions(SCOPE, 5) == ["pricing"]
        suggest.assert_called_once_with(SCOPE, db, top_k=5)
