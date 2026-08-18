# LocalChat on Scaleway — Deployment Plan (Test Stack)

Prepared 2026-08-18. Repo analyzed: `github.com/jwvanderstam/LocalChat` (cloned at commit matching `ghcr.io/jwvanderstam/localchat:latest`, built automatically by `.github/workflows/docker-publish.yml`).

## 1. The core problem, stated plainly

You asked to deploy LocalChat "on Scaleway containers." LocalChat is a 4-service `docker-compose` stack (`app`, `db` (Postgres+pgvector), `redis`, `ollama`), and its own `docs/DEPLOYMENT.md` states it is **single-instance by design** — `AppState`, the Alembic migration runner, connector polling, and the reranker's scheduler are in-process state with no cross-instance coordination. Its own ADR-1 says running two instances "silently disagree about the active model, rate limits and cached state." The Helm chart was deliberately removed for this reason.

Scaleway Serverless Containers is built for the opposite case: one container image per service, autoscaled 0–50 instances, ephemeral storage (24 GB temp disk, wiped on every restart or scale-to-zero), scale-to-zero after 15 minutes idle, no GPU, and a hard ceiling of 6 vCPU / 12 GB RAM per container. [High confidence — Scaleway's own "Containers limitations" doc, checked live today.]

You cannot deploy a `docker-compose.yml` as a unit onto Scaleway Serverless Containers. There is no multi-container/sidecar concept — it's one image per Container resource. The stack has to be decomposed service-by-service into whichever Scaleway product actually fits each one. That's what this plan does, and it flags where the fit is imperfect rather than pretending it's clean.

## 2. Service-by-service mapping

| docker-compose service | Scaleway target | Fit | Notes |
|---|---|---|---|
| `app` (FastAPI/Uvicorn) | **Serverless Container** | Good | Stateless HTTP service, already single-worker by design (`UVICORN_WORKERS=1`). Cap **max scale = 1** instance to respect the single-instance ADR — you lose horizontal scaling but that's already true of the app itself. |
| `db` (Postgres 16 + pgvector) | **Serverless SQL Database** | Good, with one caveat (§3) | Confirmed pgvector is supported here [checked live: `scaleway.com/en/docs/serverless-sql-databases/reference-content/supported-postgresql-extensions/`]. Note: Scaleway's *older* "Managed Database for PostgreSQL" product does **not** list pgvector — there's a 2+ year open feature request for it. Use Serverless SQL Database, not the classic managed DB. |
| `redis` | **Skip** | Fine | `REDIS_ENABLED` defaults to `false` in the app; it falls back to in-memory caching/rate-limiting. Since you're already capped at 1 instance, there's no cross-instance cache-consistency need Redis would solve. Add it later only if you outgrow in-memory. |
| `ollama` | **No serverless equivalent — needs a GPU Instance** | Poor fit, real cost | This is the actual blocker, detailed in §4. |

## 3. Known risk: pgvector session settings under Scaleway's pooler

`src/db/connection.py` runs `SET hnsw.ef_search = 100` once per physical connection (in psycopg's own connection-pool `configure` callback, line ~228) and relies on it persisting for every query on that connection. Scaleway's own pgvector docs carry this caveat: *"Query options using SET command require to be used in a single transaction (i.e. between BEGIN; ... COMMIT;)"* — implying their serverless proxy may not guarantee session-level `SET` persists across transactions the way a normal Postgres connection would.

Practical effect if this bites: **not a crash** — the app will run and return results, but HNSW search may silently run at whatever the default `ef_search` is instead of 100, degrading RAG retrieval recall without any visible error. [Moderate confidence — inferred from Scaleway's documented caveat plus reading the app's connection code; I have not tested this against a live Serverless SQL Database.] Worth validating with a direct query (`SHOW hnsw.ef_search;`) after a few requests once deployed, before trusting search quality.

## 4. The Ollama decision (needs your input, not mine)

LocalChat's `ollama_client.py` speaks Ollama's native API (`/api/chat`, `/api/embed`), not the OpenAI-compatible format. That rules out Scaleway's serverless "Generative APIs" product as a drop-in — using it would mean rewriting `src/ollama_client.py` and `src/llm_client.py`, not just changing config.

Real options, in order of how much they preserve the existing app unmodified:

1. **Scaleway GPU Instance** running Ollama natively (e.g., an L4 or L40S instance), reached over a Private Network attached to the Serverless Container. Zero code changes. This is a persistent VM billed hourly the whole time it's up — realistically the most expensive line item in this whole deployment, likely on the order of €1–3+/hour depending on GPU class (verify current pricing before committing — I have not fetched live GPU Instance rates for this doc).
2. **CPU-only GPU Instance / small Instance** running Ollama with a small quantized model. Works, zero code changes, much cheaper, but chat latency will be materially worse (seconds-to-tens-of-seconds per response depending on model size).
3. **Rewrite the LLM client** to target Scaleway's OpenAI-compatible Generative APIs (pay-per-token, no VM to manage, cheapest and simplest operationally) — but this is a real code change to two source files, moves you off "self-hosted local model" as a premise, and is out of scope for "deploy as-is."
4. **Skip it for the test deploy.** App boots, auth/UI/document upload work, chat endpoints fail cleanly (Ollama unreachable). Validates everything except inference for €0 extra.

Check the available credit on the account and its expiry date before committing to this. A GPU Instance left running continuously burns through a test budget faster than you would expect, so decide up front whether to keep it up or spin it up only for test sessions.

Separately: confirm the account can create resources at all before planning further. Scaleway may still require a payment method on file even when credit is available, and entering card details is a step only the account holder can do.

## 5. Image size / cold start

`requirements.txt` pulls in `sentence-transformers` (→ torch), `spacy`, `kuzu`, and test-only deps (`pytest`, `pytest-playwright`) all in one flat file with no dev/prod split. The built image is very likely several GB uncompressed — well past Scaleway's recommended 1 GB for Serverless Containers. [High confidence on the dependency list, moderate confidence on final image size — I did not build and measure the image directly.] Effect: slow cold starts every time the container wakes from its 15-minute idle scale-to-zero, which matters for a chat app where a user's first message after a break would hang.

This isn't a blocker for a test deploy — just note it, measure actual cold-start time once live, and decide later whether a trimmed `requirements-serverless.txt` (dropping test-only and optional deps like `kuzu`/`spacy` if you're not using GraphRAG) is worth doing.

## 6. How to do this without breaking your repo

Everything below is **additive only** — no existing file needs to change:

- **Don't touch** `Dockerfile`, `docker-compose.yml`, `docker-compose.nginx.yml`, or `.env.example`. Local dev (`docker compose up`) keeps working exactly as documented in `docs/DEPLOYMENT.md`.
- **Reuse the existing published image** — `ghcr.io/jwvanderstam/localchat:latest` is already public and auto-built by the existing GitHub Action on every push to `main`. Scaleway Serverless Containers can pull directly from GHCR; no new build pipeline needed, no new Scaleway Container Registry required.
- **New file only**: `docs/DEPLOYMENT_SCALEWAY.md` documenting this target (mirrors the structure of the existing `docs/DEPLOYMENT.md` but for this environment) — purely additive documentation, doesn't alter behavior.
- **Config lives entirely in Scaleway environment variables/secrets**, set through the Scaleway console or CLI — never in a committed file. The app already reads all config from env vars (12-factor), so this requires zero code changes.
- If you later want a leaner image, that would be a **new** `requirements-serverless.txt` + a **new** `Dockerfile.serverless`, both additive, with the existing `Dockerfile` left as the default for local dev and untouched by CI.
- If Ollama's SET-session issue in §3 turns out to matter, the fix is confined to `src/db/connection.py` (wrap the `SET hnsw.ef_search` in the pool's per-checkout hook instead of per-connection, or move it to be set on every query) — a small, isolated, reversible change, not a rewrite.

