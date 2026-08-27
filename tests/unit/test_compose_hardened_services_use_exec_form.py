"""Services built from the hardened image invoke no shell.

The runtime stage of `Dockerfile` is a Docker Hardened Image: no shell, no package
manager, no `curl`. A compose service built from it must therefore use exec-form
`command` and an exec-form `healthcheck` — `sh -c "..."` and `CMD-SHELL` cannot execute,
and the container dies at start with an OCI "executable file not found" error rather than
anything resembling an application failure.

The `app` service was converted when the image was hardened. The three `mcp-*` services
were not, and `docker compose --profile mcp up` could not start any of them from that day
until 2026-08-27. Nothing caught it because `docker-smoke` builds and boots `app` only —
the `mcp` profile is opt-in and no CI job has ever started it.

This is the cheap standing check that `docker-smoke` does not cover: it reads the compose
file rather than running anything, so it costs nothing and applies to every service built
from the hardened Dockerfile.

Services on *other* images are deliberately not checked — `db` runs `pgvector/pgvector`,
which has a shell, and its `CMD-SHELL`/`pg_isready` healthcheck is correct.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="PyYAML parses the compose file")

_COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"
#: Absent from the hardened runtime image; naming one in a command means it cannot start.
_ABSENT_BINARIES = ("sh", "bash", "curl", "wget")


def _compose() -> dict:
    return yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))


def _hardened_services() -> dict[str, dict]:
    """Services built from the repo's own Dockerfile, i.e. running the hardened image."""
    out = {}
    for name, svc in (_compose().get("services") or {}).items():
        build = svc.get("build")
        if isinstance(build, dict) and build.get("dockerfile") == "Dockerfile":
            out[name] = svc
    return out


@pytest.mark.unit
class TestTheCheckSeesSomething:
    def test_compose_parses_and_has_hardened_services(self):
        found = _hardened_services()
        assert found, "no service builds from Dockerfile — the check would pass vacuously"
        assert "app" in found


@pytest.mark.unit
class TestHardenedServicesInvokeNoShell:
    def test_command_is_exec_form(self):
        offenders = [
            name
            for name, svc in _hardened_services().items()
            if isinstance(svc.get("command"), str)
        ]
        assert not offenders, (
            "string-form `command` runs through a shell the hardened image does not have: "
            + ", ".join(sorted(offenders))
        )

    def test_command_names_no_absent_binary(self):
        offenders = []
        for name, svc in _hardened_services().items():
            cmd = svc.get("command")
            argv = cmd if isinstance(cmd, list) else ([cmd] if cmd else [])
            if argv and str(argv[0]) in _ABSENT_BINARIES:
                offenders.append(f"{name} (runs {argv[0]!r})")
        assert not offenders, (
            "command invokes a binary absent from the hardened image: " + ", ".join(sorted(offenders))
        )

    def test_healthcheck_is_exec_form_and_uses_present_binaries(self):
        offenders = []
        for name, svc in _hardened_services().items():
            test = (svc.get("healthcheck") or {}).get("test")
            if test is None:
                continue
            if isinstance(test, str):
                offenders.append(f"{name} (string healthcheck)")
                continue
            if test and test[0] == "CMD-SHELL":
                offenders.append(f"{name} (CMD-SHELL)")
                continue
            if len(test) > 1 and str(test[1]) in _ABSENT_BINARIES:
                offenders.append(f"{name} (runs {test[1]!r})")
        assert not offenders, (
            "healthcheck cannot run in the hardened image: " + ", ".join(sorted(offenders))
        )
