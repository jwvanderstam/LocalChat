# LocalChat on Scaleway — Deployment Plan (Test Stack)

Prepared 2026-08-18. Repo analyzed: `github.com/jwvanderstam/LocalChat` (cloned at commit matching `ghcr.io/jwvanderstam/localchat:latest`, built automatically by `.github/workflows/docker-publish.yml`).

## 0. Re-derived 2026-08-26 — read this before §1

This plan was written on 2026-08-18 against the repository as it then stood. It was
checked against the code again on 2026-08-26, by measuring rather than reading. Most of
it holds. Six things did not, and the sizing section was wrong about which dependency
mattered.

**§5's image-size guess was "very likely several GB".** Two numbers, because they are
not the same number and the difference matters:

| Measure | Value | What it is |
|---|---|---|
| `docker images` SIZE | 9.92 GB | Docker's layer accounting |
| Files inside the container | **6.60 GB** | What actually has to arrive and unpack |

The 6.60 GB is the honest figure for cold-start reasoning. It breaks down as `/opt`
(the venv) 6022 MB, `/app` 361 MB, `/usr` 120 MB, `/lib` 98 MB. Scaleway pulls the
*compressed* layers, which are smaller again — not measured here, because it needs a
push to a registry.

### Where the weight is

Nothing under `src/` imports `torch`. It is there for one reason: the cross-encoder
reranker, via `sentence-transformers`. Everything below follows from that one dependency.

| Package | Size | Reachable in this deployment? |
|---|---|---|
| `nvidia-*` (CUDA runtime) | 2855 MB | **No** — a Serverless Container has no GPU, and even in compose the `app` service has no device reservation; the GPU goes to `ollama` |
| `torch` | 1142 MB | Yes, on CPU |
| `triton` (GPU kernel compiler) | 723 MB | **No** — same reason |
| `.mypy_cache` in `/app` | 351 MB | **No** — see below |
| `playwright` | 142 MB | **No longer present** — removed by the dev/runtime split, OPS-1 |

§5's suggested trim was aimed at the wrong 10%: dropping `kuzu` and `spacy` saves
~130 MB against 4.7 GB sitting in plain sight.

### `.mypy_cache` ships in the image

`.dockerignore` excludes `.pytest_cache` but not `.mypy_cache`, `.ruff_cache` or
`design/`. The type-checker cache is 351 MB of the 361 MB `/app` directory.

The size is the smaller half of the problem. **The image differs depending on whether
the person building it happened to run mypy first.** CI builds from a clean checkout, so
this has never reached a published image — only a locally built one. It is three lines
in `.dockerignore` and there is no tradeoff.

### Three routes, measured

Each was measured, not estimated. The CPU-only figure comes from installing
`torch==2.9.1+cpu` and `sentence-transformers` into a clean `python:3.12-slim` and
walking `site-packages`.

| Route | Saves | Cost | Lands at |
|---|---|---|---|
| `.dockerignore` fix | 0.36 GB | none | 6.24 GB |
| CPU-only `torch` from `download.pytorch.org` | 4.0 GB | a second package index in the supply chain | 2.24 GB |
| **Drop `sentence-transformers` for this target** | **5.2 GB** | no reranker here | **~1.0 GB** |

The third route lands on Scaleway's own ~1 GB recommendation with **no supply-chain
change at all**, and it is the better fit for a reason beyond size: **the reranker model
is not baked into the image.** Verified — only `huggingface_hub`'s dist-info is present.
`CrossEncoder(...)` downloads the model at first use, onto ephemeral storage, and
re-downloads it after every scale-to-zero. On a serverless target the reranker is a
recurring cold-start cost, not just dead weight.

### The recommendation

**Do not change the image before the first deployment.** Deploy as it is, with
**min scale 1** so the container never sleeps. That answers "does this run on Scaleway"
with one variable changed, and it produces the numbers the rest of the decision needs:
boot time, resident memory, whether the `hnsw.ef_search` warning fires, whether
Serverless SQL's pgvector behaves. Change the supply chain first and a failed deployment
becomes ambiguous.

