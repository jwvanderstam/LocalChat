"""The Scaleway Phase 2 and Phase 4 deployment scripts.

These encode what a manual deployment taught, and the details they encode are
exactly the ones that cost a failed attempt each. So the assertions are on those
details rather than on "it ran": the memory unit the CLI actually accepts, that
an update re-sends the whole environment because Scaleway replaces it, that
secrets go in the separate secret map, and that the Ollama box is created behind
a security group which drops inbound.

`scw` is a shim that records its argv and answers with canned inventories.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "scaleway"
CONTAINER_SH = SCRIPTS / "deploy_container.sh"
EMBEDDINGS_SH = SCRIPTS / "deploy_embeddings.sh"


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
  "account project list")        printf '%s' "$SCW_FAKE_PROJECTS" ;;
  "container namespace list")    printf '%s' "$SCW_FAKE_NAMESPACES" ;;
  "container namespace create")  echo '{"id":"ns-new","name":"localchat","status":"ready"}' ;;
  "container namespace get")     echo '{"id":"ns-x","status":"ready"}' ;;
  "container container list")    printf '%s' "$SCW_FAKE_CONTAINERS" ;;
  "container container create")  echo '{"id":"ctr-new","status":"ready"}' ;;
  "container container update")  echo '{"id":"ctr-x","status":"ready"}' ;;
  "container container get")     echo '{"id":"ctr-x","status":"ready","image":"ghcr.io/jwvanderstam/localchat:sha-deployed","public_endpoint":"https://example.fnc.fr-par.scw.cloud"}' ;;
  "vpc private-network list")    printf '%s' "$SCW_FAKE_NETWORKS" ;;
  "vpc private-network create")  echo '{"id":"pn-new"}' ;;
  "instance security-group list")   printf '%s' "$SCW_FAKE_SECGROUPS" ;;
  "instance security-group create") echo '{"security_group":{"id":"sg-new"}}' ;;
  "instance server list")        printf '%s' "$SCW_FAKE_SERVERS" ;;
  "instance server create")      echo '{"id":"srv-new","state":"stopped"}' ;;
  "instance server get")         echo '{"id":"srv-x","state":"running"}' ;;
  "instance server start")       echo '{}' ;;
  "instance private-nic create") echo '{"private_nic":{"id":"nic-1"}}' ;;
  "ipam ip list")                printf '%s' "$SCW_FAKE_IPAM" ;;
  *) echo "unexpected: $*" >&2; exit 1 ;;
esac
"""

PROJECT = json.dumps([{"id": "proj-x", "name": "localchat-test"}])
IPAM = json.dumps(
    [
        {"address": "fda9::1/64", "resource": {"name": "localchat-embeddings"}},
        {"address": "172.16.0.2/22", "resource": {"name": "localchat-embeddings"}},
    ]
)


def _env(tmp_path, **over):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "scw"
    fake.write_text(FAKE_SCW, newline="\n")
    fake.chmod(0o755)
    log = tmp_path / "calls.log"
    log.touch()

    db_env = tmp_path / "db.env"
    db_env.write_text(
        "PG_HOST=db.example\nPG_PORT=5432\nPG_DB=localchat\n"
        "PG_USER=app-x\nPG_PASSWORD=dbsecret\nPG_SSLMODE=require\n",
        newline="\n",
    )
    secret_env = tmp_path / "deploy.env"
    secret_env.write_text(
        "SECRET_KEY=s1\nJWT_SECRET_KEY=s2\nENCRYPTION_KEY=s3\n"
        "METRICS_TOKEN=s4\nADMIN_PASSWORD=s5\n",
        newline="\n",
    )

    environ = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "SCW_FAKE_LOG": str(log),
        "SCW_FAKE_PROJECTS": PROJECT,
        "SCW_FAKE_NAMESPACES": "[]",
        "SCW_FAKE_CONTAINERS": "[]",
        "SCW_FAKE_NETWORKS": "[]",
        "SCW_FAKE_SECGROUPS": "[]",
        "SCW_FAKE_SERVERS": "[]",
        "SCW_FAKE_IPAM": IPAM,
        "DEPLOY_DB_ENV": str(db_env),
        "DEPLOY_SECRET_ENV": str(secret_env),
    }
    environ.update(over)
    environ.pop("SCW_PROFILE", None)
    return environ, log


# Phase 4 presupposes Phase 2: the namespace and container must already exist.
DEPLOYED = {
    "SCW_FAKE_NAMESPACES": json.dumps([{"id": "ns-x", "name": "localchat"}]),
    "SCW_FAKE_CONTAINERS": json.dumps([{"id": "ctr-x", "name": "localchat"}]),
}


def _run(script, tmp_path, **over):
    environ, log = _env(tmp_path, **over)
    proc = subprocess.run(
        [BASH, str(script)], env=environ, capture_output=True, text=True
    )
    calls = [line for line in log.read_text().splitlines() if line.strip()]
    return proc, calls


class TestTheContainerIsCreatedTheWayScalewayAccepts:
    def test_memory_is_passed_with_a_unit_not_as_bytes(self, tmp_path):
        """3072000000 is refused: "size must be defined using the G or GB unit"."""
        proc, calls = _run(CONTAINER_SH, tmp_path)

        assert proc.returncode == 0, proc.stderr
        create = next(c for c in calls if c.startswith("container container create"))
        assert "memory-limit-bytes=3GB" in create

    def test_scale_is_pinned_to_one(self, tmp_path):
        """D1 and D2: no cold start on a 3 GB image, no concurrency multiplying the bill."""
        _, calls = _run(CONTAINER_SH, tmp_path)

        create = next(c for c in calls if c.startswith("container container create"))
        assert "min-scale=1" in create and "max-scale=1" in create

    def test_secrets_go_in_the_secret_map_and_never_the_plain_one(self, tmp_path):
        proc, calls = _run(CONTAINER_SH, tmp_path)

        create = next(c for c in calls if c.startswith("container container create"))
        assert "secret-environment-variables.PG_PASSWORD=dbsecret" in create
        assert "environment-variables.PG_PASSWORD" not in create.replace(
            "secret-environment-variables.PG_PASSWORD", ""
        )
        assert "s5" not in proc.stdout, "the admin password must not be printed"

    def test_ollama_is_left_unset_when_no_instance_exists_yet(self, tmp_path):
        _, calls = _run(CONTAINER_SH, tmp_path)

        create = next(c for c in calls if c.startswith("container container create"))
        assert "OLLAMA_BASE_URL" not in create


