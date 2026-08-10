"""The in-app docs viewer must not silently drop a document.

`_CATALOGUE` is a hand-maintained list, and the existing tests all inject their own,
so nothing checked it against the repository. Eight documents had drifted out of it —
including the route permission matrix and the workspace API key guide, both of which
are the reference a user would go looking for. They existed, and the viewer that
claims to serve the project's documentation did not show them.

A fixed catalogue is the right design: slugs are looked up in a known set, so a
crafted request cannot reach an arbitrary file. This test keeps that property while
making the omission of a document a decision someone has to write down.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.docs.service import _CATALOGUE

ROOT = Path(__file__).resolve().parents[2]

#: Documents deliberately not served in-app, each with a reason.
NOT_SERVED: dict[str, str] = {}


def _tracked_docs() -> set[str]:
    out = subprocess.run(
        ["git", "ls-files", "docs/*.md"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return {line.strip() for line in out.stdout.splitlines() if line.strip()}


@pytest.mark.unit
class TestCatalogueMatchesTheRepository:
    def test_every_document_is_served_or_explicitly_excluded(self):
        catalogued = {path for _, path in _CATALOGUE}
        missing = sorted(_tracked_docs() - catalogued - set(NOT_SERVED))
        assert not missing, (
            "Documents exist but the in-app viewer cannot show them. Add them to "
            "_CATALOGUE, or to NOT_SERVED with a reason:\n  " + "\n  ".join(missing)
        )

    def test_no_catalogue_entry_points_at_a_missing_file(self):
        """A stale entry is only logged at startup, so it fails quietly in production."""
        absent = sorted(path for _, path in _CATALOGUE if not (ROOT / path).exists())
        assert not absent, f"catalogued but not present: {absent}"

    def test_slugs_are_unique(self):
        """Duplicate slugs silently shadow one another in the lookup dict."""
        slugs = [slug for slug, _ in _CATALOGUE]
        assert len(slugs) == len(set(slugs))

    def test_exclusions_name_real_files(self):
        """An exclusion for a deleted file would quietly excuse a future document."""
        stale = sorted(p for p in NOT_SERVED if not (ROOT / p).exists())
        assert not stale, f"NOT_SERVED names files that no longer exist: {stale}"
