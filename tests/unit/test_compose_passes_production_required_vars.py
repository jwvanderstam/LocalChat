"""Services on the hardened image get every variable production mode demands.

`Dockerfile` pins `ENV APP_ENV=production` into the runtime stage, so *every* container
built from it is in production mode no matter what compose says. `src/config.py` refuses
to import in that mode without `SECRET_KEY` and `JWT_SECRET_KEY` — it raises `ValueError`
at module scope, which uvicorn surfaces as a crash before the first request.

The three `mcp-*` services passed `SECRET_KEY` and not `JWT_SECRET_KEY`. `mcp-local-docs`
and `mcp-cloud-connectors` import `src.config` at module level, so both crash-looped on
every `docker compose --profile mcp up`; `mcp-web-search` survived only because its `src`
import sits inside a function and would have failed on the first search instead. Found on
2026-09-25 by booting the profile for P2-2 — no CI job had ever started it, which is the
same blind spot that hid the exec-form defect this file's neighbour was written for.

This is the cheap half of that check: it reads the files, so it runs in the fast suite and
does not wait for `security-smoke` to boot anything.

The required set is derived from `config.py` rather than hardcoded, so adding a third
production-required variable fails here — pointing at the compose file that now needs it —
instead of at a container that will not start.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="PyYAML parses the compose file")

_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE = _ROOT / "docker-compose.yml"
_DOCKERFILE = _ROOT / "Dockerfile"
_CONFIG = _ROOT / "src" / "config.py"

#: `raise ValueError("NAME must be set in production!")` inside an APP_ENV guard.
_REQUIRED = re.compile(r'raise ValueError\("(\w+) must be set in production!"\)')


def _compose() -> dict:
    return yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))


def _required_in_production() -> set[str]:
    return set(_REQUIRED.findall(_CONFIG.read_text(encoding="utf-8")))


def _hardened_services() -> dict[str, dict]:
    out = {}
    for name, svc in (_compose().get("services") or {}).items():
        build = svc.get("build")
        if isinstance(build, dict) and build.get("dockerfile") == "Dockerfile":
            out[name] = svc
    return out


def test_the_runtime_image_pins_production_mode() -> None:
    """The premise. Without this the services could be in development mode and fine."""
    assert "APP_ENV=production" in _DOCKERFILE.read_text(encoding="utf-8")


def test_config_requires_exactly_these_variables_in_production() -> None:
    """Pins the set this file checks for. A third one added to config.py lands here first."""
    assert _required_in_production() == {"SECRET_KEY", "JWT_SECRET_KEY"}


@pytest.mark.parametrize("service", sorted(_hardened_services()))
def test_hardened_service_passes_every_production_required_variable(service: str) -> None:
    env = _hardened_services()[service].get("environment") or {}
    missing = sorted(_required_in_production() - set(env))
    assert missing == [], (
        f"{service} runs the hardened image (APP_ENV=production) but does not pass "
        f"{', '.join(missing)}; src/config.py raises at import and the container crash-loops"
    )
