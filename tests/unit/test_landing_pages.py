"""The landing host's generated pages are current, and publish no identifier.

`log.html` and `deploy.html` are built from the deployment log and the scripts by
`scripts/scaleway/landing/build.py` and committed, because the host serves files,
not a build. Two things can go wrong: a session updates the log and forgets to
rebuild (the page silently lags the record), or a new kind of identifier reaches
the log that the redaction does not know (the page publishes it). §13 of
DEPLOYMENT_SCALEWAY.md forbids the second; this is its IVP.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "scripts" / "scaleway" / "landing" / "build.py"

pytestmark = pytest.mark.unit


def _module():
    spec = importlib.util.spec_from_file_location("landing_build", BUILD)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestTheCommittedPagesMatchTheirSources:
    def test_check_passes_against_the_working_tree(self):
        proc = subprocess.run(
            [sys.executable, str(BUILD), "--check"], capture_output=True, text=True, cwd=ROOT
        )
        assert proc.returncode == 0, (
            proc.stdout + proc.stderr + "\n(run scripts/scaleway/landing/build.py and commit)"
        )


class TestRedaction:
    def test_every_kind_of_identifier_in_the_log_is_replaced(self):
        build = _module()
        text = (
            "project 986172ba-5b88-4fd0-8d6d-83ac3872a692, short 8b863ff4, "
            "box 172.16.8.2 and 51.159.130.209, endpoint "
            "https://localchat3b47dd02-localchat.functions.fnc.fr-par.scw.cloud, "
            "db a9911331-5129-42f7-aa54-9e505bedb2bb.pg.sdb.fr-par.scw.cloud"
        )
        out = build.redact(text)
        assert out == (
            "project <id>, short <id>, box <address> and <address>, endpoint <endpoint>, "
            "db <id>.pg.sdb.fr-par.scw.cloud"
        )

    def test_a_git_sha_and_a_pr_number_survive(self):
        """Seven hex digits and #369 are provenance, not reach; a reader needs them."""
        build = _module()
        assert build.redact("onto sha-af6012b, fixed in #369 at 12:11:21") == (
            "onto sha-af6012b, fixed in #369 at 12:11:21"
        )

    def test_the_published_log_carries_nothing_identifier_shaped(self):
        html = (BUILD.parent / "log.html").read_text(encoding="utf-8")
        text = re.sub(r"<[^>]+>", "", html)
        assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}", text)
        assert not re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text)
        assert "functions.fnc" not in text
