"""The Scaleway Phase 1 provisioning script.

Provisioning is only useful if it is repeatable, and repeatable here means a
second run creates nothing. `scw` is a shim that records its argv and answers
with canned inventories, so what is asserted is which resources the script
decides to create, and — the part that cannot be idempotent — how it behaves
around an API secret that Scaleway shows exactly once.
"""

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "scaleway" / "provision.sh"


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

FAKE_SCW = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$SCW_FAKE_LOG"
case "$1 $2 $3" in
  "account project list")   printf '%s' "$SCW_FAKE_PROJECTS" ;;
  "account project create") echo '{"id":"proj-new","name":"localchat-test"}' ;;
  "sdb-sql database list")  printf '%s' "$SCW_FAKE_DATABASES" ;;
  "sdb-sql database create") echo '{"id":"db-new","name":"localchat"}' ;;
  "sdb-sql database get")   echo '{"id":"db-x","endpoint":"postgres://db-x.pg.sdb.fr-par.scw.cloud:5432/localchat?sslmode=require"}' ;;
  "iam application list")   printf '%s' "$SCW_FAKE_APPS" ;;
  "iam application create") echo '{"id":"app-new","name":"localchat-app"}' ;;
  "iam policy list")        printf '%s' "$SCW_FAKE_POLICIES" ;;
  "iam policy create")      echo '{"id":"pol-new","name":"localchat-db-readwrite"}' ;;
  "iam api-key list")       printf '%s' "$SCW_FAKE_KEYS" ;;
  "iam api-key create")     echo '{"access_key":"SCWFAKE1","secret_key":"the-secret","application_id":"app-x","created_at":"2026-09-05T00:00:00Z","expires_at":"2027-09-05T00:00:00Z"}' ;;
  "iam api-key delete")     echo '{}' ;;
  *) echo "unexpected: $*" >&2; exit 1 ;;
