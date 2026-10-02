"""Current-state documents name only files and endpoints that exist (ROADMAP P2-7).

`test_configuration_doc_covers_config` and `test_permissions_doc_matches_routes` each hold
one document to the code. Every other document could name a module that was renamed or an
endpoint that was removed, and nothing looked: a reader following the docs found a 404 or
an empty path, and the document read as authoritative regardless.

The journal — the records of what was planned and what happened — is excluded on purpose.
A stale path in LESSONS_LEARNED is a fact about the past; correcting it would falsify the
record. ROADMAP P2-7's other half moves those files under `docs/history/`; until it does,
they are listed by name in `_JOURNAL`.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: Records of the past, not descriptions of the present (ROADMAP P2-7 names them).
_JOURNAL = {
    "CHANGELOG.md",
    "docs/AUTH_PLAN.md",
    "docs/DEPLOYMENT_LOG.md",
    "docs/LESSONS_LEARNED.md",
    "docs/PRODUCTION_PLAN.md",
    "docs/REMEDIATION_PLAN.md",
    "docs/ROADMAP.md",
    "docs/TEST_QUALITY_AUDIT.md",
}

#: (document, path) pairs that name a file which does not exist, deliberately.
_ABSENT_PATHS_ON_PURPOSE: dict[tuple[str, str], str] = {
    ("CLAUDE.md", "src/app.py"): "warns that the module does not exist",
    (".claude/rules/testing.md", "src/app.py"): "warns that the module does not exist",
    (".claude/rules/python.md", "src/types.py"): "records that the exemption pointed nowhere",
    ("docs/ADR.md", "src/connectors/s3_connector.py"): "ADR-4's evidence; the connector was removed",
}

#: (document, endpoint) pairs that name an endpoint this application does not serve.
_FOREIGN_ENDPOINTS: dict[tuple[str, str], str] = {
    ("docs/DEPLOYMENT_SCALEWAY.md", "/api/embed"): "Ollama's native API, not ours",
    ("docs/DEPLOYMENT_SCALEWAY.md", "/api/tags"): "Ollama's native API, not ours",
}

_PATH = re.compile(r"`((?:src|tests|scripts|mcp_servers|migrations|static|templates)/[^`\s]*)`")
# Preceded by a host (`http://ollama:11434/api/tags`) it belongs to another server.
_ENDPOINT = re.compile(r"(?<![\w.:/-])(/api/[A-Za-z0-9_./{}-]*\*?)")


def _current_state_docs() -> list[str]:
    found = [
        *ROOT.glob("*.md"),
        *(ROOT / "docs").glob("*.md"),
        *(ROOT / ".claude" / "rules").glob("*.md"),
        ROOT / "plugins" / "README.md",
        ROOT / "design" / "README.md",
    ]
    names = {p.relative_to(ROOT).as_posix() for p in found if p.is_file()}
    return sorted(names - _JOURNAL)


def _read(doc: str) -> str:
    return (ROOT / doc).read_text(encoding="utf-8")


def _paths_named(doc: str) -> set[str]:
    named = set()
    for match in _PATH.finditer(_read(doc)):
        path = re.split(r"::|:|#|\(", match.group(1))[0].rstrip(".,;")
        if not re.search(r"[*{}<>]|\.\.\.", path):
            named.add(path)
    return named


def _served_paths() -> set[str]:
    from src.app_fastapi import create_app

    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        app = create_app()
        paths = set(app.openapi()["paths"])
    finally:
        logging.disable(previous)
    # Swagger and the schema are mounted by FastAPI itself, so openapi() does not list them.
    paths |= {app.docs_url or "", app.openapi_url or ""}
    return {_normalise(p) for p in paths if p}


def _normalise(endpoint: str) -> str:
    """`{workspace_id}` and `{id}` are the same shape; a trailing slash is not a difference."""
    return re.sub(r"\{[^}]*\}", "{}", endpoint).rstrip("/.") or "/"


def _endpoints_in(text: str) -> set[str]:
    # `/api/...` is prose for "an endpoint", not an endpoint.
    return {
        m.group(1).rstrip(".,;:") for m in _ENDPOINT.finditer(text) if "..." not in m.group(1)
    }


def _endpoints_named(doc: str) -> set[str]:
    return _endpoints_in(_read(doc))


def _is_served(endpoint: str, served: set[str]) -> bool:
    if endpoint.endswith("*"):
        prefix = _normalise(endpoint[:-1])
        return any(p.startswith(prefix + "/") for p in served)
    return _normalise(endpoint) in served


@pytest.fixture(scope="module")
def served() -> set[str]:
    return _served_paths()


@pytest.mark.unit
class TestPathsNamedInDocsExist:
    def test_every_backticked_repository_path_exists(self):
        missing = sorted(
            f"{doc}: {path}"
            for doc in _current_state_docs()
            for path in _paths_named(doc)
            if (doc, path) not in _ABSENT_PATHS_ON_PURPOSE and not (ROOT / path).exists()
        )
        assert missing == [], "documents name files that do not exist:\n" + "\n".join(missing)

    def test_every_deliberate_absence_is_still_named_and_still_absent(self):
        stale = sorted(
            f"{doc}: {path}"
            for doc, path in _ABSENT_PATHS_ON_PURPOSE
            if path not in _paths_named(doc) or (ROOT / path).exists()
        )
        assert stale == []

    def test_the_scan_reads_a_reference_it_must_find(self):
        assert "src/app_fastapi.py" in _paths_named("CLAUDE.md")


@pytest.mark.unit
class TestEndpointsNamedInDocsAreServed:
    def test_every_documented_api_endpoint_is_served(self, served):
        missing = sorted(
            f"{doc}: {endpoint}"
            for doc in _current_state_docs()
            for endpoint in _endpoints_named(doc)
            if (doc, endpoint) not in _FOREIGN_ENDPOINTS and not _is_served(endpoint, served)
        )
        assert missing == [], "documents name endpoints the app does not serve:\n" + "\n".join(missing)

    def test_every_foreign_endpoint_is_still_named_and_still_not_ours(self, served):
        stale = sorted(
            f"{doc}: {endpoint}"
            for doc, endpoint in _FOREIGN_ENDPOINTS
            if endpoint not in _endpoints_named(doc) or _is_served(endpoint, served)
        )
        assert stale == []

    def test_an_endpoint_on_another_host_is_not_read_as_ours(self):
        assert _endpoints_in("curl http://localhost:11434/api/tags") == set()
        assert _endpoints_in("call `/api/health` first.") == {"/api/health"}

    def test_an_ellipsis_is_a_placeholder_not_an_endpoint(self):
        assert _endpoints_in("every documented `/api/...` endpoint") == set()

    def test_a_trailing_star_is_a_prefix(self, served):
        assert _is_served("/api/oauth/microsoft/*", served) is True
        assert _is_served("/api/no-such-family/*", served) is False

    def test_the_scan_reads_an_endpoint_it_must_find(self):
        assert "/api/health" in set().union(*(_endpoints_named(d) for d in _current_state_docs()))