class TestASecondRunUpdatesRatherThanDuplicating:
    def test_an_existing_container_is_updated_in_place(self, tmp_path):
        existing = json.dumps([{"id": "ctr-x", "name": "localchat"}])
        namespaces = json.dumps([{"id": "ns-x", "name": "localchat"}])
        proc, calls = _run(
            CONTAINER_SH,
            tmp_path,
            SCW_FAKE_CONTAINERS=existing,
            SCW_FAKE_NAMESPACES=namespaces,
        )

        assert proc.returncode == 0, proc.stderr
        assert not any(c.startswith("container container create") for c in calls)
        assert any(c.startswith("container container update") for c in calls)

    def test_an_update_resends_every_variable_because_scaleway_replaces_the_map(self, tmp_path):
        """Sending only the changed variable silently drops the rest."""
        existing = json.dumps([{"id": "ctr-x", "name": "localchat"}])
        namespaces = json.dumps([{"id": "ns-x", "name": "localchat"}])
        _, calls = _run(
            CONTAINER_SH,
            tmp_path,
            SCW_FAKE_CONTAINERS=existing,
            SCW_FAKE_NAMESPACES=namespaces,
            DEPLOY_OLLAMA_URL="http://172.16.0.2:11434",
        )

        update = next(c for c in calls if c.startswith("container container update"))
        for expected in (
            "environment-variables.APP_ENV=production",
            "environment-variables.PG_HOST=db.example",
            "environment-variables.PG_SSLMODE=require",
            "environment-variables.OLLAMA_BASE_URL=http://172.16.0.2:11434",
            "secret-environment-variables.SECRET_KEY=s1",
            "secret-environment-variables.METRICS_TOKEN=s4",
        ):
            assert expected in update, f"{expected} was dropped from the update"


class TestTheEmbeddingsInstanceIsBuiltSafely:
    def test_the_security_group_drops_inbound(self, tmp_path):
        """Scaleway's default is accept, which would publish Ollama to the internet."""
        proc, calls = _run(EMBEDDINGS_SH, tmp_path, **DEPLOYED)

        assert proc.returncode == 0, proc.stderr
        sg = next(c for c in calls if c.startswith("instance security-group create"))
        assert "inbound-default-policy=drop" in sg
        assert "outbound-default-policy=accept" in sg

    def test_the_instance_lands_in_fr_par_2(self, tmp_path):
        """The only zone offering both the L4 and the larger L40S."""
        _, calls = _run(EMBEDDINGS_SH, tmp_path, **DEPLOYED)

        create = next(c for c in calls if c.startswith("instance server create"))
        assert "zone=fr-par-2" in create

    def test_the_instance_joins_the_private_network(self, tmp_path):
        _, calls = _run(EMBEDDINGS_SH, tmp_path, **DEPLOYED)

        assert any(c.startswith("instance private-nic create") for c in calls)

    def test_the_container_is_pointed_at_the_private_ipv4(self, tmp_path):
        """IPAM returns IPv6 first; the container needs the v4 address."""
        proc, calls = _run(EMBEDDINGS_SH, tmp_path, **DEPLOYED)

        assert "172.16.0.2" in proc.stdout
        update = [c for c in calls if c.startswith("container container update")]
        assert any("OLLAMA_BASE_URL=http://172.16.0.2:11434" in c for c in update)

    def test_rewiring_the_container_keeps_the_image_it_is_running(self, tmp_path):
        """Phase 4 re-runs Phase 2, so an unpassed knob reverts to Phase 2's default.

        A stack deployed on an explicit tag came back running the release tag
        DEPLOY_IMAGE_TAG defaults to — silently, because the inner run is
        redirected to /dev/null.
        """
        proc, calls = _run(EMBEDDINGS_SH, tmp_path, **DEPLOYED)

        update = [c for c in calls if c.startswith("container container update")]
        assert update, proc.stdout
        assert "image=ghcr.io/jwvanderstam/localchat:sha-deployed" in update[0]

    def test_no_model_is_pulled_from_the_script(self, tmp_path):
        """The cloud-init pull failed silently once; the app's endpoint does it now."""
        proc, _ = _run(EMBEDDINGS_SH, tmp_path, **DEPLOYED)

        assert "verify_deployment.py" in proc.stdout
        assert "--pull-model" in proc.stdout


class TestItRefusesRatherThanGuesses:
    def test_a_missing_database_credential_stops_the_run(self, tmp_path):
        proc, calls = _run(CONTAINER_SH, tmp_path, DEPLOY_DB_ENV=str(tmp_path / "absent.env"))

        assert proc.returncode != 0
        assert "provision.sh" in proc.stderr
        assert calls == []

    def test_deploying_embeddings_without_a_container_is_refused(self, tmp_path):
        proc, _ = _run(EMBEDDINGS_SH, tmp_path, SCW_FAKE_NAMESPACES="[]")

        assert proc.returncode != 0
        assert "deploy_container.sh" in proc.stderr
