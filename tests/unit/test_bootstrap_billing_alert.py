"""The Scaleway cost guardrail's create-or-update logic.

The script is unrunnable in CI against real billing, so `scw` is replaced by a
shim that records its argv and answers with canned JSON. What is asserted is the
sequence of `scw` calls the script decides to make — the decisions are the whole
of the script.

The budget payloads here are the shape a live account returned on 2026-09-05:
`consumption_limit` is an object, and `budget list` carries the whole tree, with
`alerts[]` nested in the budget and `notifications[]` nested in each alert.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "scaleway" / "bootstrap_billing_alert.sh"


def _bash() -> str | None:
    """Git Bash, not WSL.

    On Windows the `bash` first on PATH is System32's WSL shim, which cannot
    execute a Windows-style path and dies with execvpe ENOENT.
    """
    if sys.platform == "win32":
        for candidate in (
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files\Git\usr\bin\bash.exe",
        ):
            if Path(candidate).exists():
                return candidate
        return None
    return shutil.which("bash")


BASH = _bash()

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(BASH is None, reason="needs bash (Git Bash on Windows)"),
]

# Ordered most-specific-first: "budget-alert-notification create" also contains
# "budget", so a looser match would answer the wrong call.
FAKE_SCW = """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SCW_FAKE_LOG"
case "$2 $3" in
  "budget-alert-notification create") echo '{"id":"notif-new"}' ;;
  "budget-alert create")              echo '{"id":"alert-new"}' ;;
  "budget list")                      printf '%s' "$SCW_FAKE_BUDGETS" ;;
  "budget create")                    echo '{"id":"budget-new"}' ;;
  "budget update")                    echo '{"id":"budget-existing"}' ;;
  *) echo "unexpected: $*" >&2; exit 1 ;;
esac
"""

WEBHOOK = "https://hook.example/burn"


def _budget(limit=50, alerts=()):
    return json.dumps(
        [
            {
                "id": "budget-existing",
                "enabled": True,
                "consumption_limit": {"currency_code": "", "units": limit, "nanos": 0},
                "alerts": list(alerts),
            }
        ]
    )


def _alert(threshold=40, notifications=()):
    return {"id": "alert-existing", "threshold": threshold, "notifications": list(notifications)}


def _run(tmp_path, budgets="[]", **env):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "scw"
    fake.write_text(FAKE_SCW, newline="\n")
    fake.chmod(0o755)
    log = tmp_path / "calls.log"
    log.touch()

    environ = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "SCW_FAKE_LOG": str(log),
        "SCW_FAKE_BUDGETS": budgets,
        "BUDGET_LIMIT": "50",
        "ALERT_THRESHOLD": "40",
    }
    environ.update(env)
    environ.pop("SCW_PROFILE", None)

    proc = subprocess.run([BASH, str(SCRIPT)], env=environ, capture_output=True, text=True)
    calls = [line for line in log.read_text().splitlines() if line.strip()]
    return proc, calls


def test_creates_budget_alert_and_webhook_when_no_budget_exists(tmp_path):
    proc, calls = _run(tmp_path, WEBHOOK_URL=WEBHOOK)

    assert proc.returncode == 0, proc.stderr
    assert calls == [
        "billing budget list -o json",
        "billing budget create consumption-limit=50 enabled=true -o json",
        "billing budget-alert create budget-id=budget-new threshold=40 -o json",
        f"billing budget-alert-notification create budget-alert-id=alert-new"
        f" webhook-urls.0={WEBHOOK} -o json",
    ]


def test_a_second_run_against_a_matching_tree_writes_nothing(tmp_path):
    """The whole point of reading the tree: re-running is a single GET."""
    tree = _budget(limit=50, alerts=[_alert(threshold=40, notifications=[{"id": "n1"}])])
    proc, calls = _run(tmp_path, budgets=tree, WEBHOOK_URL=WEBHOOK)

    assert proc.returncode == 0, proc.stderr
    assert calls == ["billing budget list -o json"]


def test_a_changed_ceiling_updates_the_budget_in_place(tmp_path):
    proc, calls = _run(tmp_path, budgets=_budget(limit=30, alerts=[_alert()]))

    assert proc.returncode == 0, proc.stderr
    assert calls == [
        "billing budget list -o json",
        "billing budget update budget-id=budget-existing consumption-limit=50"
        " enabled=true -o json",
    ]


def test_an_alert_at_a_different_threshold_is_added_not_confused_for_ours(tmp_path):
    proc, calls = _run(tmp_path, budgets=_budget(limit=50, alerts=[_alert(threshold=25)]))

    assert proc.returncode == 0, proc.stderr
    assert calls == [
        "billing budget list -o json",
        "billing budget-alert create budget-id=budget-existing threshold=40 -o json",
    ]


def test_webhook_is_not_added_twice_to_an_already_notified_alert(tmp_path):
    tree = _budget(alerts=[_alert(notifications=[{"id": "n1"}])])
    proc, calls = _run(tmp_path, budgets=tree, WEBHOOK_URL=WEBHOOK)

    assert proc.returncode == 0, proc.stderr
    assert not any("notification" in call for call in calls)
    assert "already has a notification" in proc.stdout


def test_webhook_is_attached_to_an_existing_alert_that_has_none(tmp_path):
    proc, calls = _run(tmp_path, budgets=_budget(alerts=[_alert()]), WEBHOOK_URL=WEBHOOK)

    assert proc.returncode == 0, proc.stderr
    assert calls[-1] == (
        f"billing budget-alert-notification create budget-alert-id=alert-existing"
        f" webhook-urls.0={WEBHOOK} -o json"
    )


def test_two_budgets_are_refused_rather_than_guessed_between(tmp_path):
    two = json.dumps([{"id": "a", "alerts": []}, {"id": "b", "alerts": []}])
    proc, calls = _run(tmp_path, budgets=two)

    assert proc.returncode != 0
    assert "2 budgets exist" in proc.stderr
    assert calls == ["billing budget list -o json"]


def test_unreadable_budget_list_refuses_instead_of_creating_blind(tmp_path):
    proc, calls = _run(tmp_path, budgets="<html>gateway timeout</html>")

    assert proc.returncode != 0
    assert "refusing to create blind" in proc.stderr
    assert calls == ["billing budget list -o json"]