Net: this plan requires **zero modifications to your existing app code or local dev workflow** for the MVP path. Everything Scaleway-specific is new files plus console/CLI configuration.

## 7. Concrete environment variables / secrets for the Container

Required (app raises at startup in `APP_ENV=production` if unset — see `src/config.py`):

| Variable | Value source |
|---|---|
| `APP_ENV` | `production` |
| `SECRET_KEY` | generate: `python -c "import secrets; print(secrets.token_hex(32))"` — store as Scaleway **secret** env var |
| `JWT_SECRET_KEY` | same generation method, different value, **secret** |
| `ADMIN_PASSWORD` | your choice, **secret** — empty disables all auth, per `docs/DEPLOYMENT.md` security checklist |
| `PG_HOST`, `PG_PORT`, `PG_USER`, `PG_PASSWORD`, `PG_DB` | from the Serverless SQL Database connection details, `PG_PASSWORD` as **secret** |
| `TOKEN_ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`, **secret** — required for OAuth connectors even if unused |
| `METRICS_TOKEN` | generate a token if you enable `/api/metrics`, else leave `METRICS_ENABLED=false` |
| `REDIS_ENABLED` | `false` |
| `OLLAMA_BASE_URL` | either the GPU Instance's private address, or leave default/unreachable for the no-chat MVP |
| `UVICORN_WORKERS` | `1` (already the default) |
| `SERVER_PORT` | `5000` — matches `Dockerfile` `EXPOSE`, set Scaleway's container port to match |
| `MCP_ENABLED` | `false` (the three MCP domain servers aren't part of this plan) |

## 8. Phased rollout

**Phase 0 — Billing.** Confirm the account can actually create resources; available credit alone may not be sufficient if a payment method is still required. You'll need to do this step yourself.

**Phase 1 — Database.** Create a Scaleway Serverless SQL Database (Postgres 16-compatible), confirm `CREATE EXTENSION vector` succeeds, note connection details.

**Phase 2 — Container.** Create a Serverless Container in your Serverless Containers namespace (AMS region), image `ghcr.io/jwvanderstam/localchat:latest`, port 5000, max scale 1, env vars from §7, memory ≥2 GB (torch at import time is not free — start at 2–3 GB, watch for OOM restarts).

**Phase 3 — Validate.** Hit `/api/health`, confirm migrations ran (check container logs for "Alembic migrations applied"), log in with `ADMIN_PASSWORD`, confirm document upload works (remember: ephemeral disk, uploaded docs vanish on scale-to-zero — fine for a smoke test, not for real use).

**Phase 4 — Decide on Ollama.** Once Phase 3 is confirmed live, revisit §4 with real numbers in front of you (GPU Instance hourly rate, actual credit burn) rather than deciding blind now.

## 9. Open items only you can resolve

- Whether a payment method is required before resources can be created (§4) — needs your action in the console.
- Which Ollama path (§4) — cost/latency tradeoff, your call once Phase 3 is live.
- Whether the expiry date on your available credit changes the urgency of the GPU decision.
