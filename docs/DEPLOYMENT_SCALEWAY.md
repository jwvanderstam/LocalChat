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

> **Phases 0 to 4 are done.** The whole stack has been built, verified end to end and torn
> down more than once — first on 2026-09-05 for €0.13. Only Phase 5, the GPU, is open.
> Every phase is a script, written from what the manual run actually did (D3):
>
> ```bash
> bash scripts/scaleway/provision.sh          # Phase 1 — project, database, IAM
> bash scripts/scaleway/deploy_container.sh   # Phase 2 — namespace and container
> python scripts/scaleway/verify_deployment.py <endpoint>   # Phase 3 — the gate
> bash scripts/scaleway/deploy_embeddings.sh  # Phase 4 — Ollama on CPU
> python scripts/scaleway/verify_deployment.py <endpoint> --pull-model nomic-embed-text
> ```
>
> All of them are idempotent. To tear it down: [COST_KILL_SWITCH.md](COST_KILL_SWITCH.md).
>
> **Nothing is standing as of 2026-09-08** — the project lists zero of every billable
> resource type. But the stack is ephemeral by intent, not by mechanism: nothing deletes it
> on a timer, and one was once found still running two days after it was believed gone. The
> resource ids quoted in §10 are from that day's build and are gone with it; the shape is
> what they are there for. [DEPLOYMENT_LOG.md](DEPLOYMENT_LOG.md) says what was last left
> up, and the account is the only authority on what actually is.

1. ~~Get a payment method on the account~~ — not required; resources create without one.
2. Create a Serverless SQL Database with `cpu-max = 1` (§4) — `provision.sh` does this.
3. Deploy the container from a **pinned version tag**, min scale 1, max scale 1 (§6, §10).
4. Skip Ollama for the first pass (§5, option 4) — but note it blocks the document path,
   not just chat.
5. Work through §11 with a live stack in front of you — two rows are left.
6. Add embeddings on a **CPU** Instance before considering a GPU (§5) — the CPU box is a
   disposable stand-in, and everything built around it is what the GPU step reuses.

**Deploy the image unmodified.** It is large (§6) and there are three defensible ways to
shrink it, but changing the supply chain and the target in one step turns a failed
deployment into an ambiguous one. Deploy as-is, measure, then decide.

