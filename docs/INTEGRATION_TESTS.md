# Integration Tests

> Verified against `.github/workflows/tests.yml`, `pyproject.toml` and the test tree at
> `d0a43d4` on 2026-10-06.

Integration tests exercise the full HTTP layer (FastAPI routes + service layer)
with mocked external services (Ollama, real DB optional). A subset of tests
marked `@pytest.mark.db` require a live PostgreSQL instance.

## Running locally

### Fast (no external services — uses mocked DB)

Most integration tests mock the database via `MagicMock`. These run without
PostgreSQL:

```bash
pytest tests/integration/ -m "not (ollama or db)" -v
```

### With a real PostgreSQL + pgvector

Use a **throwaway** database, never the stack's own `db` service: the `db`-marked tests
create workspaces, ingest documents and run migrations against whatever `PG_*` points at,
and `.env` points at the database your LocalChat uses.

```bash
docker run -d \
  --name localchat-test-pg \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=ci_test_password \
  -e POSTGRES_DB=rag_db \
  -p 127.0.0.1:55432:5432 \
  pgvector/pgvector:pg16

# 55432, not 5432: the stack's own db already publishes 127.0.0.1:5432
PG_HOST=127.0.0.1 PG_PORT=55432 PG_PASSWORD=ci_test_password pytest tests/integration/ -m "not ollama" -v
docker rm -f localchat-test-pg
```

### With a real model

No test needs one. Everything that calls a model runs against `tests/utils/fake_ollama.py`,
whose bag-of-words embeddings make ranking assertions real without a GPU. Measuring what a
real model does is the evaluation scripts' job, not the suite's: `scripts/eval_retrieval.py`
(DEL-2, EV-1) and `scripts/eval_answers.py` (P2-3).

### End-to-end, through a browser

`tests/e2e/` drives the golden path — sign in, upload, ask, cited answer — in Chromium.
It starts its own LocalChat, so nothing needs to be running first except PostgreSQL:

```bash
playwright install chromium    # pytest-playwright itself is in requirements-dev.txt
pytest tests/e2e/ -v
```

The browser binary is the one piece no wheel carries, so it is a separate command
here and a separate step in CI. Without it the suite skips locally — but **never in
CI**, where a missing import raises instead: a silently skipped browser suite is
what let the previous one rot.

The model is stubbed (`tests/utils/fake_ollama.py`), so no Ollama and no GPU are needed.

**Point `PG_*` at a throwaway database.** The test signs in as `e2e-admin`, seeded on
first boot, and ingests a document into the default workspace. It retires that document
afterwards, but it is still writing to whatever database `.env` names:

```bash
docker run -d --name lc-e2e-pg -e POSTGRES_PASSWORD=e2e_test_password \
  -e POSTGRES_DB=rag_db -p 127.0.0.1:55432:5432 pgvector/pgvector:pg16
PG_HOST=127.0.0.1 PG_PORT=55432 PG_PASSWORD=e2e_test_password pytest tests/e2e/ -v
```

## Test markers

| Marker | Meaning |
|--------|---------|
| `integration` | Requires a running FastAPI test app |
| `db` | Requires a live PostgreSQL + pgvector instance |
| `ollama` | Requires a running Ollama server with a pulled model — none currently does |
| `e2e` | Drives a real browser; requires Playwright + Chromium and PostgreSQL |

Tests not marked `ollama` run in CI. Tests marked `db` run in CI via the
`pgvector/pgvector:pg16` service container.

## CI setup

`unit-tests` and `integration-tests` are two of the six **required checks** in the
"Code Verification" ruleset on `main` — see "Pull Requests and Merging" in
[CLAUDE.md](../CLAUDE.md) for the full set, and for reading it back through the API rather
than the settings UI. It is a ruleset, not a branch protection rule.

Every other job starts only after `unit-tests` passes, saving CI minutes when the unit
tests already fail.

The `e2e` job is **not** a required check, on purpose: a browser test is the one whose
flake would block every merge, and the path it covers is proven at the service layer by
`integration-tests` regardless.

## Writing new integration tests

1. Place the file in `tests/integration/`.
2. Mark the class or function with appropriate markers:
   ```python
   @pytest.mark.integration
   class TestMyRoute:
       ...
   ```
3. Use the shared `client` and `app` fixtures from `tests/conftest.py`.
4. Mock external services at the service boundary (not deep inside the RAG stack).
5. If the test needs a real DB, add `@pytest.mark.db` — it will run in CI
   via the Postgres service container.
6. If the test needs a model, use `tests/utils/fake_ollama.py`. Mark it
   `@pytest.mark.ollama` only if it truly needs a live server: the integration job
   excludes the marker, so it will never run in CI.
