"""TQ-3 — the nightly mutation gate.

Runs `mutmut` over the isolation-critical modules and fails when a module's kill
rate falls under the agreed threshold. Coverage says a line executed; this says
something asserted its behaviour.

Scoped ruthlessly on purpose. A whole-repo run is hours, and the modules here are
where the three confirmed authorisation bugs actually lived.

Everything in this file that looks fussy was learned by getting a wrong number
first — see the environment notes in docs/TEST_QUALITY_AUDIT.md:

* ``--test-time-base`` because mutmut buckets partly on wall-clock, and a loaded
  runner files kills as "suspicious" (one local run read 4 killed / 108
  suspicious; idle it read 112 / 0).
* the runner is scoped to each module's *real* test files, because a whole-suite
  runner makes every mutant cost the whole suite.
* the caller must export the same environment variables CI's tests use, or code
  behind a config guard is unreachable and its mutants survive for free.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass, field

#: Module → the test files that exercise it for real. Verified by checking that
#: each file drives the implementation rather than patching it out; a runner
#: containing tests that mock the module cannot kill anything in it.
MODULES: dict[str, list[str]] = {
    "src/security_fastapi.py": [
        "tests/unit/test_security_fastapi.py",
        "tests/unit/test_authz_by_default.py",
        "tests/unit/test_sec1_no_demo_mode.py",
        "tests/unit/test_sec2_revocation_fail_closed.py",
        "tests/unit/test_workspace_membership_authz.py",
        "tests/unit/test_workspace_role_enforcement.py",
        "tests/unit/test_workspace_api_keys.py",
        "tests/unit/test_workspace_scope_pinning.py",
        "tests/unit/test_rbac2_route_permissions.py",
        "tests/unit/test_auth_login.py",
    ],
    "src/utils/workspace.py": [
        "tests/unit/test_workspace_scope_pinning.py",
        "tests/unit/test_workspace_api_keys.py",
    ],
}

#: Agreed in docs/PRODUCTION_PLAN.md. Deliberately above the measured baseline —
#: a threshold set to today's score ratifies the status quo instead of gating it.
DEFAULT_THRESHOLD = 80.0

_BUCKETS = ("killed", "survived", "timeout", "suspicious")


#: How many survivors to spell out. Enough to work from, short of pasting the
#: whole module into the job summary.
SURVIVOR_DETAIL_LIMIT = 40


@dataclass
class Result:
    module: str
    killed: int
    survived: int
    timeout: int
    suspicious: int
    #: (id, "line — the mutated source") for the survivors, captured while this
    #: module's cache still exists. Empty when nothing survived.
    survivors: list[tuple[str, str]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.killed + self.survived + self.timeout + self.suspicious

    @property
    def score(self) -> float:
        return 100.0 * self.killed / self.total if self.total else 0.0


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _count(bucket: str) -> int:
    result = _run(["mutmut", "result-ids", bucket])
    return len(result.stdout.split()) if result.returncode == 0 else 0


def survivor_details(limit: int = SURVIVOR_DETAIL_LIMIT) -> list[tuple[str, str]]:
    """Describe each surviving mutant, read *before* the next module wipes the cache.

    `mutmut<3` keeps one `.mutmut-cache`, so a multi-module run leaves only the
    last module's results behind — which for a gate is the wrong half. Reporting
    "70 survived" without saying which is a red badge, not a work queue.
    """
    ids = _run(["mutmut", "result-ids", "survived"]).stdout.split()
    details: list[tuple[str, str]] = []
    for mutant_id in ids[:limit]:
        diff = _run(["mutmut", "show", mutant_id]).stdout.splitlines()
        location = next((line for line in diff if line.startswith("@@")), "")
        mutated = next(
            (line for line in diff if line.startswith("+") and not line.startswith("+++")), ""
        )
        details.append((mutant_id, f"{location.strip()} {mutated.strip()}".strip()))
    return details


def measure(module: str, tests: list[str], time_base: float) -> Result:
    """Mutate *module*, judged by *tests*. One module at a time — mutmut<3 keeps a
    single .mutmut-cache and a second run clears the first's results."""
    if os.path.exists(".mutmut-cache"):
        os.remove(".mutmut-cache")

    runner = "python -m pytest -x -q --no-cov -p no:cacheprovider " + " ".join(tests)
    print(f"::group::mutmut {module}", flush=True)
    _run([
        "mutmut", "run",
        "--paths-to-mutate", module,
        "--simple-output", "--no-progress",
        "--test-time-base", str(time_base),
        "--runner", runner,
    ])
    print("::endgroup::", flush=True)

    counts = {bucket: _count(bucket) for bucket in _BUCKETS}
    return Result(module=module, survivors=survivor_details(), **counts)


def check_harness(result: Result) -> str | None:
    """Return a reason this result should not be believed, else None.

    A score is a claim about the tests only if the harness ran them. Both cases
    below have already happened once and each looked like a real result.
    """
    if result.total == 0:
        return "no mutants generated — check --paths-to-mutate"
    if result.killed == 0:
        return (
            "every mutant survived — the runner is almost certainly not exercising "
            "this module (wrong test files, or an import/config error swallowed by -q)"
        )
    if result.suspicious:
        return (
            f"{result.suspicious} mutants classified 'suspicious' — timing was unstable, "
            "so this score is not reproducible; re-run on an idle runner"
        )
    return None


def report(results: list[Result], threshold: float) -> str:
    lines = ["### Mutation score", "", "| Module | Killed | Survived | Score | Threshold |",
             "|---|---|---|---|---|"]
    for r in results:
        verdict = "✅" if r.score >= threshold else "❌"
        lines.append(
            f"| `{r.module}` | {r.killed} | {r.survived} | {verdict} {r.score:.1f}% | {threshold:.0f}% |"
        )
    lines += ["", "A surviving mutant is a change to the source that no test objected to."]

    for result in results:
        if result.score >= threshold or not result.survivors:
            continue
        lines += ["", f"<details><summary>Survivors in <code>{result.module}</code>"
                      f" ({result.survived})</summary>", "", "| id | mutation |", "|---|---|"]
        lines += [f"| {mid} | `{what}` |" for mid, what in result.survivors]
        if result.survived > len(result.survivors):
            lines.append(f"| … | {result.survived - len(result.survivors)} more; "
                         f"`mutmut show <id>` for any of them |")
        lines += ["", "</details>"]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--test-time-base", type=float, default=60.0)
    parser.add_argument("--module", action="append", choices=sorted(MODULES),
                        help="limit to this module (repeatable); default is all")
    args = parser.parse_args()

    targets = args.module or list(MODULES)
    results = [measure(m, MODULES[m], args.test_time_base) for m in targets]

    summary = report(results, args.threshold)
    print(summary)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(summary + "\n")

    broken = [(r, reason) for r in results if (reason := check_harness(r))]
    for result, reason in broken:
        print(f"::error::{result.module}: {reason}")
    if broken:
        return 2  # distinct from a genuine miss: the measurement itself is void

    missed = [r for r in results if r.score < args.threshold]
    for result in missed:
        print(
            f"::error::{result.module} scored {result.score:.1f}%, below {args.threshold:.0f}% "
            f"— {result.survived} mutants survived"
        )
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