Scaleway publishes **no hard image-size limit** — only the ~1 GB recommendation and
cold-start guidance ([Containers limitations](https://www.scaleway.com/en/docs/serverless-containers/reference-content/containers-limitations/)).
6.6 GB will deploy. It just will not wake up quickly.

Then, when you act on it: **the two targets want different images.** The appliance keeps
CUDA `torch` and the reranker — cold start is irrelevant there and the reranker is
wanted. The serverless variant drops `sentence-transformers` and sets
`RERANKER_ENABLED=false`. Neither compromises for the other, which is exactly the
additive `Dockerfile.serverless` §6 already anticipates. Build it when the numbers from
the first deployment say it is worth building, not before.

**§3's `SET hnsw.ef_search` risk is now instrumented, and the mechanism was subtler than
described.** The app reads the setting back in a separate transaction at connection time
and logs one warning if it did not survive. Verified against pgbouncer in transaction
mode: every query saw `ef_search=40` instead of 100 while the app reported itself
healthy, and without the guard nothing was logged at all.

But the caveat §3 inferred is not quite the failure. pgbouncer in transaction mode does
not reset session state by default — it *leaks* it between clients. The setting then
survives on whichever server connection carries it and is absent on the others, so a
connection-time read-back can pass by luck while later queries still degrade. **Treat the
warning as a positive signal, not a clean bill of health**: behind any pooler, confirm
with `SHOW hnsw.ef_search;` on a live connection under load, exactly as §3 advised.
See [DEPLOYMENT.md](DEPLOYMENT.md#connection-poolers-and-vector-search).

**§7 names two environment variables incorrectly.**

| §7 says | Reality |
|---|---|
| `TOKEN_ENCRYPTION_KEY` | The canonical name is **`ENCRYPTION_KEY`**. `TOKEN_ENCRYPTION_KEY` is still read as a legacy alias (`src/config.py`), so §7 works — but use the current name. It is required in production for *messages and memories*, not only OAuth connectors, and boot aborts without it. |
| `METRICS_ENABLED=false` | **No such setting exists.** The only control is `METRICS_TOKEN`: unset means `/api/metrics` answers unauthenticated. Set it. |

**The image is distroless, which §6 does not mention and which changes how you debug.**
Both build stages are Docker Hardened Images; the runtime has no shell and no package
manager and runs as uid 65532. Scaleway's console "exec into container" will not work,
`docker exec ... sh` will not work, and nothing can be installed into a running instance.
Logs are the only instrument — `LOG_FORMAT=json` is already the default. A missing system
library surfaces as **SIGSEGV on import (exit 139, no traceback)**, never as a readable
error. See [ADR-3](ADR.md).

**§8 Phase 2 says image `:latest`.** For a test deployment whose results you want to
trust, pin the tag — `ghcr.io/jwvanderstam/localchat:3.0.0-beta.1` — so the thing you
debug on Friday is the thing you deployed on Monday. `:latest` moves on every push to
`main`.

**Still true, checked:** the four-service decomposition (§2); Serverless SQL Database
rather than the classic managed product, for pgvector; skipping Redis, since
`REDIS_ENABLED` defaults false and max-scale 1 removes the coherence argument; the
Ollama analysis in §4, which remains the open cost decision; and §6's core claim that
everything Scaleway-specific is additive — no file in this repository needs to change to
deploy it there.

**One thing to add to §8 Phase 3.** Migrations run at boot, in-process, with no
cross-instance lock. That is safe at max-scale 1 and only at max-scale 1. If the
container is ever allowed to scale past one instance, two of them will race the Alembic
chain. Set max scale to 1 and treat it as a correctness setting, not a cost one.

---

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
| `ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`, **secret** — required in production for messages and memories, not only OAuth connectors; boot aborts without it. (`TOKEN_ENCRYPTION_KEY` still works as a legacy alias.) |
| `METRICS_TOKEN` | Generate one. There is no `METRICS_ENABLED` switch — leaving this unset is what makes `/api/metrics` public. |
| `REDIS_ENABLED` | `false` |
| `OLLAMA_BASE_URL` | either the GPU Instance's private address, or leave default/unreachable for the no-chat MVP |
| `UVICORN_WORKERS` | `1` (already the default) |
| `SERVER_PORT` | `5000` — matches `Dockerfile` `EXPOSE`, set Scaleway's container port to match |
| `MCP_ENABLED` | `false` (the three MCP domain servers aren't part of this plan) |

## 8. Phased rollout

**Phase 0 — Billing.** Confirm the account can actually create resources; available credit alone may not be sufficient if a payment method is still required. You'll need to do this step yourself.

**Phase 1 — Database.** Create a Scaleway Serverless SQL Database (Postgres 16-compatible), confirm `CREATE EXTENSION vector` succeeds, note connection details.

**Phase 2 — Container.** Create a Serverless Container in your Serverless Containers namespace (AMS region), image `ghcr.io/jwvanderstam/localchat:3.0.0-beta.1` (pin it — `:latest` moves on every push to `main`, so the thing you debug on Friday would not be the thing you deployed on Monday), port 5000, **min scale 1 and max scale 1** (min 1 so the 6.6 GB image is never re-pulled on a cold start during the test; max 1 because migrations run at boot with no cross-instance lock — see §0), env vars from §7, memory ≥2 GB (torch at import time is not free — start at 2–3 GB, watch for OOM restarts).

**Phase 3 — Validate.** Hit `/api/health`, confirm migrations ran (check container logs for "Alembic migrations applied"), log in with `ADMIN_PASSWORD`, confirm document upload works (remember: ephemeral disk, uploaded docs vanish on scale-to-zero — fine for a smoke test, not for real use).

**Phase 4 — Decide on Ollama.** Once Phase 3 is confirmed live, revisit §4 with real numbers in front of you (GPU Instance hourly rate, actual credit burn) rather than deciding blind now.

## 9. Open items only you can resolve

- Whether a payment method is required before resources can be created (§4) — needs your action in the console.
- Which Ollama path (§4) — cost/latency tradeoff, your call once Phase 3 is live.
- Whether the expiry date on your available credit changes the urgency of the GPU decision.
