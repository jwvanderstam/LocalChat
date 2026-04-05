# Contributing to LocalChat

## Development setup

**Requirements:** Python 3.10+, Docker (for PostgreSQL, Redis, Ollama)

```bash
# 1. Clone and create virtual environment
git clone https://github.com/jwvanderstam/LocalChat.git
cd LocalChat
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt
pip install pre-commit ruff

# 3. Install pre-commit hooks
pre-commit install --install-hooks

# 4. Configure environment
cp .env.example .env               # edit .env with your settings

# 5. Start backing services
docker compose up -d db redis ollama

# 6. Run the app
python app.py
```

---

## Running tests

```bash
# Fast unit tests only — no external services required
pytest -m "not (slow or ollama or db)"

# All unit tests
pytest tests/unit/

# Integration tests — requires running PostgreSQL and Ollama
pytest tests/integration/

# Full suite with coverage
pytest

# Single test file
pytest tests/unit/test_file_validation.py -v
```

---

## Branching and PR conventions

- Branch off `main`: `git checkout -b feat/my-feature` or `fix/bug-description`
- One logical change per PR — avoid mixing features with refactors
- PR titles: imperative mood, under 70 characters (`Add file content validation`, not `Added...`)
- Reference the relevant roadmap phase in the PR description when applicable

---

## SonarCloud quality gate

PRs must pass the SonarCloud quality gate before merging:

- **0 new bugs** or **vulnerabilities**
- **0 new security hotspots** left unreviewed
- **Coverage** on new code ≥ 80%
- **Duplication** on new code < 3%

The gate runs automatically on every PR via `.github/workflows/sonarcloud.yml`.

---

## Commit message format

```
<type>: <short summary>

[optional body — wrap at 72 characters]
```

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `perf`

Examples:
```
feat: add magic-byte validation for uploaded files
fix: set SESSION_COOKIE_SECURE in non-demo mode
docs: add architecture diagram to README
test: add integration test for full RAG flow
```

---

## Keeping documentation in sync

**Rule:** if you add, remove, or rename a module, update the Key Files table in `CLAUDE.md` in the same PR.

This is a PR review checklist item — not optional.

When public-facing behaviour changes (new endpoint, changed default, removed flag), update `README.md` in the same PR.
