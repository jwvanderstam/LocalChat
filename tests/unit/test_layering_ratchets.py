"""QP-3 — ratchets on the layering ADR-7 records: numbers that may only go down.

Phase 2 moves one aggregate per PR (QP-4). These pin today's debt so it cannot grow in
the meantime, and fail when it shrinks without the number being lowered, so each PR that
pays some off records it. QP-5 takes all three to zero.

The contracts themselves run as `lint-imports` in CI (pyproject.toml,
[tool.importlinter]); this file pins what the contracts cannot count.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]

#: `app.state.db` in route modules: a handler reaching the database itself instead of a
#: service. 81 on 2026-10-23 (`3623840`); 72 after QP-4 users and auth. Lower it in the PR that removes some.
APP_STATE_DB_IN_ROUTES = 72

#: Direct imports from a route into src.db that the forbidden contract tolerates today.
IGNORED_ROUTE_TO_DB_IMPORTS = 2

#: Groups of modules that import each other, found with grimp's graph. Architecture exit
#: criterion 5 is none at all.
KNOWN_CYCLES = {
    frozenset({"src.utils.logging_config", "src.utils.request_id"}),
    frozenset({"src.config", "src.utils.encryption"}),
}


def test_route_modules_reach_the_database_no_more_often_than_recorded():
    found = sum(
        len(re.findall(r"app\.state\.db\b", path.read_text(encoding="utf-8")))
        for path in (_ROOT / "src" / "routes_fastapi").glob("*.py")
    )
    assert found == APP_STATE_DB_IN_ROUTES, (
        f"{found} uses of app.state.db in src/routes_fastapi, ratchet says "
        f"{APP_STATE_DB_IN_ROUTES}. Above it: move the new access into a service. Below it: "
        "lower APP_STATE_DB_IN_ROUTES in this PR."
    )


def test_the_contract_tolerates_no_more_route_to_db_imports_than_recorded():
    contracts = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    forbidden = next(
        c for c in contracts["tool"]["importlinter"]["contracts"] if c["type"] == "forbidden"
    )
    assert len(forbidden.get("ignore_imports", [])) == IGNORED_ROUTE_TO_DB_IMPORTS


def _cycles() -> set[frozenset[str]]:
    grimp = pytest.importorskip("grimp", reason="grimp comes with import-linter (requirements-dev)")
    graph = grimp.build_graph("src")
    adjacency = {m: graph.find_modules_directly_imported_by(m) for m in graph.modules}
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    found: set[frozenset[str]] = set()
    counter = [0]
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 10_000))

    def visit(module: str) -> None:
        index[module] = low[module] = counter[0]
        counter[0] += 1
        stack.append(module)
        on_stack.add(module)
        for target in adjacency.get(module, ()):
            if target not in index:
                visit(target)
                low[module] = min(low[module], low[target])
            elif target in on_stack:
                low[module] = min(low[module], index[target])
        if low[module] == index[module]:
            group = set()
            while True:
                member = stack.pop()
                on_stack.discard(member)
                group.add(member)
                if member == module:
                    break
            if len(group) > 1:
                found.add(frozenset(group))

    for module in sorted(graph.modules):
        if module not in index:
            visit(module)
    return found


def test_no_import_cycle_beyond_the_recorded_ones():
    assert _cycles() == KNOWN_CYCLES
