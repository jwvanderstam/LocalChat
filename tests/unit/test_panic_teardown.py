"""The Scaleway cost kill switch.

Deleting live resources to prove a teardown works is self-defeating, so `scw` is
a shim that records its argv and answers with canned inventories. What is
asserted is which deletes the script issues, with which flags, and in which
order — under a runaway bill the flags are the difference between the burn
stopping and a volume quietly billing on.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "scaleway" / "panic_teardown.sh"


def _bash() -> str | None:
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

ORG = "org-0000"
PROJECT = "proj-1111"

FAKE_SCW = """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SCW_FAKE_LOG"
if [[ -n "$SCW_FAKE_FAIL" && "$*" == *"$SCW_FAKE_FAIL"* ]]; then
  echo "scaleway-sdk-go: boom" >&2
  exit 1
fi
case "$1 $2 $3" in
  "config get default-organization-id") echo "$SCW_FAKE_ORG" ;;
  "instance server list")               printf '%s' "$SCW_FAKE_SERVERS" ;;
  "container namespace list")           printf '%s' "$SCW_FAKE_NAMESPACES" ;;
  "sdb-sql database list")              printf '%s' "$SCW_FAKE_DATABASES" ;;
  "block volume list")                  printf '%s' "$SCW_FAKE_VOLUMES" ;;
  "instance ip list")                   printf '%s' "$SCW_FAKE_IPS" ;;
  "vpc private-network list")           printf '%s' "$SCW_FAKE_PNS" ;;
  *) echo '{}' ;;
esac
"""


def _run(tmp_path, project=PROJECT, **env):
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
        "SCW_FAKE_ORG": ORG,
        "SCW_FAKE_FAIL": "",
        "SCW_FAKE_SERVERS": "[]",
        "SCW_FAKE_NAMESPACES": "[]",
        "SCW_FAKE_DATABASES": "[]",
        "SCW_FAKE_VOLUMES": "[]",
        "SCW_FAKE_IPS": "[]",
        "SCW_FAKE_PNS": "[]",
    }
    if project is not None:
        environ["PROJECT_ID"] = project
    else:
        environ.pop("PROJECT_ID", None)
    environ.update(env)
    environ.pop("SCW_PROFILE", None)

    proc = subprocess.run([BASH, str(SCRIPT)], env=environ, capture_output=True, text=True)
    calls = [line for line in log.read_text().splitlines() if line.strip()]
    deletes = [c for c in calls if " delete " in c]
    return proc, calls, deletes


FULL_STACK = {
    "SCW_FAKE_SERVERS": json.dumps([{"id": "srv-1", "zone": "fr-par-2", "name": "ollama"}]),
    "SCW_FAKE_NAMESPACES": json.dumps([{"id": "ns-1", "region": "fr-par", "name": "localchat"}]),
    "SCW_FAKE_DATABASES": json.dumps([{"id": "db-1", "region": "fr-par", "name": "localchat"}]),
    "SCW_FAKE_VOLUMES": json.dumps([{"id": "vol-1", "zone": "fr-par-2", "name": "orphan"}]),
    "SCW_FAKE_IPS": json.dumps([{"id": "ip-1", "zone": "fr-par-2"}]),
    "SCW_FAKE_PNS": json.dumps([{"id": "pn-1", "region": "fr-par", "name": "backend"}]),
}


def test_dry_run_issues_no_deletes(tmp_path):
    proc, calls, deletes = _run(tmp_path, **FULL_STACK)

    assert proc.returncode == 0, proc.stderr
    assert deletes == []
    assert "6 resources would be deleted" in proc.stdout


def test_instance_delete_takes_its_volumes_and_ip_with_it(tmp_path):
    """A bare `server delete` leaves both behind, still billing."""
    proc, _, deletes = _run(tmp_path, CONFIRM="DESTROY", **FULL_STACK)

    assert proc.returncode == 0, proc.stderr
    assert deletes[0] == (
        "instance server delete server-id=srv-1 zone=fr-par-2 with-volumes=all"
        " with-ip=true force-shutdown=true"
    )


def test_everything_billable_is_deleted_most_expensive_first(tmp_path):
    proc, _, deletes = _run(tmp_path, CONFIRM="DESTROY", **FULL_STACK)

    assert proc.returncode == 0, proc.stderr
    assert [d.split()[0:3] for d in deletes] == [
        ["instance", "server", "delete"],
        ["container", "namespace", "delete"],
        ["sdb-sql", "database", "delete"],
        ["block", "volume", "delete"],
        ["instance", "ip", "delete"],
        ["vpc", "private-network", "delete"],
    ]


def test_a_failed_delete_does_not_stop_the_sweep_and_is_reported(tmp_path):
    proc, _, deletes = _run(
        tmp_path, CONFIRM="DESTROY", SCW_FAKE_FAIL="server-id=srv-1", **FULL_STACK
    )

    assert proc.returncode == 1
    assert len(deletes) == 6, "the sweep must continue past a failure"
    assert "did NOT go away" in proc.stderr
    assert "ollama" in proc.stderr


def test_the_organisations_default_project_is_refused_outright(tmp_path):
    proc, calls, _ = _run(tmp_path, project=ORG, CONFIRM="DESTROY", **FULL_STACK)

    assert proc.returncode != 0
    assert "Refusing" in proc.stderr
    assert calls == ["config get default-organization-id"]


def test_a_missing_project_id_is_refused_rather_than_defaulted(tmp_path):
    proc, calls, _ = _run(tmp_path, project=None, CONFIRM="DESTROY", **FULL_STACK)

    assert proc.returncode != 0
    assert "PROJECT_ID" in proc.stderr
    assert calls == []


def test_an_empty_project_reports_nothing_to_do(tmp_path):
    proc, _, deletes = _run(tmp_path, CONFIRM="DESTROY")

    assert proc.returncode == 0, proc.stderr
    assert deletes == []
    assert "Nothing billable found" in proc.stdout
