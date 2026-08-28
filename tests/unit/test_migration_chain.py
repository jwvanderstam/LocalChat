"""TQ-5a — the Alembic revision chain must be unambiguous.

These checks need no database and run in the fast suite, so a broken chain is caught
before `integration-tests` gets as far as executing one (TQ-5b,
`tests/integration/test_migrations_apply.py`).

The failure they exist for: on 2026-08-05 a backfill migration was numbered `0012`,
colliding with `0012_hybrid_search_tsvector.py`. Alembic does not raise on a duplicate
revision id — it emits `UserWarning: Revision 0012 is present more than once` through
Python's ``warnings`` module, and `upgrade head` then aborts with `MultipleHeads`, so
**no migration applies at all**, including previously pending ones. It passed review,
CI and merge (#219) and surfaced only when the stack was started (#222).

Loading the ScriptDirectory does not connect to a database — ``env.py`` only runs when
a command is executed against it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

REPO = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO / "alembic.ini"
VERSIONS = REPO / "migrations" / "versions"


def _script_directory() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))


def _migration_files() -> list[Path]:
    return sorted(p for p in VERSIONS.glob("*.py") if not p.name.startswith("__"))


@pytest.mark.unit
def test_exactly_one_head():
    """Two heads means `upgrade head` aborts and nothing is applied."""
    heads = _script_directory().get_heads()
    assert len(heads) == 1, f"expected a single head, got {heads}"


@pytest.mark.unit
def test_every_migration_file_is_reachable():
    """A duplicate revision id silently drops one file from the chain.

    Alembic keys its version map by revision id, so two files declaring the same id
    leave only one reachable — the other never runs, on any database.
    """
    revisions = list(_script_directory().walk_revisions())
    assert len(revisions) == len(_migration_files())


@pytest.mark.unit
def test_no_duplicate_revision_ids():
    """Asserted against the files directly, so the message names the collision."""
    ids: dict[str, list[str]] = {}
    for path in _migration_files():
        m = re.search(r'^revision\s*=\s*["\'](.+?)["\']', path.read_text(encoding="utf-8"), re.M)
        assert m, f"{path.name} declares no revision id"
        ids.setdefault(m.group(1), []).append(path.name)
    duplicates = {rev: files for rev, files in ids.items() if len(files) > 1}
    assert not duplicates, f"duplicate revision ids: {duplicates}"


@pytest.mark.unit
def test_chain_is_linear_from_head_to_base():
    """Walking head→base must reach every revision — no orphaned branch."""
    script = _script_directory()
    walked = {r.revision for r in script.walk_revisions()}
    assert len(walked) == len(_migration_files())


@pytest.mark.unit
def test_down_revision_targets_exist():
    """A down_revision pointing at a missing id breaks the chain at that link."""
    script = _script_directory()
    known = {r.revision for r in script.walk_revisions()}
    for rev in script.walk_revisions():
        down = rev.down_revision
        if down is None:
            continue
        targets = down if isinstance(down, tuple) else (down,)
        for t in targets:
            assert t in known, f"{rev.revision} points at unknown down_revision {t}"
