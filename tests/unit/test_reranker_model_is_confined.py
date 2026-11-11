"""R-11 (#529 review) — what the reranker loads stays inside its model directory.

In the image only ``/app/data`` is writable, and the reranker's model directory lives
there. A pointer file or a version row that names a path elsewhere is ignored, and a
promotion is refused before the database marks a version active that cannot be loaded.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src import config
from src.rag.feedback_pipeline import promote_model
from src.rag.reranker import RerankerModel, confined_model_path

pytestmark = pytest.mark.unit


@pytest.fixture()
def model_dir(tmp_path):
    base = tmp_path / "reranker"
    (base / "v1").mkdir(parents=True)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    with patch.object(config, "RERANKER_MODEL_PATH", str(base / "latest")):
        yield base, outside


class TestTheConfinement:
    def test_a_version_beside_the_configured_path_is_kept(self, model_dir):
        base, _ = model_dir
        assert confined_model_path(str(base / "v1")) == str((base / "v1").resolve())

    @pytest.mark.parametrize("kind", ["outside", "dotdot", "missing"])
    def test_anything_else_is_refused(self, model_dir, kind):
        base, outside = model_dir
        raw = {"outside": str(outside), "dotdot": str(base / ".." / "elsewhere"),
               "missing": str(base / "v9")}[kind]
        assert confined_model_path(raw) is None

    def test_a_pointer_naming_another_directory_is_not_loaded(self, model_dir):
        base, outside = model_dir
        (base / "latest.txt").write_text(str(outside), encoding="utf-8")
        st = MagicMock()
        with patch.dict("sys.modules", {"sentence_transformers": st}):
            RerankerModel()
        assert [c.args[0] for c in st.CrossEncoder.call_args_list] == ["cross-encoder/ms-marco-MiniLM-L-6-v2"]

    def test_no_model_may_bring_its_own_code(self, model_dir):
        base, _ = model_dir
        (base / "latest.txt").write_text(str(base / "v1"), encoding="utf-8")
        st = MagicMock()
        with patch.dict("sys.modules", {"sentence_transformers": st}):
            RerankerModel()
        assert st.CrossEncoder.call_args.kwargs["trust_remote_code"] is False


def _db(model_path: str) -> MagicMock:
    db = MagicMock()
    db.feedback.reranker_versions.return_value = [{"id": "v", "model_path": model_path}]
    db.feedback.activate_reranker_version.return_value = model_path
    return db


class TestPromotion:
    def test_a_version_outside_the_model_directory_is_not_activated(self, model_dir):
        """A version trained into ./models before R-11 cannot be written beside any more."""
        _, outside = model_dir
        db = _db(str(outside))
        with patch("src.rag.reranker.reload_reranker") as reload:
            assert promote_model(db, "v") is False
        assert (db.feedback.activate_reranker_version.called, reload.called) == (False, False)

    def test_a_version_inside_is_pointed_at_then_activated(self, model_dir):
        base, _ = model_dir
        db = _db(str(base / "v1"))
        with patch("src.rag.reranker.reload_reranker") as reload:
            assert promote_model(db, "v") is True
        assert ((base / "latest.txt").read_text(encoding="utf-8"), reload.call_args.args[0]) == (
            str((base / "v1").resolve()), str((base / "v1").resolve()))
        db.feedback.activate_reranker_version.assert_called_once_with("v")
