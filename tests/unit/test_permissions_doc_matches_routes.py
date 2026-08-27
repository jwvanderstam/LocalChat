"""`docs/PERMISSIONS.md` lists every route the application actually serves.

PERMISSIONS.md tells its own reader to "regenerate after changing any route; drift
between this file and the code is the failure mode it exists to prevent." That
instruction was discipline, and on 2026-08-27 it had been missed three times: the table
held 98 rows, its distribution claimed 102, and the code served 111. Six of the eight
absent routes governed credentials or workspace membership.

TQ-1a's introspection did not catch it, and could not: it asserts every route is
*guarded*, which is a property of the code. Whether the matrix *documents* a route is a
property of the document, and nothing looked. This is that check — the same ratchet
shape as HK-6, applied to the one document whose whole purpose is to match the route
table.

The comparison is on (method, path) with path parameters normalised, because the doc
writes `{workspace_id}` where a different module writes `{id}` for the same shape.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROUTES_DIR = Path(__file__).resolve().parents[2] / "src" / "routes_fastapi"
_APP_FACTORY = Path(__file__).resolve().parents[2] / "src" / "app_fastapi.py"
_DOC = Path(__file__).resolve().parents[2] / "docs" / "PERMISSIONS.md"

_VERBS = "get|post|put|patch|delete"


def _normalise(path: str) -> str:
    """Collapse `{anything}` so `{workspace_id}` and `{id}` compare equal."""
    return re.sub(r"\{[^}]+\}", "{}", path).rstrip("/") or "/"


def _module_prefixes() -> dict[str, str]:
    src = _APP_FACTORY.read_text(encoding="utf-8")
    return {
        m.group(1): (m.group(2) or "")
        for m in re.finditer(
            r'include_router\(\s*([A-Za-z_]+)\.router\s*'
            r'(?:,\s*prefix\s*=\s*["\']([^"\']*)["\'])?',
            src,
        )
    }


def _code_routes() -> set[tuple[str, str]]:
    """Every route decorator, keyed by verb and path relative to its include prefix.

    The doc's Path column is module-relative — it omits the `/api` that
    `include_router` adds — so the router's own inner prefix is kept and the
    include prefix is not.
    """
    found: set[tuple[str, str]] = set()
    for module in _module_prefixes():
        text = (_ROUTES_DIR / f"{module}.py").read_text(encoding="utf-8")
        inner = re.search(r"APIRouter\(([^)]*)\)", text, re.S)
        prefix = ""
        if inner:
            q = re.search(r'prefix\s*=\s*["\']([^"\']*)["\']', inner.group(1))
            prefix = q.group(1) if q else ""
        for m in re.finditer(rf'@router\.({_VERBS})\(\s*["\']([^"\']*)["\']', text):
            found.add((m.group(1).upper(), _normalise(prefix + m.group(2))))
    return found


def _documented_routes() -> list[tuple[str, str, str]]:
    table = _DOC.read_text(encoding="utf-8").split("## Full table", 1)[1]
    return [
        (m.group(1), _normalise(m.group(2)), m.group(3).strip())
        for m in re.finditer(
            r"^\|\s*`[^`]+`\s*\|\s*(GET|POST|PUT|PATCH|DELETE)\s*\|\s*`([^`]+)`\s*\|\s*([^|]+)\|",
            table,
            re.M,
        )
    ]


@pytest.mark.unit
class TestTheCheckSeesSomething:
    """A comparison between two empty sets passes and proves nothing."""

    def test_code_routes_were_found(self):
        assert len(_code_routes()) > 90

    def test_doc_rows_were_parsed(self):
        assert len(_documented_routes()) > 90


@pytest.mark.unit
class TestPermissionsDocMatchesTheRouteTable:
    def test_every_route_is_documented(self):
        undocumented = _code_routes() - {(v, p) for v, p, _ in _documented_routes()}
        assert not undocumented, (
            "routes exist with no row in docs/PERMISSIONS.md: "
            + ", ".join(f"{v} {p}" for v, p in sorted(undocumented))
        )

    def test_no_row_describes_a_route_that_is_gone(self):
        stale = {(v, p) for v, p, _ in _documented_routes()} - _code_routes()
        assert not stale, (
            "docs/PERMISSIONS.md documents routes the app no longer serves: "
            + ", ".join(f"{v} {p}" for v, p in sorted(stale))
        )

    def test_distribution_total_matches_the_table(self):
        """The summary table is written by hand and drifted from its own rows."""
        doc = _DOC.read_text(encoding="utf-8")
        claimed = re.search(r"\|\s*\*\*Total\*\*\s*\|\s*\*\*(\d+)\*\*\s*\|", doc)
        assert claimed, "distribution table lost its Total row"
        assert int(claimed.group(1)) == len(_documented_routes())

    def test_every_row_names_a_known_level(self):
        levels = {"public", "authenticated", "ws:viewer", "ws:editor", "ws:owner", "admin"}
        seen = {lvl.replace("**", "").strip() for _, _, lvl in _documented_routes()}
        assert seen <= levels, f"unknown permission level(s): {sorted(seen - levels)}"
