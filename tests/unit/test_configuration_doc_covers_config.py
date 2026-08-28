"""`docs/CONFIGURATION.md` names every environment variable `src/config.py` reads.

CONFIGURATION.md is the configuration reference, and on 2026-08-27 it documented 45 of
the 107 values config.py actually read. The 62 it missed were not obscure: they included
`WEB_SEARCH_ENABLED`, `TOOL_CALLING_ENABLED`, `GRAPH_RAG_ENABLED`, `MCP_ENABLED`,
`PLUGINS_ENABLED`, `MODEL_ROUTER_ENABLED` and `CLOUD_FALLBACK_ENABLED` — the master
switches for seven subsystems. A reader could not discover those features existed.

The architecture rule that all configuration lives in `src/config.py` is enforced by
review; that the reference *describes* it was enforced by nothing. This is that check.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG = _ROOT / "src" / "config.py"
_DOC = _ROOT / "docs" / "CONFIGURATION.md"


def _env_vars_read() -> set[str]:
    src = _CONFIG.read_text(encoding="utf-8")
    found = set(re.findall(r"os\.(?:environ\.get|getenv)\(\s*['\"]([A-Z0-9_]+)['\"]", src))
    found |= set(re.findall(r"os\.environ\[\s*['\"]([A-Z0-9_]+)['\"]\s*\]", src))
    return found


def _mentions(doc: str, var: str) -> bool:
    """Whole-token match, so `REDIS_PORT` is not satisfied by `REDIS_PORTAL`."""
    return re.search(rf"(^|[^A-Z_]){re.escape(var)}([^A-Z_]|$)", doc) is not None


@pytest.mark.unit
class TestTheCheckSeesSomething:
    def test_config_reads_were_found(self):
        assert len(_env_vars_read()) > 90, "config.py parse found almost nothing"


@pytest.mark.unit
class TestEveryConfigValueIsDocumented:
    def test_no_env_var_is_undocumented(self):
        doc = _DOC.read_text(encoding="utf-8")
        missing = sorted(v for v in _env_vars_read() if not _mentions(doc, v))
        assert not missing, (
            f"{len(missing)} environment variable(s) read by src/config.py and absent "
            f"from docs/CONFIGURATION.md: " + ", ".join(missing)
        )


@pytest.mark.unit
class TestConfigStaysTheOnlyReader:
    def test_no_os_getenv_outside_config(self):
        """The architecture rule this document depends on: config.py is the one reader."""
        offenders = []
        for path in (_ROOT / "src").rglob("*.py"):
            if path.name == "config.py":
                continue
            text = path.read_text(encoding="utf-8")
            if re.search(r"os\.(?:environ\.get|getenv)\(|os\.environ\[", text):
                offenders.append(str(path.relative_to(_ROOT)).replace("\\", "/"))
        assert not offenders, (
            "os.getenv outside src/config.py makes a value invisible to the "
            "configuration reference: " + ", ".join(sorted(offenders))
        )
