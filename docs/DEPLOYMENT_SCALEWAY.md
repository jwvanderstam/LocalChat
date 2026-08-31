# Deploying LocalChat on Scaleway — Test Stack

A companion to [DEPLOYMENT.md](DEPLOYMENT.md), which covers the supported Docker Compose
topology. This one covers a managed-cloud test stack on Scaleway: what each compose
service maps to, what fits badly, what it costs, and what is still unverified.

> **Nothing here has been deployed.** Every claim is labelled by how it was established —
> measured, checked live against Scaleway's docs, or inferred. §11 collects everything
> still unverified into a worklist with the command that settles each one. Read §11 before
> trusting any number in §§2–10.

**Scope.** A single-user smoke test of a single-node appliance ([ADR-1](ADR.md)), not a
production deployment and not a scaled one. LocalChat is single-instance by design; this
document treats that as a constraint to respect rather than a limitation to work around.

---

## 1. Start here

**The shortest useful path**, and the reasoning is in the sections that follow:

1. Get a payment method on the account (§10, Phase 0). Console-only, nothing else works first.
2. Create a Serverless SQL Database with `max_cpu = 1` (§4).
3. Deploy the container from a **pinned version tag**, min scale 1, max scale 1 (§6, §10).
4. Skip Ollama for the first pass (§5, option 4). Everything except chat validates for no GPU spend.
5. Work through §11 with a live stack in front of you.

**Deploy the image unmodified.** It is large (§6) and there are three defensible ways to
shrink it, but changing the supply chain and the target in one step turns a failed
deployment into an ambiguous one. Deploy as-is, measure, then decide.

### The one trap worth stating up front

**Do not deploy `ghcr.io/jwvanderstam/localchat:latest`.** It moves on every push to
`main`, so the thing you debug on Friday is not the thing you deployed on Monday — and it
lags. On 2026-08-31, `latest` was five days stale and carried a fixed crash that broke
every `= ANY(%s)` query, plus a PowerPoint ingest failure. A first deployment spent
debugging already-fixed bugs is a wasted deployment.

`.github/workflows/docker-publish.yml` triggers on `tags: ["v*"]` with `type=semver`, so
tagging `v3.0.0` publishes `ghcr.io/jwvanderstam/localchat:3.0.0` automatically. **Deploy
a version tag.** Verified by reading the workflow; the resulting image has not been pulled
from Scaleway.

---

## 2. Decisions taken, and what would reverse them

Everything below is a deliberate choice rather than a default. Each is argued in the
section named; this table exists so none of them is re-litigated by accident, and so an
inherited assumption is visible as a decision.

| # | Decision | Why | What would reverse it |
|---|---|---|---|
| D1 | **Max scale = 1** on the container | Migrations run at boot in-process with no cross-instance lock; two instances race the Alembic chain. Also ADR-1's single-instance rule. | Nothing, short of a distributed lock for migrations and a coordination layer for `AppState`, the connector poller and the reranker scheduler. Treat as a correctness setting, not a cost one. |
| D2 | **Min scale = 1** for the first deployment | The image is 6.6 GB of files (§6). Scale-to-zero after 15 min idle means a cold pull before the next request. Pinning min scale 1 removes cold start as a variable while you are answering "does this run at all". | Once cold-start time is measured (§11) and judged acceptable, or once a trimmed image exists. Min scale 1 bills continuously — revisit it as soon as the stack works. |
| D3 | **Deploy the image unmodified** | Three routes to a smaller image exist (§6). Changing the supply chain and the target simultaneously makes a failure ambiguous. | The first successful deployment. Then §6's table becomes actionable with real cold-start numbers behind it. |
| D4 | **Serverless SQL Database**, not Managed Database for PostgreSQL | pgvector is supported on the former and not the latter — a 2+ year open feature request. | Scaleway shipping pgvector on the managed product, which would trade serverless autoscaling for conventional session semantics and remove the §4 `SET` caveat entirely. |
| D5 | **`max_cpu = 1`** on the database | The platform ceiling is 15 vCPU, and the Terraform resource *defaults* to it. An explicit ceiling makes runaway compute cost structurally impossible rather than merely unlikely. | Observed contention under real multi-user load. Raise it deliberately; do not discover the default from an invoice. |
| D6 | **Skip Redis** | `REDIS_ENABLED` defaults false, and at max scale 1 there is no cross-instance cache coherence argument for it. | Outgrowing in-memory caching, which at 25 users is unlikely. |
| D7 | **Skip Ollama on the first pass** | It is the only expensive line item (§5) and the only one that needs a persistent GPU VM. Everything else validates without it. | Phase 3 passing. Then §5's four options get decided with real credit-burn numbers instead of blind. |
| D8 | **Accept degraded rate limiting** (§7) | `X-Forwarded-For` is not sanitised at Scaleway's edge, and there is no IP-range middle ground. For a handful of known users this is tolerable. | A public or untrusted user base. §7 lists the alternatives; none is free. **This one is an acceptance, not a fix** — it should be re-read before anyone outside the test group gets a login. |

