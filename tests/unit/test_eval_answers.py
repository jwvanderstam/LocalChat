"""P2-3 — the parts of the answer evaluation that decide its numbers.

The model calls cannot run here; what can is everything that turns their output into a
score, and each of these would bias the baseline silently if it were wrong.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

# `scripts/` is not a package, so the script is loaded by path.
_SPEC = importlib.util.spec_from_file_location(
    "eval_answers", Path(__file__).resolve().parents[2] / "scripts" / "eval_answers.py"
)
ev = importlib.util.module_from_spec(_SPEC)
sys.modules["eval_answers"] = ev
_SPEC.loader.exec_module(ev)


def _result(rank, proof=True, correct=1.0, faithful=1.0):
    return {"rank": rank, "proof_in_context": proof, "correct": correct, "faithful": faithful}


class TestProofMatching:
    def test_whitespace_and_case_do_not_break_a_verbatim_quote(self):
        passage = "The contract term is\n  five (5) YEARS from signature."
        assert ev.normalise("contract term is five (5) years") in ev.normalise(passage)

    def test_a_paraphrase_is_not_a_quote(self):
        assert ev.normalise("the term lasts five years") not in ev.normalise(
            "The contract term is five (5) years from signature."
        )


class TestJsonFromAModelReply:
    def test_json_wrapped_in_prose_is_extracted(self):
        raw = 'Sure! Here it is:\n{"question": "Q?", "answer": "A", "quote": "q"}\nHope that helps.'
        assert ev.parse_json_object(raw) == {"question": "Q?", "answer": "A", "quote": "q"}

    def test_a_brace_inside_a_string_does_not_end_the_object_early(self):
        raw = '{"reason": "uses {braces}", "correct": "yes"}'
        assert ev.parse_json_object(raw) == {"reason": "uses {braces}", "correct": "yes"}

    def test_no_object_is_none_not_an_exception(self):
        assert ev.parse_json_object("I cannot answer that.") is None


class TestSourceRank:
    def test_rank_counts_documents_not_chunks(self):
        """Three chunks of one file are one rank; otherwise MRR punishes a thorough retriever."""
        retrieved = ["a.pdf", "a.pdf", "a.pdf", "b.docx"]
        assert ev.source_rank("folder/b.docx", retrieved) == 2

    def test_a_missing_source_has_no_rank(self):
        assert ev.source_rank("c.pptx", ["a.pdf", "b.docx"]) is None


class TestSummary:
    def test_metrics_combine_every_case(self):
        """Two cases with different outcomes, so a metric that kept only the last would show."""
        summary = ev.summarise([_result(1, True, 1.0, 1.0), _result(4, False, 0.5, 0.0)])
        assert summary["source_recall@1"] == 0.5
        assert summary["source_recall@5"] == 1.0
        assert summary["source_mrr"] == round((1 + 1 / 4) / 2, 3)
        assert summary["proof_recall"] == 0.5
        assert summary["answer_correct"] == 0.75
        assert summary["faithfulness"] == 0.5

    def test_an_unparseable_verdict_is_left_out_not_scored_zero(self):
        summary = ev.summarise([_result(1, correct=None, faithful=None), _result(1, correct=1.0)])
        assert summary["answer_correct"] == 1.0


class TestRegressionCheck:
    BASELINE = {"tolerance": 0.05, "metrics": {"answer_correct": 0.80, "source_mrr": 0.60}}

    def test_a_drop_within_tolerance_passes(self):
        assert ev.regressions({"answer_correct": 0.76, "source_mrr": 0.60}, self.BASELINE) == []

    def test_a_drop_beyond_tolerance_is_named(self):
        failed = ev.regressions({"answer_correct": 0.74, "source_mrr": 0.60}, self.BASELINE)
        assert [line.split(":")[0] for line in failed] == ["answer_correct"]


class TestJudgeAgreement:
    def test_exact_and_within_one(self):
        pairs = [("yes", "yes"), ("partial", "yes"), ("no", "yes"), ("no", "no")]
        assert ev.agreement(pairs) == {"n": 4, "exact": 0.5, "within_one": 0.75}

    def test_unscored_rows_are_skipped(self):
        assert ev.agreement([("", "yes"), ("yes", "yes")])["n"] == 1


class TestPrivacyGuard:
    def test_an_output_inside_the_repository_is_refused(self):
        with pytest.raises(SystemExit, match="inside the repository"):
            ev.refuse_inside_repo(ev.REPO_ROOT / "tests" / "eval" / "cases.yaml")

    def test_an_output_outside_it_is_allowed(self, tmp_path):
        ev.refuse_inside_repo(tmp_path / "cases.yaml")


class TestJudgePrompts:
    @pytest.mark.parametrize("version", ["v1", "v2"])
    def test_every_prompt_formats_and_carries_the_answer(self, version):
        """A stray brace in a template is a KeyError halfway through a run, not at import."""
        text = ev.JUDGE_PROMPTS[version].format(
            question="Q?", reference="R.", context="C.", answer="ANSWER-MARKER"
        )
        assert "ANSWER-MARKER" in text and "{" in text  # the JSON example survives formatting

    def test_v2_has_every_specific_checked(self):
        """The failure v1 passed: a correct core with an invented clause or section number."""
        assert "clause, section and page numbers" in ev.JUDGE_PROMPTS["v2"]
        assert "clause" not in ev.JUDGE_PROMPTS["v1"]


class TestSelectForRejudge:
    RESULTS = [
        {"id": 1, "question": "What is the term?", "reference_answer": "old"},
        {"id": 2, "question": "Who signs?", "reference_answer": "x"},
        {"id": 3, "question": "When does it end?", "reference_answer": "y"},
        {"id": 4, "question": "Orphan?", "reference_answer": "z"},
    ]
    CASES = [
        {"id": 1, "status": "accepted", "question": "What is  the TERM?", "reference_answer": "fixed"},
        {"id": 2, "status": "rejected", "question": "Who signs?", "reference_answer": "x"},
        {"id": 3, "status": "accepted", "question": "When does the contract end?", "reference_answer": "y"},
    ]

    def test_each_result_lands_in_exactly_one_bucket(self):
        keep, dropped, stale = ev.select_for_rejudge(self.RESULTS, self.CASES)
        assert [r["id"] for r in keep] == [1]
        assert dropped == [2, 4]
        assert stale == [3]

    def test_an_edited_reference_answer_is_the_one_graded_against(self):
        keep, _, _ = ev.select_for_rejudge(self.RESULTS, self.CASES)
        assert keep[0]["reference_answer"] == "fixed"


class TestUnusablePassages:
    def test_a_table_of_contents_is_skipped(self):
        toc = "\n".join([
            "1 Introduction .......... 3",
            "2 Service description .......... 5",
            "2.1 Service levels .......... 7",
            "3 Pricing .......... 12",
        ])
        assert ev.looks_unusable(toc)

    def test_a_fill_in_template_is_skipped(self):
        assert ev.looks_unusable("Solution overview. Please describe the desired solution for each site.")

    def test_ordinary_prose_with_numbers_is_kept(self):
        """Contract text is full of numbers; only a list of titles ending in page numbers is a TOC."""
        prose = (
            "The Supplier shall restore service within 4 hours for Priority 1 incidents.\n"
            "Availability is measured monthly and must reach 99.95 percent.\n"
            "Service credits of 5 percent apply for each 0.1 percent below target.\n"
            "Credits are capped at 20 percent of the monthly charge."
        )
        assert not ev.looks_unusable(prose)


class TestCalibrationScoring:
    def test_rejected_and_rereferenced_cases_are_handled_and_the_grader_is_named(self, tmp_path, capsys):
        import json
        import types

        results = tmp_path / "results.json"
        results.write_text(json.dumps({"results": [
            {"id": 1, "reference_answer": "same", "correct": 1.0, "faithful": 1.0},
            {"id": 2, "reference_answer": "fixed since", "correct": 0.0, "faithful": 0.5},
        ]}))
        sheet = tmp_path / "sheet.json"
        sheet.write_text(json.dumps({"cases": [
            {"id": 1, "reference_answer": "same", "human_correct": "yes", "human_faithful": "yes", "grader": "claude"},
            {"id": 2, "reference_answer": "old", "human_correct": "yes", "human_faithful": "partial", "grader": "claude"},
            {"id": 3, "reference_answer": "x", "human_correct": "no", "human_faithful": "no", "grader": "claude"},
        ]}))
        ev.cmd_calibrate(types.SimpleNamespace(results=results, score=sheet))
        out = json.loads(capsys.readouterr().out)
        assert out["graders"] == ["claude"]
        assert out["missing_results"] == [3]
        assert out["correct"]["n"] == 1   # case 2's reference changed after it was graded
        assert out["faithful"] == {"n": 2, "exact": 1.0, "within_one": 1.0}


class TestInstrumentMismatch:
    BASELINE = {"answer_model": "llama3.2", "judge_model": "mistral", "judge_prompt": "v1"}

    def test_the_same_instrument_is_comparable(self):
        assert ev.instrument_mismatch(dict(self.BASELINE), self.BASELINE) == []

    def test_a_different_judge_prompt_is_not_a_regression_to_report(self):
        """A stricter judge lowers the scores without the chat changing at all."""
        run = {**self.BASELINE, "judge_prompt": "v2"}
        assert [m.split()[0] for m in ev.instrument_mismatch(run, self.BASELINE)] == ["judge_prompt"]
