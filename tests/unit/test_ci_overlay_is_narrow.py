"""The CI overlay replaces what a runner cannot provide, and nothing else.

`docker-compose.ci.yml` exists so the `security-smoke` job can boot the shipped stack
on a GitHub-hosted runner: there is no NVIDIA runtime for the `app` and `ollama` device
reservations, and no disk for a 9.7 GB Ollama image on top of a ~10 GB app image.

That is a standing hazard. The job's whole value is that it attacks the configuration
*as shipped*, so every key this overlay grows is a key the job stops testing — and it
would stay green while doing less, which is the failure mode worth a test. The ticket
(ROADMAP P2-2) states the rule as: a job that rewrites the thing it is verifying proves
something else.

So this pins the overlay's surface exactly. It is deliberately an equality check rather
than a "does not contain" check: a new key nobody thought of fails it too.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="PyYAML parses the compose files")

_ROOT = Path(__file__).resolve().parents[2]
_OVERLAY = _ROOT / "docker-compose.ci.yml"
_SHIPPED = _ROOT / "docker-compose.yml"


class _TagTolerantLoader(yaml.SafeLoader):
    """Compose's merge tags (`!reset`) are not YAML that SafeLoader knows."""


_TagTolerantLoader.add_constructor(
    "!reset", lambda loader, node: loader.construct_sequence(node)
)


def _overlay() -> dict:
    return yaml.load(_OVERLAY.read_text(encoding="utf-8"), Loader=_TagTolerantLoader)


def _shipped() -> dict:
    return yaml.safe_load(_SHIPPED.read_text(encoding="utf-8"))


def _devices(service: dict) -> list:
    return service["deploy"]["resources"]["reservations"]["devices"]


def test_overlay_declares_only_services() -> None:
    assert set(_overlay()) == {"services"}


def test_overlay_touches_only_app_and_ollama() -> None:
    assert set(_overlay()["services"]) == {"app", "ollama"}


def test_overlay_changes_nothing_about_app_but_its_device_reservation() -> None:
    app = _overlay()["services"]["app"]
    assert app == {"deploy": {"resources": {"reservations": {"devices": []}}}}


def test_overlay_changes_only_ollamas_image_command_healthcheck_and_devices() -> None:
    assert set(_overlay()["services"]["ollama"]) == {
        "image",
        "command",
        "healthcheck",
        "deploy",
    }


def test_overlay_names_nothing_the_security_smoke_job_probes() -> None:
    """Proxy trust, the MCP token and the nginx config are the assertions; they stay shipped."""
    text = _OVERLAY.read_text(encoding="utf-8")
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    named = [
        k
        for k in ("TRUSTED_PROXY_IPS", "MCP_AUTH_TOKEN", "networks", "nginx", "environment")
        if k in body
    ]
    assert named == []


def test_the_shipped_stack_still_reserves_a_gpu_for_app_and_ollama() -> None:
    """The overlay's whole reason. If this fails, delete the overlay rather than fix it."""
    services = _shipped()["services"]
    drivers = {name: [d["driver"] for d in _devices(services[name])] for name in ("app", "ollama")}
    assert drivers == {"app": ["nvidia"], "ollama": ["nvidia"]}
