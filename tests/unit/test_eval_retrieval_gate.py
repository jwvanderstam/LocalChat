"""EV-1 — the retrieval gate's verdicts, without a database.

The gate is only worth having if a red run means the diff moved retrieval and a green
run means it did not. These pin the parts that decide that: how a document's rank is
read, and how a score is compared to the committed baseline.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# `scripts/` is not a package, so the script is loaded by path (see
# test_eval_retrieval_corpus.py for why it goes into sys.modules first).
_SPEC = importlib.util.spec_from_file_location(
    "eval_retrieval",
    Path(__file__).resolve().parents[2] / "scripts" / "eval_retrieval.py",
)
assert _SPEC
assert _SPEC.loader
ev = importlib.util.module_from_spec(_SPEC)
sys.modules["eval_retrieval"] = ev
_SPEC.loader.exec_module(ev)

pytestmark = pytest.mark.unit

SETTINGS = {"TOP_K_RESULTS": 30, "RERANKER_ENABLED": True}


def _result(filename: str, combined: float, rerank: float | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        filename=filename,
        similarity=0.0,
        metadata={"combined_score": combined, "rerank_score": rerank},
    )


def _score_with(results: list[SimpleNamespace], source: str) -> dict:
    processor = MagicMock()
    processor.retrieve_context.return_value = results
    case = ev.Case(question="q", source=source, proof="p", answered_by="x")
    with patch("src.rag.processor.doc_processor", processor):
        return ev.score([case], top_k=10, workspace_id=None)


class TestRankIsRelevanceNotPosition:
    def test_the_best_scoring_file_ranks_first_even_when_returned_last(self):
        """retrieve_context returns reading order — alphabetical. Position is not rank."""
        results = [_result("docs/AAA.md", 0.1), _result("docs/ZZZ.md", 0.9)]

        scored = _score_with(results, "docs/ZZZ.md")

        assert (scored["recall@1"], scored["mrr"]) == (1.0, 1.0)

    def test_the_alphabetically_first_file_is_not_rank_one_when_it_scores_lower(self):
        results = [_result("docs/AAA.md", 0.1), _result("docs/ZZZ.md", 0.9)]

        scored = _score_with(results, "docs/AAA.md")

        assert (scored["recall@1"], scored["mrr"]) == (0.0, 0.5)

    def test_a_rerank_score_takes_precedence_over_the_blend(self):
        results = [_result("a.md", 0.9, rerank=-5.0), _result("b.md", 0.1, rerank=3.0)]

        assert _score_with(results, "b.md")["recall@1"] == 1.0

    def test_a_miss_names_the_best_scoring_file_as_the_top_hit(self):
        results = [_result("docs/AAA.md", 0.1), _result("docs/ZZZ.md", 0.9)]

        scored = _score_with(results, "docs/MISSING.md")

        assert scored["misses"] == [("q", "ZZZ.md")]


def _record(r1: float, r5: float, mrr: float, settings: dict | None = None, n: int = 20) -> dict:
    return ev.gate_record(
        {"n": n, "recall@1": r1, "recall@5": r5, "mrr": mrr},
        settings if settings is not None else SETTINGS,
    )


class TestCompareToBaseline:
    def test_an_identical_score_passes(self):
        assert ev.compare_to_baseline(_record(0.5, 0.8, 0.6), _record(0.5, 0.8, 0.6)) == []

    def test_a_drop_in_any_metric_fails_and_names_it(self):
        problems = ev.compare_to_baseline(_record(0.5, 0.75, 0.6), _record(0.5, 0.8, 0.6))

        assert problems == ["recall@5 fell: 0.8 -> 0.75"]

    def test_a_rise_fails_too_because_the_baseline_would_go_stale(self):
        problems = ev.compare_to_baseline(_record(0.55, 0.8, 0.6), _record(0.5, 0.8, 0.6))

        assert problems == ["recall@1 rose: 0.5 -> 0.55"]

    def test_changed_settings_are_reported_as_settings_not_as_a_regression(self):
        changed = dict(SETTINGS, TOP_K_RESULTS=40)

        problems = ev.compare_to_baseline(_record(0.5, 0.8, 0.6, changed), _record(0.5, 0.8, 0.6))

        assert len(problems) == 1 and problems[0].startswith("retrieval settings differ")

    def test_a_different_case_count_is_reported(self):
        problems = ev.compare_to_baseline(_record(0.5, 0.8, 0.6, n=19), _record(0.5, 0.8, 0.6))

        assert problems == ["19 cases, the baseline has 20"]

    def test_the_record_rounds_so_float_noise_cannot_fail_an_exact_comparison(self):
        assert _record(1 / 3, 0.8, 0.6)["metrics"]["recall@1"] == 0.333333


class TestTheGateRefusesToScoreWithoutTheReranker:
    def test_enabled_but_not_loaded_is_a_refusal(self, monkeypatch):
        monkeypatch.setattr("src.config.RERANKER_ENABLED", True)
        unavailable = MagicMock()
        unavailable.is_available.return_value = False

        with patch("src.rag.reranker.get_reranker", return_value=unavailable):
            assert "did not load" in ev.reranker_problem()

    def test_enabled_and_loaded_is_fine(self, monkeypatch):
        monkeypatch.setattr("src.config.RERANKER_ENABLED", True)
        loaded = MagicMock()
        loaded.is_available.return_value = True

        with patch("src.rag.reranker.get_reranker", return_value=loaded):
            assert ev.reranker_problem() is None

    def test_deliberately_disabled_is_fine(self, monkeypatch):
        monkeypatch.setattr("src.config.RERANKER_ENABLED", False)

        assert ev.reranker_problem() is None


class TestEveryRunPinsTheDefaults:
    def test_a_compare_run_scores_the_defaults_not_a_persisted_override(self, monkeypatch):
        """--compare used to read app_state.json's settings-page overrides, which the gate pinned away."""
        from src import config

        monkeypatch.setitem(config.app_state.state, "rag_params", {"TOP_K_RESULTS": 40})
        seen: list[int] = []

        def _score(*_args, **_kwargs):
            seen.append(config.app_state.get_rag_param("TOP_K_RESULTS"))
            return {"n": 1, "recall@1": 0.0, "recall@5": 0.0, "mrr": 0.0, "misses": []}

        args = SimpleNamespace(cases=None, corpus=Path("."), ingest=False, check=False,
                               write_baseline=False, compare="reranker", top_k=10,
                               workspace_id=None, misses=False)
        with (
            patch.object(ev, "connect_db"),
            patch.object(ev, "load_cases", return_value=[]),
            patch.object(ev, "verify_premises", return_value=[]),
            patch.object(ev, "score", side_effect=_score),
        ):
            assert ev._run(args) == 0

        assert seen == [config.TOP_K_RESULTS, config.TOP_K_RESULTS]
