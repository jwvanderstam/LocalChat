"""Regression: running migrations must not silence the application's loggers.

``migrations/env.py`` calls ``logging.config.fileConfig`` on ``alembic.ini``. That
helper defaults to ``disable_existing_loggers=True``, and ``alembic.ini`` declares
only root/sqlalchemy/alembic — so the default switched off every ``src.*`` logger,
``uvicorn.access`` and the request log.

Migrations run in-process at startup, so the effect lasted the whole life of the
process: the app kept serving and stopped logging anything. That hid a real
``MultipleHeads`` error which had been raised and logged on every boot.

The ``fileConfig`` calls run in a subprocess on purpose — it rewrites global logging
state (root handlers included), which would leak into every later test in the session.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO / "alembic.ini"
ENV_PY = REPO / "migrations" / "env.py"
APP_LOGGERS = ("src.app_bootstrap", "src.db.connection", "uvicorn.access", "src.utils.request_id")


def _disabled_after_file_config(logger_name: str, *, keyword: bool) -> bool:
    """Return logger.disabled after fileConfig runs, in a throwaway interpreter."""
    call = (
        "fileConfig(ini, disable_existing_loggers=False)" if keyword else "fileConfig(ini)"
    )
    code = (
        "import logging\n"
        "from logging.config import fileConfig\n"
        f"ini = {str(ALEMBIC_INI)!r}\n"
        f"log = logging.getLogger({logger_name!r})\n"
        "log.disabled = False\n"
        f"{call}\n"
        "print(log.disabled)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=REPO
    )
    return out.stdout.strip() == "True"


@pytest.mark.unit
def test_alembic_ini_exists():
    assert ALEMBIC_INI.is_file()


@pytest.mark.unit
@pytest.mark.parametrize("logger_name", APP_LOGGERS)
def test_app_loggers_survive_alembic_file_config(logger_name):
    """The call env.py makes must leave application loggers enabled."""
    assert _disabled_after_file_config(logger_name, keyword=True) is False


@pytest.mark.unit
def test_default_would_have_disabled_them():
    """Pins the reason the keyword is required — the default is what broke it."""
    assert _disabled_after_file_config("src.app_bootstrap", keyword=False) is True


@pytest.mark.unit
def test_env_py_passes_the_keyword():
    """Guards the call site itself, not just the library behaviour."""
    assert "disable_existing_loggers=False" in ENV_PY.read_text(encoding="utf-8")
