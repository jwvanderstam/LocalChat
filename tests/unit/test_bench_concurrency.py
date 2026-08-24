"""The concurrency benchmark's CI gate, tested.

PERF-2 established that time-to-first-token cannot see the defect PERF-1 fixed —
three runs of one build spread wider than the change did. The canary can, so the
canary is what gates CI, and its verdict is worth pinning: a gate that passes when
it measured nothing is the failure mode that matters.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest

# `scripts/` is not a package, so the benchmark is loaded by path. It must be
# registered in sys.modules before exec: @dataclass resolves its own module
# through sys.modules and raises on a module that is not there.
_SPEC = importlib.util.spec_from_file_location(
    "bench_concurrency",
    Path(__file__).resolve().parents[2] / "scripts" / "bench_concurrency.py",
)
assert _SPEC
assert _SPEC.loader
bench = importlib.util.module_from_spec(_SPEC)
sys.modules["bench_concurrency"] = bench
_SPEC.loader.exec_module(bench)


@pytest.mark.unit
class TestCanaryVerdict:

    def test_no_budget_never_fails(self):
        assert bench.canary_verdict([0.9, 5.0], None) is None

    def test_passes_when_the_worst_probe_is_inside_the_budget(self):
        # 0.305s is what PERF-1 left behind; a 500ms budget accepts it.
        assert bench.canary_verdict([0.003, 0.005, 0.305], 500) is None

    def test_fails_on_the_worst_probe_not_the_average(self):
        # The pre-PERF-1 shape: healthy p50, one 848ms stall. A mean-based gate
        # would pass this — the stall is the whole signal.
        breach = bench.canary_verdict([0.003, 0.003, 0.004, 0.848], 500)
        assert breach is not None
        assert "848ms" in breach
        assert "500ms" in breach

    def test_empty_sample_is_a_failure_not_a_pass(self):
        breach = bench.canary_verdict([], 500)
        assert breach is not None
        assert "never measured" in breach

    def test_a_probe_exactly_on_the_budget_passes(self):
        assert bench.canary_verdict([0.5], 500) is None


@pytest.mark.unit
class TestPercentile:

    def test_nearest_rank_returns_a_real_observation(self):
        # Not an interpolation between two samples — a worst-case budget should be
        # a number the system actually produced.
        assert bench._percentile([1.0, 2.0, 3.0, 4.0], 95) == 4.0

    def test_p50_of_an_even_sample_takes_the_lower_middle(self):
        assert bench._percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.0

    def test_empty_is_nan_rather_than_an_exception(self):
        assert math.isnan(bench._percentile([], 95))