> **The stack is ephemeral; the landing host is not.** Deploy, test, destroy is the
> pattern — nothing here is meant to stay up. A separate, permanently reachable machine
> carries the public face of that: see [§13](#13-the-landing-host).

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
| D8 | **Accept degraded rate limiting** (§7) | `X-Forwarded-For` is not sanitised at Scaleway's edge, and there is no IP-range middle ground. For a handful of known users this is tolerable. **Confirmed live 2026-09-08:** the shared bucket is what the deployment does, measured rather than assumed (§11). | A public or untrusted user base. §7 lists the alternatives; none is free. **This one is an acceptance, not a fix** — it should be re-read before anyone outside the test group gets a login. |

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
> silently by a default. *[Confirmed from the provider's argument reference.]*
>
> **The CLI does not share that default, and the command is `scw sdb-sql`, not `scw sdb`.**
> `scw sdb-sql database create` *requires* `cpu-min` and `cpu-max` — note the argument
> order and the hyphen; there is no `max_cpu` — and refuses without them. The trap is
> Terraform-specific, which makes the CLI the safer path for Phase 1.
> *[Confirmed against `scw` 2.61.0, 2026-09-05.]*

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
| 1 | **GPU Instance** running Ollama, on a Private Network attached to the container | None | Highest — hourly, the whole time it is up. `L4-1-24G` is **€0.787/h — about €575/month left running**; `L40S-1-48G` €1.47/h, `H100-1-80G` €2.87/h. *[Measured via `scw instance server-type list zone=fr-par-2`, 2026-09-05.]* | Good |
| 2 | **CPU Instance** with a small quantised model | None | Much lower | Materially worse — seconds to tens of seconds per response |
| 3 | **Rewrite the LLM client** for Scaleway's OpenAI-compatible Generative APIs | Two source files | Pay-per-token, no VM | Good |
| 4 | **Skip it** (D7) | None | €0 | Chat endpoints fail cleanly — **and so does document ingest**, since embedding goes through Ollama too. Boot, auth, database and health all validate; the document path does not (§10, Phase 3) |

**Start with 4.** App boots and auth, the database and health all validate — but *not*
document upload or retrieval, which need an embedding model (corrected 2026-09-05 against
the live deployment; this used to claim they worked).

Option 3 is worth naming honestly: it is the cheapest and simplest operationally, and it
moves you off "self-hosted local model", which is the product's premise. That is a
product decision, not a deployment one.

### Option 2 is a stage, not an alternative

**Do not treat 2 and 1 as competing choices. Run 2 first, then replace it with 1.**

The application knows exactly one Ollama endpoint — `OLLAMA_BASE_URL` (`src/config.py`),
and `OllamaClient` takes a single `base_url`. Embeddings and generation both go there, so
there is no "CPU for embeddings, GPU for generation" split without a code change.

That sounds like a limitation and is the opposite. It makes the CPU Instance a **disposable
stand-in rather than a foundation**: Ollama presents the identical API on a GPU box, so
moving from one to the other is `OLLAMA_BASE_URL` plus a container redeploy. One variable.

What carries forward is not the instance — it is the plumbing:

- the VPC private network, and proof the container can reach an instance at all
- the firewall rules
- the cloud-init that installs Ollama and pulls the model
- proof that ingest works end to end, which nothing has yet demonstrated

Those are exactly what you would otherwise be debugging **for the first time** while a
€0.787/h meter runs. A GPU Instance bills for every hour it *exists*, not every hour it is
useful, so an hour of plumbing debug on it is pure waste — and plumbing is where first
deployments fail.

**Costs, measured 2026-09-05.** The cheapest 4 GiB CPU Instance is `DEV1-M` at
**€0.0202/h ≈ €14.70/month** left running — 30% of the €50 ceiling, permanently. Per
session it is **€0.16 for a full working day**. Run it with the same discipline the GPU
demands: up while testing, gone afterwards. `panic_teardown.sh` already deletes instances
with their volumes and IP, so tearing down is one command.

> **Build the GPU as a separate instance. Never resize the CPU one.** Both then exist
> briefly, you confirm generation works, and only then delete the CPU Instance. Resizing
> discards the fallback at the moment you are most likely to need it.

### One zone: `fr-par-2`

**Every Instance goes in `fr-par-2`.** The container and the Serverless SQL Database are
*regional* services with no zone at all (`fr-par`), so this rule governs Instances only —
but for those it is absolute, and `fr-par-2` is the zone that makes it possible.

Measured 2026-09-05 with `scw instance server-type list zone=<z>`:

| Type | fr-par-1 | fr-par-2 | fr-par-3 |
|---|---|---|---|
| `L4-1-24G` (GPU, €0.787/h) | available | **available** | not offered |
| `L40S-1-48G` (GPU, €1.47/h) | **not offered** | **available** | not offered |
| `DEV1-M`, `DEV1-L`, `BASIC2-A2C-4G` | available | **available** | not offered |

`fr-par-1` fails the rule on one row, and it is the row that matters most later: the L40S
is the machine you move to if the L4's 24 GB of VRAM proves tight for a larger model.
Discovering that mid-migration means moving zones with a private network already wired.
`fr-par-3` offers none of these types.

Keeping every Instance in one zone also removes a question this document could otherwise
only guess at — whether a regional private network behaves the same across zones. It
should. It has not been tested, and now it does not need to be.

> **Check the account's credit balance and expiry before committing to option 1.** A GPU
> Instance left running burns a test budget faster than expected. Decide up front whether
> it stays up or is created per test session — Terraform (§8) makes the latter practical.

---

## 6. The image — size, cold start, and which tag

### Measured, not estimated

> **Compressed: 2.99 GB across 10 layers**, of which **one layer is 2.96 GB** — the
> virtualenv, and effectively the whole image. Measured from the registry manifest for
> `3.0.0` on 2026-09-05. Any trim that does not touch that layer changes nothing.

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

Deploy an **immutable tag**, never `latest` — see §1. For a release that is a version
tag, `ghcr.io/jwvanderstam/localchat:3.0.0`, published by CI from the `v3.0.0` git tag. To
test what is on `main` ahead of a release — which is usually what this stack is for — deploy
`sha-<commit>`, published by CI on every push. `main` runs ahead of `3.0.0`, so the release
tag is the *older* image whenever a fix has landed since.

`APP_VERSION` is not worth setting on Scaleway, and it is **not** a check that you are
running the image you think you are. It is a constant in `config.py`: every build since the
`v3.0.0` tag reports `3.0.0`, so it identifies the release and says nothing about the build.
On 2026-09-08 a container was deployed on `sha-359069a`, silently reverted to `3.0.0` by
Phase 4, and reported `3.0.0` throughout. Ask Scaleway which image is deployed
(`scw container container list`) — that is the only answer that distinguishes builds.
*(This paragraph also said the version was on `GET /api/status` until 2026-09-08. It is
admin-only on `GET /api/settings/stats`, as §10's Phase 3 has said since 2026-09-05.)*

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
Feb 2024 states it plainly. Untested, and not testable while the deployment trusts no proxy:
with `TRUSTED_PROXY_IPS` empty the app never reads the header, so a probe cannot tell a
sanitising edge from an app that ignores it (§11).]*

**What is measured, on the live stack (2026-09-08):** the limiter ignores
`X-Forwarded-For` entirely and every caller shares one bucket. Rotating a forged header
across the login limit changed nothing; neither did removing it. That is option 1 below,
already in force by default.

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

> **The brake itself is [COST_KILL_SWITCH.md](COST_KILL_SWITCH.md).** This section explains
> why no cap exists; that page is what you run when something is burning. Read it before
> you need it, not while.

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
`scw billing ... create` is **not idempotent**, so a blind second run adds a second budget
and a second alert silently, and the duplicate is invisible until the invoice. The script
is shaped entirely by how little of that the CLI lets it check:

Neither `budget-alert list` nor `budget-alert-notification list` exists — but that turns
out not to matter, because **`billing budget list` returns the whole tree**: every budget
with its `alerts[]`, and every alert with its `notifications[]`. One GET establishes all
three levels, which is why nothing here ever creates blind.

| Level | Identified by | So the script |
|---|---|---|
| `budget` | nothing — a budget has **no name**, only `consumption_limit` and `enabled` | updates the one that exists, or creates the first. More than one is **refused**: with no name there is no way to tell which is the guardrail. |
| `budget-alert` | its `threshold` — **a percentage of the budget, not an amount** — read from the budget's nested `alerts[]` | creates one only when no alert at that threshold exists. An alert at a *different* threshold is left alone — two thresholds on one budget are a legitimate configuration. |
| `budget-alert-notification` | presence in the alert's nested `notifications[]` | attaches a webhook only to an alert that has none. The reply does not expose destinations, so "already notified" is as far as it can tell; repointing means deleting first. |

An unreadable reply is refused rather than read as "absent" — reading a failure as absent
is exactly what would create the duplicate. Note that `consumption_limit` comes back as
`{currency_code, units, nanos}`, not a scalar.

*[Verified against `scw` 2.61.0 and a live account, 2026-09-05: created the €50 budget and
its 40% alert, then re-ran twice — the second run was a single GET and no writes.]*

> **`threshold` is a percentage, and this page called it euros until 2026-09-08.** Nothing
> renders a unit — the API returns a bare `"threshold": 40`, and `consumption_limit` comes
> back with an empty `currency_code` — so no amount of looking settles it. What settles it
> is the constraint: `threshold=101` and `threshold=150` are both refused with *"must be
> lower than or equal to 100"*. So the guardrail created on 2026-09-05 warns at **40% of
> €50 = €20**, not at €40. Earlier and more conservative than intended, which is why it was
> never noticed. Raising the warning to €40 means `ALERT_THRESHOLD=80`. The
decision logic is covered by `tests/unit/test_bootstrap_billing_alert.py`, which runs the
script against a recording `scw` shim and asserts the exact call sequence.

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

**Phase 0 — Billing. Done, 2026-09-05.** The account creates resources without further
setup — the budget, a project and the database all went through. The budget guardrail is
live: €50 ceiling, alert at 40% of it — €20, not €40 (§8).

**Phase 1 — Database. Done.** `provision.sh` owns the whole phase now: the scoped project,
the database, the IAM application, the project-scoped policy and the API key.

```
project   localchat-test   986172ba-5b88-4fd0-8d6d-83ac3872a692
identity  localchat-app    f80a9363-fde6-49b0-80ca-65b0f37a2b56  (policy f301de68, ServerlessSQLDatabaseReadWrite)
database  localchat        d68f9ef0-4e06-496f-b485-cd22b4ef3382   ready, PG 16, cpu 0–1
endpoint  postgres://d68f9ef0-….pg.sdb.fr-par.scw.cloud:5432/localchat?sslmode=require
```

The database id changes on every rebuild — a teardown deletes it — while the project and
the IAM identity survive. That asymmetry is why `provision.sh` rewrites the connection
details in the credential file and reuses the stored API secret: a secret is shown once, so
recreating the database must not orphan the key that reaches it.

Created with `scw sdb-sql database create name=localchat cpu-min=0 cpu-max=1
project-id=…` — the CLI requires both CPU bounds, so §4's `max_cpu = 15` trap cannot fire
on this path. `started: false`: it is scaled to zero and costs nothing until first
connection. `CREATE EXTENSION vector` was settled on 2026-09-05 (pgvector 0.8.2, §11).

### Signing in: where the admin password comes from

`deploy_container.sh` generates the application secrets on its first run — including
`ADMIN_PASSWORD`, which is how you sign in — and writes them to a mode-600 file outside
the repository. It never prints them, so the file is the only copy.

```bash
grep ADMIN_PASSWORD ~/.config/scw/localchat-deploy.env      # bash
Select-String ADMIN_PASSWORD $HOME\.config\scw\localchat-deploy.env   # PowerShell
```

The username is `admin`. Read it in your own terminal rather than through a tool that
records its output — a password pasted into a transcript is a password that has leaked,
which is the whole of §10c.

Lost the file, or it no longer matches what is deployed? Delete it and re-run
`deploy_container.sh`: it generates a fresh set and applies them to the container in the
same pass. Existing sessions are invalidated, which is the point.

**Phase 2 — Container. Done.** `deploy_container.sh` owns it; ids below are from the
2026-09-08 rebuild.

```
namespace  localchat  c69ca6ba-2047-44af-9380-c60312d3daea   fr-par
container  localchat  d8af0eb1-5208-4982-821c-87289651a182
endpoint   https://localchatc69ca6ba-localchat.functions.fnc.fr-par.scw.cloud
image      ghcr.io/jwvanderstam/localchat:sha-359069a   (pulled from ghcr.io directly)
scale      min 1 / max 1 (D1, D2)      memory 3 GB, 1000 mvCPU      port 5000
```

`DEPLOY_IMAGE_TAG` defaults to `3.0.0`, the release tag. Pass a `sha-` tag to deploy what is
on `main` (§6), and check afterwards which image the container actually holds — Phase 4
reverted it to the default until 2026-09-08, and no HTTP check can see that.

Reaching `ghcr.io` from Scaleway needed no registry mirroring — the 2.99 GB pull
took about five minutes from `creating` to `ready`, once.

Two things the CLI does not tell you until it refuses:

- **`memory-limit-bytes` does not take bytes.** `3072000000` is rejected with *"size
  must be defined using the G or GB unit"*. Pass `3GB`.
- **Use `secret-environment-variables` for anything sensitive**, not
  `environment-variables`. Scaleway stores those separately and returns them as argon2
  hashes, so `container get` never echoes a secret.

**Phase 3 — Validate. Done.** `verify_deployment.py` runs the whole table; every row passes
on the 2026-09-08 stack, the last one since Phase 4 exists.

| Check | Result |
|---|---|
| `GET /api/health` answers | ✅ 200 — database `up`, cache `up`, ollama `up` once Phase 4 is deployed |
| The deployed image is the one you think | ⚠️ **this check cannot do that.** `app_version` is `3.0.0` in every build since the release tag; it proves an app answered. Read the image off the container (§6) |
| The Alembic chain applied | ✅ 20 tables, head `0016`, admin user seeded |
| Log in with `ADMIN_PASSWORD` | ✅ 200, session cookie issued |
| `hnsw.ef_search` survives a transaction | ✅ reads back `100` — §4's caveat does not bite |
| Upload a document and ask about it | ✅ ingest, then a semantic retrieval whose query shares no words with what it matches (similarity 0.49) |

> **The version is not on `/api/status`.** That endpoint returns readiness and feature
> flags and carries no version at all. `app_version` lives on **`GET /api/settings/stats`**,
> which is admin-only. This page said `/api/status` until 2026-09-05.

> **Correction: "retrieval works without Ollama" is false.** Ingest embeds every chunk
> through `OllamaClient.generate_embeddings_batch` (`src/rag/processor.py`), so with no
> Ollama reachable an upload fails cleanly with *"No embedding model is configured yet"*
> and **nothing is ingested**. No documents means no retrieval. §5's option 4 is
> therefore narrower than it read: the no-GPU pass validates boot, auth, database,
> migrations, health and login — not the document path.
>
> The cheap way to unblock it is not a GPU. Embeddings are the only thing ingest needs,
> and `nomic-embed-text` runs acceptably on CPU: a small CPU Instance running Ollama with
> an embedding model alone would make upload and retrieval work, leaving only generation
> absent. That is §5 option 2 applied narrowly, and it is a fraction of option 1's
> €575/month.

> **Correction, 2026-09-06.** This page said uploads live on ephemeral disk and vanish
> on restart, and that a durable store was needed before real use. That is wrong.
> `UPLOAD_FOLDER` is a *staging area*: a file is written there, ingested, and deleted —
> twice over, by `_stream_file_ingest` and again in the upload stream's `finally`.
> Nothing reads it back. The durable copy of a document is its extracted text and
> embeddings in PostgreSQL, which survives a restart and is covered by the backup
> recipes in [OPERATIONS.md](OPERATIONS.md).
>
> What a restart *can* lose is an upload in flight, and what a crash can leave behind is
> a staged file nothing will ever delete — the application now clears the staging area at
> startup, since nothing on a cold start can still be mid-ingest.
>
> **Object storage is therefore not needed, and adding it would cost more than it buys:**
> another service, another credential, and a new thing the teardown must sweep — which
> [COST_KILL_SWITCH.md](COST_KILL_SWITCH.md) deliberately does not do for buckets, on the
> grounds that a bucket is the one thing that might hold something unregenerable. The
> safest place for a document nobody needs to keep is nowhere.

**Phase 4 — Embeddings on CPU. Done.** A `DEV1-M` in `fr-par-2` running Ollama with
`nomic-embed-text` only, on a private network the container can reach; `deploy_embeddings.sh`
builds all of it and re-points `OLLAMA_BASE_URL`. This unblocks upload and retrieval, and
generation stays absent by design — generation performance on CPU is not the point and
should not be judged here.

```
network    localchat-backend      307c667f-26f7-4da9-8f93-2dd5ea26db3b
security   localchat-ollama       49b8625d-d0fa-46e7-a036-d9a6572fb003   inbound drop
instance   localchat-embeddings   006b6a04-db91-43f2-b925-c96d17cf5658   DEV1-M, fr-par-2, 172.16.16.2
```

The model is pulled *through the application* — `verify_deployment.py --pull-model
nomic-embed-text` — because the security group drops inbound and there is no SSH to the box.
The pull is also what proves the private network carries traffic.

> **A Phase 4 stack has working retrieval and no chat, and now it says so.** The box holds
> an embedding model and nothing else, which is deliberate — so there is no model the app
> can chat with. Chat requests return a 400 `NoModelConfigured` naming the remedy, and
> `GET /api/status` reports `ready: false` with `active_model: null` beside `ollama: true`
> and `database: true`. Ingest and retrieval are unaffected, and `/api/health` stays
> healthy — it tracks the backing services, so a container is never restarted for having
> no chat model.
>
> To chat on a Phase 4 stack, pull a generation model and **set it active explicitly**
> (`POST /api/models/active`): the active model is chosen only at startup, and only when
> unset, so a model pulled into a running container stays unused until it is selected.
>
> *Until 2026-09-09 this was a defect rather than a refusal.* The app made the embedding
> model active — `get_first_available_model()` filtered embedding families out, then fell
> back to the unfiltered list when the filter left nothing — so `/api/status` reported
> `ready: true` naming an embedding model while every chat request returned the opaque
> `"Failed to generate response"`, the real reason (`does not support chat`, an Ollama 400)
> reaching the log and nowhere else. The fallback is gone, and `ready` no longer claims a
> readiness that excludes chat. See [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

Everything built in this phase is what Phase 5 reuses. That is the reason it comes first.

**Phase 5 — Decide on the GPU.** Revisit §5 with the plumbing already proven and ingest
already working, so that a GPU Instance is only ever asked to answer one question: is
generation acceptable?

*Generation has now been run on the CPU box once, as a sanity check rather than a
measurement: `llama3.2:1b` on the `DEV1-M` answered a RAG question in 32 s, streamed
tokens, and cited the right chunks — but the 1B model said the canary "is not mentioned in
the provided document" while that document was in front of it. Retrieval had done its job;
the model could not use what it was given. That is the question Phase 5 exists to answer,
and a 1B model on three vCPUs is not the instrument for it.* Build it beside the CPU Instance, never by resizing it, and delete
the CPU Instance once generation is confirmed. `L4-1-24G` is €0.787/h ≈ €575/month; everything up to
this point has cost about €1.50 in total, across three build-and-destroy cycles.

---

## 10b. The lesson this deployment taught about this document

Nine claims in this guide were tested by actually deploying. **Eight of them were wrong**,
and one fear turned out to be groundless:

| Claim | Reality |
|---|---|
| Retrieval works without Ollama | It does not. Ingest embeds through Ollama, so nothing is stored at all. |
| The version is on `/api/status` | That endpoint carries no version. |
| The `scw billing` verbs and fields | Half did not exist; a budget has no name to match on. |
| The database command is `scw sdb` | It is `scw sdb-sql`, and it requires both CPU bounds. |
| Terraform's `max_cpu = 15` default also applies to the CLI | It does not. The trap is Terraform-only. |
| `memory-limit-bytes` takes bytes | It requires a G/GB unit. |
| TLS to the database is a hardening choice | It is structural: routing is by TLS SNI. |
| Uploads are lost on restart and need object storage | They are staged and deleted; nothing is lost. |
| `hnsw.ef_search` will not survive the pooler | It survives. The feared defect does not exist. |

### The pattern, and what actually prevented harm

Every one of those came from reading documentation, reading a provider's behaviour, or
reasoning about the code — not from running it. That is not a criticism of writing a plan
before deploying; a plan is how you know what to test. **§11 exists precisely because
someone knew these claims were unverified, and §11 worked.** Each row it held was checked,
and the wrong ones were corrected the moment they were.

The damage came from the claims that were *never in §11* — the ones stated as fact,
confidently enough that nobody thought to list them.

### Why that matters more than being wrong

**An unverified claim in a deployment plan is not neutral. It directs work.**

- "Retrieval works without Ollama" made the no-GPU first pass look sufficient. It made the
  product's whole reason to exist untestable, and the plan said that was fine.
- "Uploads are lost on restart and need object storage" would have bought a bucket nobody
  needed — another service, another credential, and a new thing the teardown must sweep,
  weakening the one guarantee the kill switch offers. Reading three functions in
  `document_routes.py` was the entire cost of not doing that.

Both would have produced work: one deferred, one built. Neither was flagged as uncertain,
because both sounded like descriptions of a system rather than claims about it.

### The rule that follows

**A statement about how the application behaves belongs in §11 unless someone has run it.**
Not "unless it seems obvious" — the two most costly errors above were the two that seemed
most obvious. The check is cheap and specific: *whose behaviour is this, and did I watch it?*
If the answer is "the code's" and "no", it is a claim, and claims go in the register where
they get tested rather than believed.

---

## 10c. The lesson the scripts taught about secrets

`provision.sh` and `deploy_container.sh` were built so that a secret never passes
through a place it could be read. The key's secret goes from `scw` straight into a
mode-600 file outside the repository. It is never echoed, never held in a shell
variable, and never printed in a summary. Scaleway helps: it stores
`secret-environment-variables` separately and reads them back as argon2 hashes, so
`container get` cannot leak one either.

**All of that was true of the success path. The failure path published every one of
them.**

Secrets reach `scw` as *command arguments*. `scw_json`'s error handler prints the
failing command, because a failure with no context cannot be fixed. On 2026-09-06 a
single Scaleway rejection — a transient-state error, not even a real problem — printed
`PG_PASSWORD`, `SECRET_KEY`, `JWT_SECRET_KEY`, `ENCRYPTION_KEY`, `ADMIN_PASSWORD` and
`METRICS_TOKEN` in clear. Everything that appeared had to be rotated.

### The rule

**When a secret is an argument, every path that can print the command is a disclosure
path — and the error path is the one written last and reviewed least.** Care taken on
the happy path is not care; it is care where it was convenient to take it. The question
to ask of any credential-handling code is not "does this print the secret?" but "what
prints on the way out when this fails?"

The fix is redaction at the single choke point every command goes through, not at each
call site:

```bash
_redact() {
  printf '%s' "$*" | sed -E 's/(secret-environment-variables[.][A-Za-z0-9_]+=)[^ ]*/***/g'
}
```

### The part redaction does not fix

Passing a secret as a command-line argument is itself the weaker channel. Arguments are
visible in the process table for as long as the command runs, so **anything that can run
`ps` on the same host can read them**, redaction or not. The CLI offers no stdin path for
these values, so this is accepted rather than solved.

On a single operator's laptop that is a reasonable trade. **On a shared CI runner it is
not**, and it is a live constraint on the deploy job §12 contemplates: a pipeline that
runs `deploy_container.sh` puts six secrets into the process table of a machine it does
not own. Whoever builds that job needs to decide knowingly, not discover it afterwards.

---

## 11. What is unverified, and the check that settles it

Every claim above that is not settled, with the command that settles it and what a
different answer means. Work through it in order rather than rediscovering each one at the
moment it bites.

### Settled — checked 2026-09-05 against `scw` 2.61.0 on the live account

All read-only except the last row, which created the cost guardrail itself.

| Claim | What the check found |
|---|---|
| The `scw billing` verbs and field names `bootstrap_billing_alert.sh` matched on | **Half of them did not exist.** `budget create` takes `consumption-limit`/`enabled`, not `name`/`amount`; a budget has no name at all; and neither `budget-alert list` nor `budget-alert-notification list` exists. The script refused rather than duplicated, as designed — but it could not work. Rewritten around the real surface (§8). |
| How an alert can be found, given no `budget-alert list` | **`budget list` returns the whole tree** — `alerts[]` nested in each budget, `notifications[]` nested in each alert. One GET covers all three levels, so the script matches an alert on its threshold instead of guessing from whether the budget already existed. |
| Whether `scw` shares Terraform's `max_cpu` default of 15 | **No.** The command is `scw sdb-sql database create`, and it requires `cpu-min` and `cpu-max` explicitly. The trap is Terraform-only; the CLI path is safer (§4). |
| GPU Instance hourly rate | **€0.787/h for `L4-1-24G`** — about €575/month left running. L40S-1-48G €1.47/h, H100-1-80G €2.87/h. Feeds §5 and sets the budget figures (§8). |
| That the account can authenticate at all | `scw login` (browser SSO, no secret key handled) writes a working profile. One project exists, `Test_Belgium_Atos`, sharing its id with the organisation — i.e. the default project. |
| Organisation security settings | Already sane: API keys capped at 365 days, lockout after 5 failed logins. Login sessions last 30 days, which is long for an account with this reach. |
| Which zone can hold the whole stack | **`fr-par-2`, and only it.** `fr-par-1` does not offer `L40S-1-48G`; `fr-par-3` offers none of the types this stack needs. Every Instance goes in `fr-par-2` (§5). |
| Compressed image size | **2.99 GB over 10 layers, one of which is 2.96 GB.** Pulled from `ghcr.io` by Scaleway with no mirroring, `creating` to `ready` in about five minutes. |
| That the image runs on Scaleway at all | **It does.** `/api/health` answers in 0.52 s with the database up; `app_version` reports 3.0.0; the Alembic chain applied to head `0016`. |
| `hnsw.ef_search` persistence through Scaleway's pooler (§4) | **It persists.** Reads back `100` in a later transaction, so the pool's `configure` callback is sufficient and `src/db/connection.py` needs no change. |
| Whether pgvector is available | **Yes, 0.8.2**, via `CREATE EXTENSION vector`. |
| Whether TLS to the database is optional | **No.** Serverless SQL routes by TLS **SNI**, so an unencrypted client cannot even name its database. `PG_SSLMODE=require` is structural, not hardening. |
| **The guardrail itself (§8)** | **Created:** budget `acd46bb4` at a €50 ceiling, alert `0de04d05` at threshold 40 — which is 40 *per cent*, i.e. €20 (established 2026-09-08, below), not the €40 this page then claimed. No webhook (no consumer existed to receive one). Two further runs made no writes. |
| Whether a payment method is needed before resources can be created (Phase 0) | **No.** A scoped project and a Serverless SQL Database were both created without one. Phase 0 is closed. |
| What the account is already spending | **€2.31 this period, none of it LocalChat's** — a running `PLAY2-PICO` (`poc-hello-world-par`, fr-par-1) with a flexible IP and a block volume, all in the *default* project. Left alone deliberately; the kill switch refuses that project. |

### Still settleable now — no spend, no live stack

| Claim | Why unsettled | The check | If it differs |
|---|---|---|---|
| ~~The webhook payload shape (§8)~~ | **Closed 2026-09-08 as not needed.** The shape only matters to code that parses it, and the decision is not to build that: a consumer that tears the stack down on an unauthenticated POST is a liability, and the alert lags consumption by hours so it cannot be a brake anyway. Delivery goes to **email** instead — supported natively, no endpoint, no public surface. Reopen this row if anyone ever builds a machine consumer | — |
| Whether a budget alert fires when consumption is *already* above the threshold | Set up 2026-09-08 and unresolved. A 1% alert (€0.50) with ~€5 consumed and an email notification attached produced no mail in 2 h 33 min | Leave it armed and look again the next day. If nothing ever arrives, an alert most likely fires on a *crossing* rather than on a standing state — in which case creating one above the line proves nothing, and the check has to be made before the spend, not after | It changes what the guardrail is: a tripwire you must arm in advance, not a condition you can test whenever. It would also mean this test design was wrong rather than the notification being broken. |
| Whether an organisation may hold more than one budget | One now exists and `create` takes no name, but a second was never attempted | `scw billing budget create consumption-limit=1 enabled=false`, then list and delete | If several are allowed, the script's refuse-on-more-than-one guard is the right behaviour but becomes reachable in normal use — and there is still no name to tell them apart. |

### Settled — checked 2026-09-08 against the live stack

| Claim | What the check found |
|---|---|
| Which of §7's two rate-limiting failure modes is live | **The shared bucket.** 14 logins with one fixed `X-Forwarded-For` gave 9 x 401 then 429; eight more with a rotating header, and three with none, stayed 429. A forged header buys nothing, because `TRUSTED_PROXY_IPS` is empty, no `ProxyHeadersMiddleware` is mounted, and every caller keys on Scaleway's ingress address. **D8 is the state of the deployment, not merely its recommendation.** |
| Whether `X-Forwarded-For` is *spoofable at the edge* (§7) | **Still open, and this check cannot settle it.** With no proxy trusted, "the edge stripped the header" and "the app ignored it" are indistinguishable from outside. Settling it means setting `TRUSTED_PROXY_IPS` deliberately and repeating the probe — worth doing only if someone proposes to fix the shared bucket that way, since that setting is the exploitable configuration. |
| What `threshold` on a budget alert means | **A percentage of the budget, not an amount.** Nothing renders a unit, so looking cannot settle it; the constraint can. `threshold=101` and `threshold=150` are both refused with *"must be lower than or equal to 100"*. The guardrail therefore warns at €20, not €40 (§8). |
| Whether the guardrail can reach a human without a webhook | **Yes.** `budget-alert-notification create` takes `email-addresses.{index}` and `sms-phone-numbers.{index}` as well as `webhook-urls.{index}`. An email notification is now attached to the 40% alert, which until then had `notifications: []` and so delivered nothing, anywhere. |
| Whether Phase 4 preserves the deployed image | **It did not.** Rewiring the container re-ran Phase 2 with defaults and rolled a `sha-` deployment back to `3.0.0`. Fixed; `tests/unit/test_deploy_scripts.py` holds it. |

**A payment method was never needed.** An earlier note here said everything billable was
gated behind one. Instances, containers and a database have all been created and billed
since; the account needs nothing added to it.

---

## 12. Open items only you can resolve

These are decisions, not facts. §11 is the companion list of facts.

- ~~Whether a payment method is required before resources can be created (Phase 0).~~
  **Answered 2026-09-05: not required.** Project and database were created without one.
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

---

## 13. The landing host

**LocalChat is deployed to be destroyed.** Deploy, test, destroy is the pattern, and the
cost section is built on it. That leaves a gap the deployment itself cannot fill: between
runs there is nothing to point anyone at, and no stable address that says what this is.

`atospoc.solbyco.nl` fills it. A `PLAY2-PICO` — Scaleway's smallest Instance — running
nginx, permanently up, serving the deployment's instructions and report as a static page.
It has two jobs:

1. **Documentation that outlives the stack.** Publicly reachable whether or not LocalChat
   is running.
2. **An entry point while the stack is up.** When a deployment exists, this is where a
   reader is sent to reach it.

It is deliberately the cheapest thing that can do both. It will evolve, and a plan for it
follows once the LocalChat deployment itself is finished and robustly repeatable — not
before, because its shape depends on what that deployment settles into.

### What is standing

```
DNS       atospoc.solbyco.nl -> 212.47.234.196   zone hosted at OVH, not Scaleway
host      poc-hello-world-par, PLAY2-PICO, fr-par-1, default project
web       nginx, document root /var/www/html
TLS       Let's Encrypt via certbot, auto-renewing, HTTP 301s to HTTPS
firewall  security group `atospoc-web` — inbound default drop
            TCP 80  from 0.0.0.0/0
            TCP 443 from 0.0.0.0/0
            TCP 22  from the operator's IP only
```

The page itself is version-controlled at `scripts/scaleway/landing/index.html`, because a
deliverable that exists only on one machine is not a deliverable. Deploying it is one
command — nginx serves static files from disk per request, so nothing needs reloading:

```bash
scp scripts/scaleway/landing/index.html root@212.47.234.196:/var/www/html/index.html
```

The original placeholder is kept beside it as `index.html.placeholder`, so rolling back is
a `cp`.

### What the page may not contain

It is served over the public internet from a host in the *default* project. It carries no
resource IDs, no private addresses, no keys and no container endpoints — only description.
A reader should learn what happened, never how to reach something.

### Things worth knowing before changing it

**TLS renewal depends on port 80 staying reachable.** Certbot's HTTP-01 challenge needs it.
The nginx plugin handles this correctly through the redirect; a hand-written "everything to
HTTPS" rule without an exception for `/.well-known/acme-challenge/` breaks renewal silently,
and you find out ninety days later. Renewal was proven with `certbot renew --dry-run`, not
merely configured.

**The account was registered without an email address**, so there are no expiry warnings
from Let's Encrypt. The automatic renewal makes that acceptable; re-register with
`certbot update_account` if you want the safety net.

**The certificate lives on this machine.** Rebuild the host and it is gone — this is the
one part of the deployment that is not reproducible from the repository. Moving it into
cloud-init is the obvious fix when the host is next rebuilt.

**SSH is restricted to a single operator IP**, which is a consumer address and may change.
The serial console in the Scaleway UI is the fallback, and is why locking it down this
tightly is safe.

**Scaleway's default security group accepts all inbound traffic.** That is what this host
ran under until 2026-09-06, with port 22 open to the internet. Any new Instance inherits
that default unless given a group of its own — see `deploy_embeddings.sh`, which creates
one for exactly this reason.