esac
"""

EXISTING_PROJECT = json.dumps([{"id": "proj-x", "name": "localchat-test"}])
EXISTING_DB = json.dumps([{"id": "db-x", "name": "localchat"}])
EXISTING_APP = json.dumps([{"id": "app-x", "name": "localchat-app"}])
EXISTING_POLICY = json.dumps([{"id": "pol-x", "name": "localchat-db-readwrite"}])
EXISTING_KEY = json.dumps([{"access_key": "SCWOLD1", "application_id": "app-x"}])

ALL_PRESENT = {
    "SCW_FAKE_PROJECTS": EXISTING_PROJECT,
    "SCW_FAKE_DATABASES": EXISTING_DB,
    "SCW_FAKE_APPS": EXISTING_APP,
    "SCW_FAKE_POLICIES": EXISTING_POLICY,
    "SCW_FAKE_KEYS": EXISTING_KEY,
}


def _run(tmp_path, **env):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "scw"
    fake.write_text(FAKE_SCW, newline="\n")
    fake.chmod(0o755)
    log = tmp_path / "calls.log"
    log.touch()
    env_out = tmp_path / "creds" / "localchat-db.env"

    environ = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "SCW_FAKE_LOG": str(log),
        "SCW_FAKE_PROJECTS": "[]",
        "SCW_FAKE_DATABASES": "[]",
        "SCW_FAKE_APPS": "[]",
        "SCW_FAKE_POLICIES": "[]",
        "SCW_FAKE_KEYS": "[]",
        "PROVISION_ENV_OUT": str(env_out),
    }
    environ.update(env)
    environ.pop("SCW_PROFILE", None)

    proc = subprocess.run([BASH, str(SCRIPT)], env=environ, capture_output=True, text=True)
    calls = [line for line in log.read_text().splitlines() if line.strip()]
    return proc, calls, env_out


def _creates(calls):
    return [c for c in calls if " create " in c]


class TestAFreshAccount:
    def test_every_resource_is_created_once_in_dependency_order(self, tmp_path):
        proc, calls, _ = _run(tmp_path)

        assert proc.returncode == 0, proc.stderr
        assert [c.split(" -o ")[0] for c in _creates(calls)] == [
            "account project create name=localchat-test description=LocalChat test stack",
            "sdb-sql database create name=localchat cpu-min=0 cpu-max=1 project-id=proj-new",
            "iam application create name=localchat-app description=LocalChat test stack"
            " - owns the database credential",
            "iam policy create name=localchat-db-readwrite description=Scoped to the"
            " localchat-test project only application-id=app-new"
            " rules.0.permission-set-names.0=ServerlessSQLDatabaseReadWrite"
            " rules.0.project-ids.0=proj-new",
            "iam api-key create application-id=app-new expires-at=+365d"
            " description=LocalChat test stack database credential",
        ]

    def test_the_database_is_created_with_both_cpu_bounds(self, tmp_path):
        """The CLI requires them, which is what stops Terraform's max_cpu = 15 default."""
        _, calls, _ = _run(tmp_path)

        create = next(c for c in calls if c.startswith("sdb-sql database create"))
        assert "cpu-min=0" in create and "cpu-max=1" in create

    def test_the_policy_is_scoped_to_the_project_not_the_organisation(self, tmp_path):
        _, calls, _ = _run(tmp_path)

        policy = next(c for c in calls if c.startswith("iam policy create"))
        assert "rules.0.project-ids.0=proj-new" in policy
        assert "organization-id" not in policy

    def test_the_credential_file_is_written_private_and_complete(self, tmp_path):
        proc, _, env_out = _run(tmp_path)

        assert proc.returncode == 0, proc.stderr
        written = dict(
            line.split("=", 1)
            for line in env_out.read_text().splitlines()
            if line and not line.startswith("#")
        )
        assert written == {
            "PG_HOST": "db-x.pg.sdb.fr-par.scw.cloud",
            "PG_PORT": "5432",
            "PG_DB": "localchat",
            "PG_USER": "app-x",
            "PG_PASSWORD": "the-secret",
            "PG_SSLMODE": "require",
        }
        if sys.platform != "win32":  # Windows models only a read-only bit
            assert stat.S_IMODE(env_out.stat().st_mode) & 0o077 == 0, (
                "group/other can read the secret"
            )

    def test_the_secret_never_reaches_stdout(self, tmp_path):
        proc, _, _ = _run(tmp_path)

        assert "the-secret" not in proc.stdout
        assert "the-secret" not in proc.stderr
        assert "SCWFAKE1" in proc.stdout, "the access key is safe to show, and useful"


class TestASecondRun:
    def test_creates_nothing_when_everything_exists(self, tmp_path):
        proc, calls, _ = _run(tmp_path, **ALL_PRESENT)

        assert proc.returncode == 0, proc.stderr
        assert _creates(calls) == []

    def test_refuses_a_second_key_because_the_secret_cannot_be_read_back(self, tmp_path):
        proc, calls, env_out = _run(tmp_path, **ALL_PRESENT)

        assert not any(c.startswith("iam api-key create") for c in calls)
        assert "PROVISION_ROTATE_KEY=1" in proc.stdout
        assert not env_out.exists(), "an unchanged run must not overwrite the credential file"


class TestRotation:
    def test_the_old_key_is_deleted_before_the_new_one_is_created(self, tmp_path):
        proc, calls, env_out = _run(tmp_path, PROVISION_ROTATE_KEY="1", **ALL_PRESENT)

        assert proc.returncode == 0, proc.stderr
        key_calls = [c for c in calls if c.startswith("iam api-key") and " list" not in c]
        assert key_calls == [
            "iam api-key delete access-key=SCWOLD1",
            "iam api-key create application-id=app-x expires-at=+365d"
            " description=LocalChat test stack database credential -o json",
        ]
        assert "PG_PASSWORD=the-secret" in env_out.read_text()


class TestItRefusesRatherThanGuesses:
    def test_an_unreadable_project_list_stops_the_run(self, tmp_path):
        proc, calls, _ = _run(tmp_path, SCW_FAKE_PROJECTS="<html>502</html>")

        assert proc.returncode != 0
        assert _creates(calls) == [], "nothing may be created on an unreadable reply"
