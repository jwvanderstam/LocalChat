"""`.env.example` is the file a new deployment is copied from, so every line in it is a
claim: *this variable does something*. On 2026-09-16 twenty-nine of them did nothing —
an SMTP block, gunicorn `WORKERS`, `DEBUG`, `MAX_UPLOAD_SIZE_MB`, `HOST`/`PORT` where the
code reads `SERVER_HOST`/`SERVER_PORT` — and four that *were* read carried values that
silently overrode the code's defaults (`CHUNK_SIZE=768` against 1200). A reader tuning
either file could not tell which one the application would obey.

`test_configuration_doc_covers_config.py` checks the reference documents everything the
code reads. This is the other direction: everything the example and the reference *name*
is read, by `config.py`, `app.py`, `docker-entrypoint.py` or a compose file.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLE = _ROOT / ".env.example"
_DOC = _ROOT / "docs" / "CONFIGURATION.md"
_READERS = [_ROOT / "src" / "config.py", _ROOT / "app.py", _ROOT / "docker-entrypoint.py"]

#: Example values that are deliberately not the code's default: secrets a deployment
#: must replace, and choices the example makes that the code leaves open.
_PLACEHOLDERS = {
    "APP_ENV",  # code: "" (local); the example starts a deployment as development
    "SECRET_KEY",
    "JWT_SECRET_KEY",
    "ADMIN_PASSWORD",
    "PG_PASSWORD",
    "OLLAMA_EMBEDDING_MODEL",  # code: "" (first embedder found); the example pins one
}


def _variables_read() -> set[str]:
    found: set[str] = set()
    for path in _READERS:
        src = path.read_text(encoding="utf-8")
        found |= set(re.findall(r"os\.(?:environ\.get|getenv)\(\s*['\"]([A-Z0-9_]+)['\"]", src))
        found |= set(re.findall(r"os\.environ\[\s*['\"]([A-Z0-9_]+)['\"]\s*\]", src))
    for path in _ROOT.glob("docker-compose*.yml"):
        found |= set(re.findall(r"\$\{([A-Z0-9_]+)", path.read_text(encoding="utf-8")))
    return found


def _example_assignments(*, include_commented: bool) -> dict[str, str]:
    """Every `VAR=value` line. A commented-out `# VAR=` is still a claim that VAR is read,
    but its value is a suggestion rather than an override."""
    text = _EXAMPLE.read_text(encoding="utf-8")
    prefix = r"#?\s*" if include_commented else ""
    return {
        m.group(1): m.group(2).strip()
        for m in re.finditer(rf"^\s*{prefix}([A-Z][A-Z0-9_]+)=(.*)$", text, re.M)
    }


def _config_literal_defaults() -> dict[str, str]:
    """`os.environ.get('VAR', 'literal')` pairs — the defaults a reader can compare against."""
    src = (_ROOT / "src" / "config.py").read_text(encoding="utf-8")
    return dict(re.findall(r"os\.environ\.get\(\s*['\"]([A-Z0-9_]+)['\"]\s*,\s*['\"]([^'\"]*)['\"]", src))


@pytest.mark.unit
class TestTheCheckSeesSomething:
    def test_readers_and_example_were_both_parsed(self):
        assert len(_variables_read()) > 100
        assert len(_example_assignments(include_commented=True)) > 40


@pytest.mark.unit
class TestEveryExampleVariableIsRead:
    def test_no_example_variable_is_dead(self):
        dead = sorted(
            v for v in _example_assignments(include_commented=True) if v not in _variables_read()
        )
        assert not dead, (
            f"{len(dead)} variable(s) in .env.example that nothing reads: " + ", ".join(dead)
        )

    def test_example_values_match_the_code_defaults(self):
        """A value that differs from the default is a decision; the placeholders list records it."""
        defaults = _config_literal_defaults()
        drift = sorted(
            f"{var}={value} (code default {defaults[var]!r})"
            for var, value in _example_assignments(include_commented=False).items()
            if var in defaults and var not in _PLACEHOLDERS and value.lower() != defaults[var].lower()
        )
        assert not drift, "example value silently overrides the code default: " + "; ".join(drift)


@pytest.mark.unit
class TestEveryReferenceVariableIsRead:
    def test_no_reference_row_names_a_dead_variable(self):
        """The tables under "Complete environment variable reference". The RAG-parameter
        table above it lists settings-page sliders, some of them deliberately UI-only."""
        doc = _DOC.read_text(encoding="utf-8")
        reference = doc[doc.index("## Complete environment variable reference") :]
        rows = set(re.findall(r"^\| `([A-Z][A-Z0-9_]+)` \|", reference, re.M))
        dead = sorted(rows - _variables_read())
        assert not dead, (
            f"{len(dead)} variable(s) documented in CONFIGURATION.md that nothing reads: "
            + ", ".join(dead)
        )