---

## 3. Why a compose stack does not lift onto Serverless Containers

LocalChat is a four-service compose stack — `app`, `db` (Postgres + pgvector), `redis`,
`ollama` — and [DEPLOYMENT.md](DEPLOYMENT.md) states it is single-instance by design:
`AppState`, the Alembic migration runner, connector polling and the reranker's scheduler
are all in-process state with no cross-instance coordination. [ADR-1](ADR.md) says two
instances "silently disagree about the active model, rate limits and cached state", and
the Helm chart was deliberately deleted for that reason.

Scaleway Serverless Containers is built for the opposite case: one image per service,
autoscaled 0–50 instances, ephemeral storage (24 GB, wiped on restart or scale-to-zero),
scale-to-zero after 15 minutes idle, no GPU, and a hard ceiling of 6 vCPU / 12 GB RAM per
container. *[High confidence — Scaleway's "Containers limitations", checked live 2026-08-18.]*

There is no multi-container or sidecar concept: you cannot deploy a `docker-compose.yml`
as a unit. The stack has to be decomposed service by service.

### Service mapping

| compose service | Scaleway target | Fit | Notes |
|---|---|---|---|
| `app` (FastAPI/Uvicorn) | **Serverless Container** | Good | Stateless HTTP, already single-worker (`UVICORN_WORKERS=1`). Max scale 1 (D1). |
| `db` (Postgres 16 + pgvector) | **Serverless SQL Database** | Good, one caveat (§4) | pgvector confirmed supported *[checked live]*. Not the classic Managed Database — see D4. |
| `redis` | **Skip** | Fine | D6. Falls back to in-memory. |
| `ollama` | **No serverless equivalent — a GPU Instance** | Poor fit, real cost | §5. The actual blocker. |

**Everything Scaleway-specific is additive.** No file in this repository needs to change
to deploy it there: the image is already published, all config is read from environment
variables, and the Scaleway-specific parts are console/CLI/Terraform configuration plus
this document. *[Verified by reading `src/config.py` and the Dockerfile.]*

---

## 4. The database, and the `SET hnsw.ef_search` caveat

### Sizing

The platform range is 0–15 vCPU / 0–60 GB RAM, and you set min/max within it — in the
console under *Edit autoscaling*, or via `min_cpu`/`max_cpu` on
`scaleway_sdb_sql_database`. Scaling moves 25% at a time, at most once a minute, after
sustained utilisation above 90% or below 70% for 10 s.
*[High confidence — Scaleway's technical spec page, checked live 2026-08-27.]*

> **The Terraform resource defaults `max_cpu` to 15.** A block that sets only `name`
> creates the database at the full platform ceiling — the runaway-cost scenario, produced
> silently by a default. *[Confirmed from the provider's argument reference.]* Whether the
> `scw` CLI shares that default was never checked; §11 has it.

Use `min_cpu = 0`, `max_cpu = 1` (D5). `min_cpu = 0` stops idle billing at the cost of a
few seconds of cold start, which is acceptable here.

### The caveat

`src/db/connection.py` runs `SET hnsw.ef_search = 100` once per physical connection, in
psycopg's pool `configure` callback, and relies on it persisting for every later query.
Scaleway's own pgvector documentation warns: *"Query options using SET command require to
be used in a single transaction."*

**The failure is silent.** Nothing crashes; HNSW search runs at the default `ef_search`
instead of 100 and retrieval recall degrades with no error anywhere.

The app now instruments this: it reads the setting back in a separate transaction at
connection time and logs one warning if it did not survive. Verified against pgbouncer in
transaction mode — every query saw `ef_search=40` instead of 100 while the app reported
itself healthy, and without the guard nothing was logged at all.

> **Treat the absence of that warning as a positive signal, not a clean bill of health.**
> pgbouncer in transaction mode does not *reset* session state by default — it **leaks**
> it between clients. The setting survives on whichever server connection carries it and
> is absent on the others, so a connection-time read-back can pass by luck while later
> queries still degrade. Behind any pooler, confirm with `SHOW hnsw.ef_search;` on a live
> connection under load.
>
> *(This corrects the mechanism originally inferred here, which assumed the pooler reset
> session state. It does not. The practical advice was right for the wrong reason.)*

See [DEPLOYMENT.md](DEPLOYMENT.md#connection-poolers-and-vector-search). If it bites, the
fix is confined to `src/db/connection.py`: set it per checkout or per query rather than
per connection.

### Credentials are not Postgres credentials

Serverless SQL Database has no username and password. It authenticates with an **IAM
application ID** as the login and an **IAM API secret key** as the password, via
`scaleway_iam_application` + `scaleway_iam_policy` (`ServerlessSQLDatabaseReadWrite`) +
`scaleway_iam_api_key`. §9's `PG_USER` / `PG_PASSWORD` rows are filled from those, not
from anything that looks like a database user.

---

## 5. Ollama — the cost decision

`src/ollama_client.py` speaks Ollama's native API (`/api/chat`, `/api/embed`), not the
OpenAI-compatible format. That rules out Scaleway's serverless Generative APIs as a
drop-in: using it means rewriting `src/ollama_client.py` and `src/llm_client.py`, not
changing config.

Options, ordered by how much they preserve the app unmodified:

| # | Option | Code change | Cost | Latency |
|---|---|---|---|---|
| 1 | **GPU Instance** running Ollama, on a Private Network attached to the container | None | Highest — hourly, the whole time it is up. Order of €1–3+/hour depending on GPU class, **unverified** (§11) | Good |
| 2 | **CPU Instance** with a small quantised model | None | Much lower | Materially worse — seconds to tens of seconds per response |
| 3 | **Rewrite the LLM client** for Scaleway's OpenAI-compatible Generative APIs | Two source files | Pay-per-token, no VM | Good |
| 4 | **Skip it** (D7) | None | €0 | Chat endpoints fail cleanly; everything else works |

**Start with 4.** App boots, auth, UI, document upload and retrieval all validate. Revisit
with real numbers after Phase 3.

Option 3 is worth naming honestly: it is the cheapest and simplest operationally, and it
moves you off "self-hosted local model", which is the product's premise. That is a
product decision, not a deployment one.

> **Check the account's credit balance and expiry before committing to option 1.** A GPU
> Instance left running burns a test budget faster than expected. Decide up front whether
> it stays up or is created per test session — Terraform (§8) makes the latter practical.

---

## 6. The image — size, cold start, and which tag

### Measured, not estimated

| Measure | Value | What it is |
|---|---|---|
| `docker images` SIZE | 9.92 GB | Docker's layer accounting |
| **Files inside the container** | **6.60 GB** | What has to arrive and unpack |

6.60 GB is the honest figure for cold-start reasoning: `/opt` (the venv) 6022 MB, `/app`
361 MB, `/usr` 120 MB, `/lib` 98 MB. Scaleway pulls *compressed* layers, which are smaller
again — not measured, because it needs a registry push (§11).

Scaleway publishes **no hard image-size limit**, only a ~1 GB recommendation and cold-start
guidance. 6.6 GB will deploy. It just will not wake up quickly.

### Where the weight is

Nothing under `src/` imports `torch`. It is present for one reason: the cross-encoder
reranker, via `sentence-transformers`.

| Package | Size | Reachable here? |
|---|---|---|
| `nvidia-*` (CUDA runtime) | 2855 MB | **No** — a Serverless Container has no GPU |
| `torch` | 1142 MB | Yes, on CPU |
| `triton` (GPU kernel compiler) | 723 MB | **No** — same reason |
| `.mypy_cache` in `/app` | 351 MB | **No** — see below |

### Three routes, measured

The CPU-only figure comes from installing `torch==2.9.1+cpu` and `sentence-transformers`
into a clean `python:3.12-slim` and walking `site-packages`.

| Route | Saves | Cost | Lands at |
|---|---|---|---|
| `.dockerignore` fix | 0.36 GB | none | 6.24 GB |
| CPU-only `torch` from `download.pytorch.org` | 4.0 GB | a second package index in the supply chain | 2.24 GB |
| **Drop `sentence-transformers` for this target** | **5.2 GB** | no reranker here | **~1.0 GB** |

The third lands on Scaleway's own recommendation with **no supply-chain change**, and fits
for a reason beyond size: **the reranker model is not baked into the image** — verified,
only `huggingface_hub`'s dist-info is present. `CrossEncoder(...)` downloads it at first
use, onto ephemeral storage, and re-downloads after every scale-to-zero. On a serverless
target the reranker is a recurring cold-start cost, not just dead weight.

When you act on it, **the two targets want different images**: the appliance keeps CUDA
`torch` and the reranker; a serverless variant drops `sentence-transformers` and sets
`RERANKER_ENABLED=false`. Neither compromises for the other — an additive
`Dockerfile.serverless`, built when the numbers justify it.

> **`.mypy_cache` ships in the image.** `.dockerignore` excludes `.pytest_cache` but not
> `.mypy_cache`, `.ruff_cache` or `design/`. The type-checker cache is 351 MB of the 361 MB
> `/app` directory. The size is the smaller half: **the image differs depending on whether
> the builder happened to run mypy first.** CI builds from a clean checkout, so this has
> never reached a published image — only a locally built one. Three lines in
> `.dockerignore`, no tradeoff.

### Which tag

Deploy a **version tag**, never `latest` — see §1. As of 2026-08-31 that is
`ghcr.io/jwvanderstam/localchat:3.0.0`, published by CI from the `v3.0.0` git tag.

`APP_VERSION` is not worth setting on Scaleway. The image's built-in default now matches
the release, so `GET /api/status` reporting `3.0.0` is a free check that you are running
the image you think you are. *(Until 2026-08-31 it defaulted to `1.0.0` and compose
overrode it to `0.5.0`, so this check was worthless — three declarations had drifted apart.
`tests/unit/test_app_version_is_consistent.py` now holds them together.)*

### Debugging: the image is distroless

Both build stages are Docker Hardened Images. The runtime has **no shell and no package
manager** and runs as **uid 65532**. Scaleway's console "exec into container" will not
work, nor will `docker exec ... sh`, and nothing can be installed into a running instance.

**Logs are the only instrument** — `LOG_FORMAT=json` is already the default. A missing
system library surfaces as **SIGSEGV on import (exit 139, no traceback)**, never as a
readable error. See [ADR-3](ADR.md).

---

## 7. Rate limiting behind Scaleway's edge

**This is a bad default to accept deliberately, not an open question.**

Scaleway does not sanitise `X-Forwarded-For` at the Serverless Containers edge: an external
caller can set `X-Forwarded-For: 1.2.3.4` and it reaches the container unchanged.
*[High confidence on the mechanism — a still-open Scaleway community feature request from
Feb 2024 states it plainly. Moderate on real-world exploitability — not tested against a
live deployment.]*

How LocalChat's limiter is wired (`src/config.py`, `src/app_fastapi.py`,
`docker-entrypoint.py`, [DEPLOYMENT.md](DEPLOYMENT.md)):

- `TRUSTED_PROXY_IPS` decides who is believed when they set `X-Forwarded-For`. Uvicorn's own
  default trust of `127.0.0.1` is deliberately disabled (`--forwarded-allow-ips ""`), so this
  is the only place the decision is made.
- **Behind the bundled nginx, `TRUSTED_PROXY_IPS=*` is safe** — topology guarantees nginx is
  the only possible peer, because the app publishes no port of its own.
- **That guarantee does not hold here.** The peer is always Scaleway's shared ingress, so
  `*` means trusting a header any internet caller can forge: the per-IP login limit becomes
  bypassable by rotating a fake value, and can equally be used to push a real user's IP
  into its limit.
- **`TRUSTED_PROXY_IPS=""`** (the safe default) makes every caller key on Scaleway's ingress
  address, collapsing all users into one shared bucket. On a 25-user appliance that is a
  real availability problem: one active user can exhaust the shared login budget for everyone.
- **There is no IP-range middle ground.** Serverless Containers ingress addresses are
  explicitly documented as unpredictable. Even fixed prefixes would not help — the problem is
  not *which* peer to trust, it is that the trusted peer does not verify what it forwards.

### Options

1. **Accept and document (recommended, D8).** Set `TRUSTED_PROXY_IPS=""`. A shared bucket
   fails *closed* — over-restrictive under load — rather than open, which is the safer
   failure mode for a small trusted group. Write the acceptance down.
2. **Scaleway Edge Services in front.** *[Checked live.]* A paid add-on; needs a Load
   Balancer or Object Storage backend for the console flow (container backends are
   CLI/Terraform-only); its docs describe caching and WAF and nowhere claim to sanitise or
   replace `X-Forwarded-For`. It adds a filtering layer, not a fix, plus custom domain and
   TLS surface. **Not recommended.**
3. **A defence that does not depend on the header.** A global rather than per-IP request
   budget, or invite-only registration — you are already capped at ~25 users by ADR-1 —
   sidesteps the trust problem instead of trying to win it.

---

## 8. Billing, cost ceilings, and Terraform

### There is no hard spend cap

*[High confidence — Scaleway's billing docs, checked live 2026-08-27.]* Budget alerts are
notification-only: estimate-based, lagged behind the invoice, and computed after discounts
and taxes in a way that can mislead. Scaleway's own worked example shows a €150 alert
firing only once €250 of real usage has occurred, because a €100 discount delayed the
billed amount crossing the threshold. **No product-level spend cap exists anywhere in a
Scaleway account.**

The structural ceilings are the real protection, and they are D1 and D5: max scale 1 on the
container, `max_cpu = 1` on the database. Those make runaway compute impossible rather than
merely alerted-about. The GPU Instance (§5) has no equivalent — it bills hourly while it
exists, which is why D7 defers it.

### The webhook path

Budget alerts support a **webhook**, not just SMS and email — confirmed via
`scw billing budget-alert-notification create` (`webhook-urls.{index}`) and the Billing API.
Scaleway POSTs `{"invoice_start_date": ..., "threshold": ...}` when the threshold fires.

That turns "an email arrives, eventually" into "the burn stops within minutes" — *if* a
consumer exists that reacts by deleting or scaling down the GPU instance. **That consumer
is not built.** It needs somewhere to run (a Serverless Function) and credentials scoped to
delete exactly that instance and nothing else. It is the next real step if option 1 in §5
is chosen.

`scripts/scaleway/bootstrap_billing_alert.sh` creates the budget, alert and notification.
It checks before it creates, at every level: `scw billing ... create` is **not idempotent**,
so a second blind run produces a second budget and a second alert silently, and the
duplicate is invisible until the invoice. When a lookup cannot be trusted — the call fails,
or the reply is not the shape expected — it refuses to create rather than risk a duplicate
it could not see. Its `scw` verbs and field names are written from the documented CLI
surface and are **unverified against a live account** (§11); a mismatch makes it refuse, not
duplicate. The matching logic itself is tested.

### Terraform covers everything except billing

*[Confirmed against the provider's resource documentation, checked live 2026-08-27.]*

| Component | Resource | Notes |
|---|---|---|
| Container namespace | `scaleway_container_namespace` | — |
| The app | `scaleway_container` | `min_scale`, `max_scale`, `environment_variables`, `secret_environment_variables`, `private_network_id`, and `image` (accepts a full external address, so `ghcr.io/...:TAG` works directly) |
| Database | `scaleway_sdb_sql_database` | `min_cpu` / `max_cpu` — mind the default (§4) |
| DB credentials | `scaleway_iam_application` + `scaleway_iam_policy` + `scaleway_iam_api_key` | The IAM application ID is the login, the API secret key the password |
| GPU Instance | `scaleway_instance_server` (e.g. `L4-1-24G`) | `user_data` with `cloud-init` for unattended Ollama bootstrap |
| app → Ollama link | `scaleway_vpc` + `scaleway_vpc_private_network` | Containers support Private Network for **outgoing** traffic only, which is the direction needed |
| **Budget / alert / webhook** | **None exists** | `scw billing ...` or the raw API, outside Terraform |

A real `terraform apply` can stand up the database, container, GPU instance and private
network in one pass. The billing gap is a Scaleway platform gap, not a missing Terraform
feature.

> **No `terraform/` directory is committed, deliberately.** A skeleton was drafted but is
> unapplied and untested. Committing untested infrastructure code invites an `apply` by
> someone who trusts it, and a prose warning beside runnable code is the weakest guard
> there is. **Deploy once by console, then write Terraform from what actually worked** —
> the same argument as D3. The table above is the useful artefact until then.

Terraform removes nothing from the phased approach: Phase 0 is still console-only, and D3
still holds. What it changes is how repeatably you can stand the stack up and tear it down
between measurements — which, for a stack you will create and destroy more than once, is
the actual reason to use it.

---

## 9. Environment variables and secrets

Required — the app raises at startup under `APP_ENV=production` if these are unset
(`src/config.py`):

| Variable | Value |
|---|---|
| `APP_ENV` | `production` |
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_hex(32))"` — **secret** |
| `JWT_SECRET_KEY` | same method, different value — **secret** |
| `ADMIN_PASSWORD` | your choice — **secret** |
| `ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` — **secret**. Required for messages and memories, not only OAuth; boot aborts without it. (`TOKEN_ENCRYPTION_KEY` is a legacy alias — use the current name.) |
| `PG_HOST`, `PG_PORT`, `PG_DB` | From the Serverless SQL Database connection details |
| `PG_USER` | **The IAM application ID** — not a Postgres username (§4) |
| `PG_PASSWORD` | **The IAM API secret key** — **secret** (§4) |
| `METRICS_TOKEN` | Generate one. **There is no `METRICS_ENABLED` setting**; leaving this unset is what makes `/api/metrics` public. |
| `TRUSTED_PROXY_IPS` | `""` — see §7 and D8 |
| `REDIS_ENABLED` | `false` |
| `OLLAMA_BASE_URL` | The GPU Instance's private address, or leave unreachable for the no-chat pass |
| `UVICORN_WORKERS` | `1` (already the default) |
| `SERVER_PORT` | `5000` — matches the Dockerfile's `EXPOSE`; set Scaleway's container port to match |
| `MCP_ENABLED` | `false` |

Do **not** set `APP_VERSION` — see §6.

---

## 10. Phased rollout

**Phase 0 — Billing.** Confirm the account can create resources. Available credit may not
be enough if a payment method is still required; entering card details is console-only and
only you can do it. Optionally run `scripts/scaleway/bootstrap_billing_alert.sh` (§8).

**Phase 1 — Database.** Create a Serverless SQL Database, `min_cpu = 0`, `max_cpu = 1`.
Confirm `CREATE EXTENSION vector` succeeds. Create the IAM application, policy and API key
(§4) and note the connection details.

**Phase 2 — Container.** Serverless Container in the AMS namespace. Image
`ghcr.io/jwvanderstam/localchat:3.0.0` — **a version tag, not `latest`** (§1). Port 5000.
**Min scale 1, max scale 1** (D1, D2). Env from §9. Memory ≥ 2 GB — torch at import time is
not free; start at 2–3 GB and watch for OOM restarts.

**Phase 3 — Validate.**

- `GET /api/health` answers.
- `GET /api/status` reports **3.0.0** — confirms the image you think you deployed (§6).
- Container logs show the Alembic chain applied.
- Log in with `ADMIN_PASSWORD`.
- Upload a document and ask a question about it. *(Retrieval works without Ollama;
  generation does not. Note that uploads live on ephemeral disk and vanish on restart —
  fine for a smoke test, not for real use.)*
- Check the logs for the `hnsw.ef_search` warning, then run `SHOW hnsw.ef_search;` on a
  live connection under load — the warning's absence is not sufficient (§4).

**Phase 4 — Decide on Ollama.** Revisit §5 with real credit-burn numbers in front of you.

---

## 11. What is unverified, and the check that settles it

Every claim above that is not settled, with the command that settles it and what a
different answer means. Work through it in order rather than rediscovering each one at the
moment it bites.

### Settleable now — no spend, no live stack

| Claim | Why unsettled | The check | If it differs |
|---|---|---|---|
| The `scw billing` verbs and field names `bootstrap_billing_alert.sh` matches on (`.name`, `.budget_id`, `.threshold`, `.budget_alert_id`) | Written from the documented CLI surface; `scw` was not installed when it was written | `scw billing budget list -o json`, then the same for `budget-alert list` and `budget-alert-notification list` | Adjust the `MATCHED ON:` comments. Safe by construction: a wrong field name matches nothing and the script refuses — the symptom is a refusal, never a duplicate. |
| That `scw sdb sql database create` shares the Terraform provider's `max_cpu` default of 15 (§4) | Only the *provider's* default was confirmed; the CLI's was never checked | `scw sdb sql database create --help` | If shared, the trap is not Terraform-specific and `max_cpu = 1` must be passed explicitly on the CLI path too. If the flag is required, the CLI path is the safer one. |
| GPU Instance hourly rate (§5) | Never fetched | `scw instance server-type list zone=fr-par-2 -o json`, against the current pricing page | Feeds the §5 decision and sets the budget figures the bootstrap script needs — those are guesses until this is real. |
| Compressed image size (§6 measured 6.60 GB of files and 9.92 GB of layers, both uncompressed) | Needs a registry push to observe | `docker manifest inspect ghcr.io/jwvanderstam/localchat:3.0.0` | Sets the honest cold-start expectation. D2 avoids the problem during the test either way, so this informs the §6 trim decision rather than blocking anything. |
| The webhook payload shape `{"invoice_start_date": ..., "threshold": ...}` (§8) | From Scaleway's docs; never received | Point the webhook at a request-capture endpoint and set the threshold to €1 so it fires early | The eventual consumer parses this. A wrong shape means it silently no-ops at exactly the moment it should stop the burn — the one failure that costs money. Worth the €1. |

### Settleable only against a live stack

| Claim | Why unsettled | The check | If it differs |
|---|---|---|---|
| `hnsw.ef_search = 100` persists across transactions under Scaleway's pooler (§4) | Inferred from Scaleway's `SET` caveat plus the connection code; never run against a live Serverless SQL Database | `SHOW hnsw.ef_search;` after the app has served several requests, under load | It fails silently — retrieval degrades, nothing errors. The fix is confined to `src/db/connection.py`: set it per checkout or per query. |
| `X-Forwarded-For` is spoofable at the edge (§7) | Scaleway's own unresolved forum post states the behaviour; not tested | Behavioural, because the app logs no client IP — the limiter keys on `request.client.host` (`src/security_fastapi.py`). Exhaust the limit on a limited endpoint with a fixed `X-Forwarded-For`, then repeat rotating the header. A reset budget means the header is trusted and spoofable; an unchanged one means everyone shares one bucket. | Those are the two failure modes §7 describes and the check distinguishes them. Either way the response is §7's options — the point is to know which you accepted. |
| Cold start after scale-to-zero (§6) | Never measured; the compressed size it depends on is itself unmeasured | Idle past 15 minutes, then time the first request | Decides whether a trimmed image is worth building, or whether min scale 1 is simply the answer (D2). |
| That the image runs on Scaleway at all | Nothing has been deployed | Phase 3 | The whole point of the first deployment. D3 exists so that a failure here has one plausible cause. |

**Phase 0 gates all of it.** Every check in the second table, and the pricing and webhook
rows in the first, need an account that can create resources — which still needs a payment
method on file, still console-only, still only you.

---

## 12. Open items only you can resolve

These are decisions, not facts. §11 is the companion list of facts.

- Whether a payment method is required before resources can be created (Phase 0).
- Which Ollama path (§5) — your call once Phase 3 is live and the rate in §11 is real.
- Whether your credit's expiry date changes the urgency of that decision.
- Whether §7's degraded rate limiting stays accepted (D8) once anyone outside the test
  group has a login.

---

## Appendix — how this document was built

Kept because the corrections are more useful than the conclusions: each one is a case of a
plausible inference that measurement overturned.

| Date | What happened |
|---|---|
| 2026-08-18 | Written against the repository as it then stood. Sections were labelled by confidence but not verified. |
| 2026-08-26 | **Re-derived against the code, by measuring rather than reading.** Most held. Six things did not: the image-size guess ("very likely several GB" → 6.60 GB measured); *which dependency mattered* (the trim proposed dropping `kuzu` and `spacy`, ~130 MB, against 4.7 GB of CUDA and torch sitting in plain sight); the `SET hnsw.ef_search` mechanism (the pooler leaks session state, it does not reset it); two environment variable names (`TOKEN_ENCRYPTION_KEY` → `ENCRYPTION_KEY`; `METRICS_ENABLED` does not exist); the distroless runtime, which changes how you debug; and `:latest` as a deployment target. |
| 2026-08-27 | Addendum: cost ceilings (§4), billing and the webhook path (§8), the `X-Forwarded-For` problem (§7), a Terraform assessment (§8), and §11 — turning scattered confidence labels into a worklist. |
| 2026-08-31 | **Consolidated into this document**, and renamed from `localchat_scaleway_deployment_plan.md`. Corrections were folded into the sections they correct rather than layered in front of them: reading it end to end had come to mean reconstructing the current truth by diffing three revisions. §9's `PG_USER`/`PG_PASSWORD` rows were still wrong in the table someone would copy from, three revisions after being identified. Decisions were collected into §2, since several were being re-litigated by accident. Updated for `kuzu`'s removal, and for the tag to deploy — `:latest` was five days stale that day and carried two fixed bugs, which is the concrete form of the hazard §1 now states outright. |

**The pattern worth naming**, since it recurs in every row: each correction replaced a
*plausible inference* with a *measurement*, and the inference was never obviously wrong —
it was wrong in a way only checking could reveal. That is what §11 is for. Prefer a check
over an argument, and when a check is not available, say so in the sentence that makes the
claim.
