"""The mutation gate's own judgement, tested.

`scripts/mutation_gate.py` decides whether a nightly score is believable before
it decides whether the score passes. Both of the conditions it screens for
produced a plausible-looking wrong number during TQ-3 — a 4-killed/108-suspicious
run under machine load, and a run where an unset ADMIN_PASSWORD left a whole
function unreachable — so the screening is worth pinning.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# `scripts/` is not a package, so the gate is loaded by path. It must be
# registered in sys.modules before exec: @dataclass resolves its own module
# through sys.modules and raises on a module that is not there.
_SPEC = importlib.util.spec_from_file_location(
    "mutation_gate",
    Path(__file__).resolve().parents[2] / "scripts" / "mutation_gate.py",
)
assert _SPEC and _SPEC.loader
mutation_gate = importlib.util.module_from_spec(_SPEC)
sys.modules["mutation_gate"] = mutation_gate
_SPEC.loader.exec_module(mutation_gate)

Result = mutation_gate.Result

pytestmark = pytest.mark.unit


class TestScore:
    def test_score_is_killed_over_every_classified_mutant(self):
        """Survivors, timeouts and suspicious all count against — a mutant that
        was not killed was not killed, whatever the reason."""
        result = Result(module="m", killed=6, survived=2, timeout=1, suspicious=1)

        assert result.total == 10
        assert result.score == 60.0

    def test_score_of_a_module_with_no_mutants_is_zero_not_an_error(self):
        assert Result(module="m", killed=0, survived=0, timeout=0, suspicious=0).score == 0.0


class TestHarnessScreening:
    def test_a_healthy_result_is_believed(self):
        result = Result(module="m", killed=119, survived=83, timeout=0, suspicious=0)

        assert mutation_gate.check_harness(result) is None

    def test_no_mutants_at_all_means_the_path_is_wrong(self):
        result = Result(module="m", killed=0, survived=0, timeout=0, suspicious=0)

        assert "no mutants generated" in mutation_gate.check_harness(result)

    def test_nothing_killed_is_reported_as_a_broken_runner_not_a_score_of_zero(self):
        """The distinction the gate exists to make: 0% and "the tests never ran"
        look identical in the output and mean opposite things."""
        result = Result(module="m", killed=0, survived=90, timeout=0, suspicious=0)
        reason = mutation_gate.check_harness(result)

        assert reason is not None
        assert "not exercising" in reason

    def test_suspicious_mutants_void_the_run(self):
        """mutmut buckets partly on wall-clock; a loaded runner files kills as
        suspicious. Reporting 55% from such a run is reporting noise."""
        result = Result(module="m", killed=4, survived=95, timeout=0, suspicious=108)
        reason = mutation_gate.check_harness(result)

        assert reason is not None
        assert "suspicious" in reason


class TestReport:
    def test_a_module_under_threshold_is_marked_failed(self):
        table = mutation_gate.report(
            [Result(module="src/x.py", killed=59, survived=41, timeout=0, suspicious=0)],
            threshold=80.0,
        )

        assert "❌ 59.0%" in table

    def test_a_module_at_the_threshold_passes(self):
        """The boundary itself: 80 against a threshold of 80 is a pass."""
        table = mutation_gate.report(
            [Result(module="src/x.py", killed=80, survived=20, timeout=0, suspicious=0)],
            threshold=80.0,
        )

        assert "✅ 80.0%" in table


class TestSurvivorsAreNamed:
    """A failing gate has to say *which* mutants survived. mutmut<3 keeps one
    cache, so a later module erases the earlier one's results — reporting only a
    count would leave the failing module's work queue unrecoverable."""

    def test_a_failing_module_lists_its_survivors(self):
        report = mutation_gate.report(
            [Result(module="src/x.py", killed=1, survived=2, timeout=0, suspicious=0,
                    survivors=[("7", "@@ -10 +10 @@ +    if not x:"),
                               ("9", "@@ -20 +20 @@ +    return None")])],
            threshold=80.0,
        )

        assert "if not x:" in report
        assert "return None" in report

    def test_a_passing_module_does_not_list_anything(self):
        """Noise on a green run trains people to skim the summary."""
        report = mutation_gate.report(
            [Result(module="src/x.py", killed=9, survived=1, timeout=0, suspicious=0,
                    survivors=[("7", "@@ -10 +10 @@ +    if not x:")])],
            threshold=80.0,
        )

        assert "if not x:" not in report

    def test_a_truncated_list_says_how_many_are_missing(self):
        """Silently showing 40 of 70 would misrepresent the size of the job."""
        report = mutation_gate.report(
            [Result(module="src/x.py", killed=0, survived=70, timeout=0, suspicious=0,
                    survivors=[(str(i), f"mutant {i}") for i in range(40)])],
            threshold=80.0,
        )

        assert "30 more" in report
