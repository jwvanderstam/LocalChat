"""`APP_VERSION` is declared in three places and nothing derives it from the tag.

`src/config.py`, `docker-compose.yml`'s `${APP_VERSION:-...}` default, and the row in
`docs/CONFIGURATION.md` each carry the number independently. That is a drift class with
no natural signal: the version a deployment reports at `GET /api/status` is not something
anyone reads until they need it to be right.

It had already drifted. Until 2026-08-31 the three read `1.0.0`, `0.5.0` and `1.0.0`
against a `v3.0.0-beta.1` tag — so a containerised deployment reported 0.5.0, a host-run
one reported 1.0.0, and neither was the version being run. `docs/CONFIGURATION.md`
described the problem in prose for weeks, which is what documentation can do and a test
cannot: nothing *failed*.

This is the check that fails. It does not assert a particular version — bumping a release
should not require editing this file — only that whatever the three say, they say the same
thing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _config_default() -> str:
    """The literal in src/config.py, read as text.

    Not `config.APP_VERSION`: importing config reads the environment, and a shell that
    happens to export APP_VERSION would make this pass against the wrong thing.
    """
    text = (REPO_ROOT / "src" / "config.py").read_text(encoding="utf-8")
    match = re.search(r"^APP_VERSION:\s*str\s*=\s*os\.environ\.get\(\s*'APP_VERSION'\s*,\s*'([^']+)'\s*\)",
                      text, re.MULTILINE)
    assert match, "src/config.py no longer declares APP_VERSION the way this test reads it"
    return match.group(1)


def _compose_default() -> str:
    text = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    match = re.search(r"APP_VERSION:\s*\$\{APP_VERSION:-([^}]*)\}", text)
    assert match, "docker-compose.yml no longer sets an APP_VERSION default"
    return match.group(1)


def _documented_default() -> str:
    text = (REPO_ROOT / "docs" / "CONFIGURATION.md").read_text(encoding="utf-8")
    match = re.search(r"^\|\s*`APP_VERSION`\s*\|\s*`([^`]+)`\s*\|", text, re.MULTILINE)
    assert match, "docs/CONFIGURATION.md no longer has an APP_VERSION row"
    return match.group(1)


@pytest.mark.unit
class TestAppVersionDefaults:

    def test_compose_matches_config(self):
        # The one that bit: compose is the supported deployment, so its default is what a
        # real user's /api/status reports.
        assert _compose_default() == _config_default()

    def test_documentation_matches_config(self):
        assert _documented_default() == _config_default()

    def test_the_default_is_a_release_version_not_a_placeholder(self):
        # `1.0.0` survived to a v3 tag because nothing said it was a placeholder. A bare
        # major.minor.patch is required, so an empty or `latest`-style value fails here.
        assert re.fullmatch(r"\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?", _config_default()), (
            f"APP_VERSION default {_config_default()!r} is not a semantic version"
        )
