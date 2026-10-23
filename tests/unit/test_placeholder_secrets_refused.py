"""S1 — a secret copied unchanged from `.env.example` must stop the boot in every APP_ENV.

The placeholders are published in the repository, so a host running with one is running
with a known secret. Before S1 only `APP_ENV=production` checked them, and outside it the
module even swapped a placeholder SECRET_KEY for a random one, so a forgotten APP_ENV
turned "known admin password" into a silent success. The values are read from
`.env.example` itself, so a placeholder edited there is still covered here.
"""

from __future__ import annotations

import importlib
import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from src import config

_ROOT = Path(__file__).resolve().parents[2]
_SECRETS = ("SECRET_KEY", "JWT_SECRET_KEY", "ADMIN_PASSWORD")


def _example_value(name: str) -> str:
    text = (_ROOT / ".env.example").read_text(encoding="utf-8")
    match = re.search(rf"^{name}=(.*)$", text, re.M)
    if match is None:
        raise AssertionError(f"{name} is not assigned in .env.example")
    return match.group(1).strip()


def _strong() -> dict[str, str]:
    return {
        "SECRET_KEY": "s" * 32,
        "JWT_SECRET_KEY": "j" * 32,
        "ADMIN_PASSWORD": "a-strong-admin-password",
    }


def _critical_messages(monkeypatch: pytest.MonkeyPatch, **values: str) -> list[str]:
    for key, value in values.items():
        monkeypatch.setattr(config, key, value)
    with patch.object(config.logger, "critical") as critical, pytest.raises(SystemExit):
        config.validate_secrets()
    return [call.args[1] for call in critical.call_args_list]


@pytest.mark.parametrize("app_env", ["", "development"])
@pytest.mark.parametrize("name", _SECRETS)
def test_an_example_placeholder_stops_the_boot_outside_production(
    monkeypatch: pytest.MonkeyPatch, name: str, app_env: str
) -> None:
    values = {**_strong(), name: _example_value(name)}
    messages = _critical_messages(monkeypatch, APP_ENV=app_env, **values)
    assert messages == [f"{name} is a known placeholder — set a random value"]


def test_an_admin_password_one_short_of_the_minimum_stops_the_boot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    short = "x" * (config.ADMIN_PASSWORD_MIN_LENGTH - 1)
    messages = _critical_messages(
        monkeypatch, APP_ENV="development", **{**_strong(), "ADMIN_PASSWORD": short}
    )
    assert messages == ["ADMIN_PASSWORD is too short (minimum 16 characters)"]


def test_an_admin_password_at_the_minimum_boots(monkeypatch: pytest.MonkeyPatch) -> None:
    exact = "x" * config.ADMIN_PASSWORD_MIN_LENGTH
    for key, value in {**_strong(), "APP_ENV": "development", "ADMIN_PASSWORD": exact}.items():
        monkeypatch.setattr(config, key, value)
    config.validate_secrets()


@pytest.fixture
def restore_config():
    yield
    importlib.reload(config)


@pytest.mark.parametrize("name", ["SECRET_KEY", "JWT_SECRET_KEY"])
def test_a_placeholder_key_is_kept_so_validation_can_refuse_it(
    restore_config: None, name: str
) -> None:
    """The module used to replace a placeholder with a generated key outside
    production, which hid it from validate_secrets entirely."""
    placeholder = _example_value(name)
    with patch.dict(os.environ, {"APP_ENV": "development", name: placeholder}):
        importlib.reload(config)
        assert getattr(config, name) == placeholder


def test_an_unset_key_outside_production_is_generated(restore_config: None) -> None:
    env = {k: v for k, v in os.environ.items() if k != "SECRET_KEY"}
    env["APP_ENV"] = "development"
    with patch.dict(os.environ, env, clear=True), patch("dotenv.load_dotenv"):
        importlib.reload(config)
        assert len(config.SECRET_KEY) == 64
        assert config.SECRET_KEY.lower() not in config._WEAK_PLACEHOLDERS


def test_env_example_starts_a_deployment_in_production() -> None:
    assert _example_value("APP_ENV") == "production"
