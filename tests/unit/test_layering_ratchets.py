"""QP-3 — ratchets on the layering ADR-7 records: numbers that may only go down.

Phase 2 moves one aggregate per PR (QP-4). These pin today's debt so it cannot grow in
the meantime, and fail when it shrinks without the number being lowered, so each PR that
pays some off records it. QP-5 takes all three to zero.

The contracts themselves run as `lint-imports` in CI (pyproject.toml,
[tool.importlinter]); this file pins what the contracts cannot count.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]

#: A route module reaching the database itself instead of through a service. 81 on
#: 2026-10-23 (`3623840`); 72 after QP-4 users and auth; 58 after workspaces; 51 after
#: documents; 41 after conversations; 36 after memories; 23 after connectors.
#:
#: 4 after the last aggregate, counted differently from then on: `_services.py` is left
#: out, since building services from the database is its job, and the other spellings
#: (`app_state.db`, `getattr(app_state, "db")`) are counted, which the first pattern
#: missed. The four: `api_routes` hands the database to chat's functions three times,
#: which QP-5 turns into a service class, and the settings page reads its totals once.
#: Lower it in the PR that removes some.
APP_STATE_DB_IN_ROUTES = 4

#: The one route module that may read the database: it builds the services from it.
_PROVIDERS = "_services.py"
_DB_ACCESS = re.compile(r'app\.state\.db\b|app_state\.db\b|getattr\(app_state, "db"')

#: Direct imports from a route into src.db that the forbidden contract tolerates today.
IGNORED_ROUTE_TO_DB_IMPORTS = 0

#: Repository methods that touch a row-level-security table on a connection opened with
#: neither a workspace nor ALL_WORKSPACES, and so depend on migration 0021's transition
#: policy (QP-5, ADR-5's option B). 47 on 2026-10-25, 0 the same day: 0021 can be dropped.
UNSCOPED_RLS_METHODS = 0

#: The ten tables migration 0017 put under row-level security.
_RLS_TABLES = re.compile(
    r"\b(documents|conversations|memories|answer_feedback|connectors|workspace_api_keys"
    r"|workspace_members|document_chunks|conversation_messages|annotations)\b"
)

#: Groups of modules that import each other, found with grimp's graph. Architecture exit
#: criterion 5 is none at all, and since QP-4 there are none: config validates its
#: encryption key itself, and the request-ID context variable lives in logging_config.
KNOWN_CYCLES: set[frozenset[str]] = set()


def test_route_modules_reach_the_database_no_more_often_than_recorded():
    found = sum(
        len(_DB_ACCESS.findall(path.read_text(encoding="utf-8")))
        for path in (_ROOT / "src" / "routes_fastapi").glob("*.py")
        if path.name != _PROVIDERS
    )
    assert found == APP_STATE_DB_IN_ROUTES, (
        f"{found} uses of the database in src/routes_fastapi, ratchet says "
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


def _unscoped_rls_methods() -> list[str]:
    """``file:Class.method`` for each repository method that opens an unscoped connection.

    A method counts when its SQL names an RLS table and it either calls ``get_connection``
    without ``scope=``, or takes the caller's ``conn`` with no ``scope`` of its own (the
    caller then decides, which this cannot see). The boot's schema creation is excluded: it
    runs as the owner before any request.
    """
    found = []
    for path in sorted((_ROOT / "src" / "db").glob("*.py")):
        if path.name == "connection.py":
            continue
        src = path.read_text(encoding="utf-8")
        for cls in (n for n in ast.parse(src).body if isinstance(n, ast.ClassDef)):
            for fn in (n for n in cls.body if isinstance(n, ast.FunctionDef)):
                sql = " ".join(
                    n.value for n in ast.walk(fn)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)
                )
                if not _RLS_TABLES.search(sql):
                    continue
                unscoped_call = any(
                    isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                    and c.func.attr == "get_connection"
                    and not any(k.arg == "scope" for k in c.keywords)
                    for c in ast.walk(fn)
                )
                params = [a.arg for a in fn.args.args + fn.args.kwonlyargs]
                borrows = "conn" in params and "scope" not in params
                if unscoped_call or borrows:
                    found.append(f"{path.name}:{cls.name}.{fn.name}")
    return found


def test_no_more_repository_methods_rely_on_the_transition_policy_than_recorded():
    found = _unscoped_rls_methods()
    assert len(found) == UNSCOPED_RLS_METHODS, (
        f"{len(found)} repository methods touch an RLS table without a scope, ratchet says "
        f"{UNSCOPED_RLS_METHODS}. Above it: open the connection with the workspace, or "
        "with ALL_WORKSPACES when the path is installation-wide. Below it: lower "
        "UNSCOPED_RLS_METHODS in this PR.\n  " + "\n  ".join(found)
    )
