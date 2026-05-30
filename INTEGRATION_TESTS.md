# Integration Tests

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

Spin up the DB container, then run the full integration suite:

```bash
docker compose up -d postgres
pytest tests/integration/ -m "not ollama" -v
```

Or with bare Docker:

```bash
docker run -d \
  --name localchat-test-pg \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=ci_test_password \
  -e POSTGRES_DB=rag_db \
  -p 5432:5432 \
  pgvector/pgvector:pg16

pytest tests/integration/ -m "not ollama" -v
docker rm -f localchat-test-pg
```

### With Ollama (full end-to-end)

Start Ollama and pull a model, then run the complete suite:

```bash
ollama pull llama3.2
pytest tests/integration/ -v
```

## Test markers

| Marker | Meaning |
|--------|---------|
| `integration` | Requires a running FastAPI test app |
| `db` | Requires a live PostgreSQL + pgvector instance |
| `ollama` | Requires a running Ollama server with a pulled model |

Tests not marked `ollama` run in CI. Tests marked `db` run in CI via the
`pgvector/pgvector:pg16` service container.

## CI setup

Both `unit-tests` and `integration-tests` are **required checks** for merging
to `main`. To enforce this, go to:

> GitHub → Repository → Settings → Branches → Branch protection rules → main
> → Require status checks → Add `unit-tests` and `integration-tests`

The `integration-tests` job only starts after `unit-tests` passes, saving
CI minutes when unit tests already fail.

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
6. If the test needs Ollama, add `@pytest.mark.ollama` — it will be excluded
   from CI and documented as manual-only.
