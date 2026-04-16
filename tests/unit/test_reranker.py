"""
Tests for src/rag/reranker.py

Covers:
  - RerankerModel.is_available: True when model loaded, False when not
  - RerankerModel.score: happy path, empty passages, model unavailable, predict error
  - _load: falls back to base model when fine-tuned path fails
  - _load: no-op when sentence-transformers absent
  - _resolve_model_path: returns None when no paths resolve
  - get_reranker: returns singleton
  - reload_reranker: forces a fresh instance
  - _to_safe_path / _read_latest_pointer: path helpers
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.rag.reranker import (
    RerankerModel,
    _read_latest_pointer,
    _to_safe_path,
    get_reranker,
    reload_reranker,
)

# ===========================================================================
# Path helpers
# ===========================================================================

class TestToSafePath:
    def test_empty_string_returns_none(self):
        assert _to_safe_path("") is None

    def test_null_byte_returns_none(self):
        assert _to_safe_path("some\x00path") is None

    def test_nonexistent_path_returns_none(self, tmp_path):
        assert _to_safe_path(str(tmp_path / "nonexistent")) is None

    def test_existing_path_is_returned(self, tmp_path):
        result = _to_safe_path(str(tmp_path))
        assert result is not None


class TestReadLatestPointer:
    def test_no_txt_file_returns_none(self, tmp_path):
        cfg = str(tmp_path / "model" / "config.json")
        assert _read_latest_pointer(cfg) is None

    def test_reads_pointed_path(self, tmp_path):
        txt_file = tmp_path / "model.txt"
        txt_file.write_text("/some/model/path")
        cfg = str(tmp_path / "model.json")
        result = _read_latest_pointer(cfg)
        assert result == "/some/model/path"

    def test_empty_txt_file_returns_none(self, tmp_path):
        txt_file = tmp_path / "model.txt"
        txt_file.write_text("   ")
        cfg = str(tmp_path / "model.json")
        assert _read_latest_pointer(cfg) is None


# ===========================================================================
# RerankerModel — sentence-transformers absent
# ===========================================================================

class TestRerankerModelNoSentenceTransformers:
    def test_is_not_available_when_import_fails(self):
        with patch.dict("sys.modules", {"sentence_transformers": None}):
            m = RerankerModel()
        assert m.is_available() is False

    def test_score_returns_empty_when_unavailable(self):
        with patch.dict("sys.modules", {"sentence_transformers": None}):
            m = RerankerModel()
        assert m.score("query", ["passage one"]) == []


# ===========================================================================
# RerankerModel — sentence-transformers present
# ===========================================================================

class TestRerankerModelWithCrossEncoder:
    def _make_mock_cross_encoder_cls(self, predict_return=None):
        """Return a mock CrossEncoder class whose instances return predict_return."""
        mock_instance = MagicMock()
        mock_instance.predict.return_value = predict_return or [0.9, 0.4]
        mock_cls = MagicMock(return_value=mock_instance)
        return mock_cls, mock_instance

    def test_loads_base_model_and_is_available(self):
        mock_cls, _ = self._make_mock_cross_encoder_cls()
        mock_st = MagicMock()
        mock_st.CrossEncoder = mock_cls
        with patch.dict("sys.modules", {"sentence_transformers": mock_st}):
            m = RerankerModel()
        assert m.is_available() is True

    def test_score_returns_float_list(self):
        mock_cls, mock_instance = self._make_mock_cross_encoder_cls([0.9, 0.3])
        mock_st = MagicMock()
        mock_st.CrossEncoder = mock_cls
        with patch.dict("sys.modules", {"sentence_transformers": mock_st}):
            m = RerankerModel()
        scores = m.score("what is X?", ["passage A", "passage B"])
        assert scores == [0.9, 0.3]

    def test_score_calls_predict_with_pairs(self):
        mock_cls, mock_instance = self._make_mock_cross_encoder_cls([0.5])
        mock_st = MagicMock()
        mock_st.CrossEncoder = mock_cls
        with patch.dict("sys.modules", {"sentence_transformers": mock_st}):
            m = RerankerModel()
        m.score("query", ["p1"])
        mock_instance.predict.assert_called_once_with([("query", "p1")])

    def test_score_returns_empty_for_empty_passages(self):
        mock_cls, _ = self._make_mock_cross_encoder_cls()
        mock_st = MagicMock()
        mock_st.CrossEncoder = mock_cls
        with patch.dict("sys.modules", {"sentence_transformers": mock_st}):
            m = RerankerModel()
        assert m.score("query", []) == []

    def test_score_returns_empty_when_predict_raises(self):
        mock_cls, mock_instance = self._make_mock_cross_encoder_cls()
        mock_instance.predict.side_effect = RuntimeError("GPU OOM")
        mock_st = MagicMock()
        mock_st.CrossEncoder = mock_cls
        with patch.dict("sys.modules", {"sentence_transformers": mock_st}):
            m = RerankerModel()
        assert m.score("query", ["p1"]) == []

    def test_falls_back_to_base_when_fine_tuned_fails(self, tmp_path):
        """Fine-tuned model path exists but CrossEncoder raises; base model loads OK."""
        fine_tuned_dir = tmp_path / "ft_model"
        fine_tuned_dir.mkdir()

        call_count = 0
        mock_instance = MagicMock()
        mock_instance.predict.return_value = [0.7]

        def cross_encoder_side_effect(path, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("model files missing")
            return mock_instance

        mock_cls = MagicMock(side_effect=cross_encoder_side_effect)
        mock_st = MagicMock()
        mock_st.CrossEncoder = mock_cls

        with patch.dict("sys.modules", {"sentence_transformers": mock_st}):
            m = RerankerModel(model_path=str(fine_tuned_dir))

        assert m.is_available() is True
        assert call_count == 2  # first attempt failed, second (base) succeeded

    def test_not_available_when_base_model_also_fails(self):
        mock_cls = MagicMock(side_effect=OSError("no model files"))
        mock_st = MagicMock()
        mock_st.CrossEncoder = mock_cls
        with patch.dict("sys.modules", {"sentence_transformers": mock_st}):
            m = RerankerModel()
        assert m.is_available() is False

    def test_model_path_property(self):
        mock_cls, _ = self._make_mock_cross_encoder_cls()
        mock_st = MagicMock()
        mock_st.CrossEncoder = mock_cls
        with patch.dict("sys.modules", {"sentence_transformers": mock_st}):
            m = RerankerModel()
        assert m.model_path == "cross-encoder/ms-marco-MiniLM-L-6-v2"


# ===========================================================================
# Module-level singleton helpers
# ===========================================================================

class TestGetReranker:
    def test_returns_reranker_model_instance(self):
        import src.rag.reranker as mod
        mod._reranker = None  # reset singleton
        with patch.dict("sys.modules", {"sentence_transformers": None}):
            r = get_reranker()
        assert isinstance(r, RerankerModel)

    def test_returns_same_instance_on_repeated_calls(self):
        import src.rag.reranker as mod
        mod._reranker = None
        with patch.dict("sys.modules", {"sentence_transformers": None}):
            r1 = get_reranker()
            r2 = get_reranker()
        assert r1 is r2

    def test_reload_reranker_returns_new_instance(self):
        import src.rag.reranker as mod
        mod._reranker = None
        with patch.dict("sys.modules", {"sentence_transformers": None}):
            r1 = get_reranker()
            r2 = reload_reranker()
        assert r1 is not r2
