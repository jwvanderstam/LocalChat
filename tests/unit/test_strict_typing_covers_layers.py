"""Every service and every repository is held to strict typing (maturity criterion 5).

`pyproject.toml` lists the strict modules by name, because `strict = true` is global-only in
mypy. A list by name drifts silently: `chat.py`, `admin_stats.py` and `logs.py` sat in
`src/services/` outside it until 2026-10-31, and CI's `mypy src` stayed green throughout.
This fails when a module in either layer is missing from the list.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# The pool and the package's re-exports, not repositories.
NOT_REPOSITORIES = {"__init__", "connection"}


def _strict_modules() -> set[str]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as f:
        overrides = tomllib.load(f)["tool"]["mypy"]["overrides"]
    return {
        module
        for override in overrides
        if override.get("disallow_any_generics") and override.get("warn_return_any")
        for module in override["module"]
    }


def _layer_modules(package: str, excluded: set[str]) -> set[str]:
    return {
        f"src.{package}.{path.stem}"
        for path in (REPO_ROOT / "src" / package).glob("*.py")
        if path.stem not in excluded
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    ("package", "excluded"),
    [("services", {"__init__"}), ("db", NOT_REPOSITORIES)],
)
def test_every_module_in_the_layer_is_held_to_strict_typing(package: str, excluded: set[str]) -> None:
    missing = _layer_modules(package, excluded) - _strict_modules()
    assert missing == set(), f"add to [[tool.mypy.overrides]] in pyproject.toml: {sorted(missing)}"
