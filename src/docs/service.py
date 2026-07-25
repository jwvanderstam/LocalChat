"""
Docs Service
============

Loads a fixed catalogue of the repo's own markdown files (``CLAUDE.md``,
``.claude/rules/*.md``, ``docs/*.md``, ``README.md``, ``SECURITY.md``) and
renders them to HTML, so in-app documentation (the ``/docs`` viewer and
per-setting help text on the settings page) is generated from the same
files a human reads instead of being hand-duplicated in templates — the
two can no longer silently drift apart.

Usage::

    docs_service = DocsService(root_dir=Path("."))
    docs_service.load_all()
    docs_service.get_doc("claude-md")
    docs_service.get_fragment("docs-settings", "chunk-size-chunk_size")

"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import markdown

from ..utils.logging_config import get_logger

logger = get_logger(__name__)

# Fixed catalogue of (slug, path-relative-to-repo-root). Never derived from
# request input — slugs are looked up in this fixed set only, so a route
# handler can never be tricked into reading an arbitrary file.
_CATALOGUE: list[tuple[str, str]] = [
    ("claude-md", "CLAUDE.md"),
    ("readme", "README.md"),
    ("security", "SECURITY.md"),
    ("rules-architecture", ".claude/rules/architecture.md"),
    ("rules-file-map", ".claude/rules/file-map.md"),
    ("rules-plugins", ".claude/rules/plugins.md"),
    ("rules-python", ".claude/rules/python.md"),
    ("rules-testing", ".claude/rules/testing.md"),
    ("docs-deployment", "docs/DEPLOYMENT.md"),
    ("docs-integration-tests", "docs/INTEGRATION_TESTS.md"),
    ("docs-migrations", "docs/MIGRATIONS.md"),
    ("docs-operations", "docs/OPERATIONS.md"),
    ("docs-roadmap", "docs/ROADMAP.md"),
    ("docs-schema", "docs/SCHEMA.md"),
    ("docs-test-quality-audit", "docs/TEST_QUALITY_AUDIT.md"),
    ("docs-troubleshooting", "docs/TROUBLESHOOTING.md"),
    ("docs-lessons-learned", "docs/LESSONS_LEARNED.md"),
    ("docs-settings", "docs/SETTINGS.md"),
]

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$", re.MULTILINE)
_MD_EXTENSIONS = ["fenced_code", "tables", "toc"]
_SLUG_STRIP_RE = re.compile(r"[^\w\s-]")
_SLUG_SPACE_RE = re.compile(r"\s+")


def _slugify(heading: str) -> str:
    """GitHub-anchor-style slug: lowercase, strip punctuation, spaces to hyphens."""
    slug = _SLUG_STRIP_RE.sub("", heading.lower()).strip()
    return _SLUG_SPACE_RE.sub("-", slug)


def _extract_title(raw: str, path: Path) -> str:
    """First H1 heading text, else the filename stem."""
    for match in _HEADING_RE.finditer(raw):
        if len(match.group(1)) == 1:
            return match.group(2)
    return path.stem


def _split_fragments(raw: str) -> dict[str, str]:
    """
    Split raw markdown into heading-keyed fragments, each rendered to HTML.

    A fragment runs from its own heading (inclusive) up to the next heading
    of equal-or-higher level (fewer or equal '#' characters), or the end of
    the document. Duplicate heading slugs within one doc get ``-1``, ``-2``,
    ... suffixes, matching GitHub's own anchor-collision scheme.
    """
    headings = [
        (match.start(), len(match.group(1)), match.group(2))
        for match in _HEADING_RE.finditer(raw)
    ]
    fragments: dict[str, str] = {}
    seen: dict[str, int] = {}
    for i, (start, level, text) in enumerate(headings):
        end = len(raw)
        for later_start, later_level, _ in headings[i + 1 :]:
            if later_level <= level:
                end = later_start
                break
        slug = _slugify(text)
        if slug in seen:
            seen[slug] += 1
            slug = f"{slug}-{seen[slug]}"
        else:
            seen[slug] = 0
        fragments[slug] = markdown.markdown(raw[start:end].rstrip(), extensions=_MD_EXTENSIONS)
    return fragments


@dataclass(frozen=True)
class DocEntry:
    slug: str
    path: Path
    title: str
    raw_markdown: str
    html: str
    fragments: dict[str, str] = field(default_factory=dict)
    mtime: float = 0.0


class DocsService:
    """
    Loads and caches the repo's fixed markdown catalogue as rendered HTML.

    Args:
        root_dir: Repository root that catalogue paths are relative to.
        catalogue: Override the fixed (slug, relative_path) list — used by
            tests to point at a small temp fixture instead of the real repo.
    """

    def __init__(self, root_dir: Path, catalogue: list[tuple[str, str]] | None = None) -> None:
        self._root_dir = Path(root_dir)
        self._catalogue = catalogue if catalogue is not None else _CATALOGUE
        self._docs: dict[str, DocEntry] = {}

    def load_all(self) -> int:
        """Scan the catalogue, parse and cache each doc. Returns count loaded."""
        loaded = 0
        for slug, rel_path in self._catalogue:
            path = self._root_dir / rel_path
            try:
                raw = path.read_text(encoding="utf-8")
            except OSError as exc:
                logger.warning(f"[DOCS] Skipping '{slug}' ({path}): {exc}")
                continue
            self._docs[slug] = DocEntry(
                slug=slug,
                path=path,
                title=_extract_title(raw, path),
                raw_markdown=raw,
                html=markdown.markdown(raw, extensions=_MD_EXTENSIONS),
                fragments=_split_fragments(raw),
                mtime=path.stat().st_mtime,
            )
            loaded += 1
        logger.info(f"[DOCS] Loaded {loaded} doc(s) from {self._root_dir}")
        return loaded

    def reload_all(self) -> int:
        """Re-read every catalogued file from disk, picking up edits."""
        self._docs = {}
        return self.load_all()

    def list_docs(self) -> list[dict[str, Any]]:
        """Return ``{slug, title, path}`` for every loaded doc."""
        return [
            {"slug": entry.slug, "title": entry.title, "path": str(entry.path)}
            for entry in self._docs.values()
        ]

    def get_doc(self, slug: str) -> DocEntry | None:
        return self._docs.get(slug)

    def get_fragment(self, slug: str, fragment_slug: str) -> str | None:
        entry = self._docs.get(slug)
        if entry is None:
            return None
        return entry.fragments.get(fragment_slug)
