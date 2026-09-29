# Architecture Decision Records

Decisions that constrain what LocalChat is, recorded so they stop being re-litigated.
A decision belongs here when reversing it would change the shape of the codebase rather
than the contents of a module.

Format per record: the decision, what it rules out, and what would justify revisiting it.
A record without a revisit condition is a belief, not a decision — see LESSONS_LEARNED
Ch. 11 on rationales having a shelf life.

---

## ADR-1 — LocalChat is a single-node appliance

**Accepted 2026-08-05** (PG-0). Supersedes nothing; makes explicit what the code has assumed all along.

**Decision.** LocalChat v3.0 is a single-node, self-hosted RAG appliance for a small team
(≤ 25 users). Multi-tenant SaaS and horizontal scaling are out of scope.

**Why this had to be written down.** The codebase has been carrying both answers at once.
The Helm chart, the Redis cache backend and the JWT/RBAC layers imply multi-replica scale;
module-level TTL caches, the per-process admin password salt, in-memory rate limiting, the
`AppState` JSON file and the reranker's `threading.Timer` scheduler all assume exactly one
process. Run two replicas today and cache coherence, rate limits and the active-model
setting diverge silently — no error, just two nodes disagreeing.

Choosing single-node converts that from a latent defect into **legitimate architecture**.
The in-process state model becomes correct rather than lucky, and the "Multi-instance
concurrency" entry under Known Accepted Debt in `ROADMAP.md` becomes a closed question
instead of a standing risk.

**What this rules out**, deliberately: distributed rate limiting, sticky-session SSE,
Redis-mandatory shared state, a distributed lock for migrations and the sync worker, and a
cross-process metrics aggregator. That is months of work this deployment does not need.

**Consequences to execute:**
- ✅ **Helm chart deleted** (2026-08-05). Confirmed with the owner that no concrete Kubernetes
  deployment exists, so the stated default applied: 19 files, 755 lines removed, and
  `DEPLOYMENT.md` rewritten for Docker Compose. Restoration is a `git revert` — but
  reinstating the chart means superseding this ADR first, not just restoring files.
- ✅ **`README.md` read "production-patterned"** from PG-0 until 2026-08-31, with the scope
  (≤ 25 users, single node) stated alongside. With all eight exit criteria met the gate was
  lifted and it now claims production-readiness *for that scope* — the scope sentence stays,
  because it is the half of the claim ADR-1 exists to protect.
- The README and the wiki must describe the *same* product. They currently do not: the wiki
  says "learning journey / reference implementation", the README says "production-ready".
  Two claims means two obligation levels, and the lower one is the honest one today.

**Revisit when:** a concrete deployment needs more than one replica — not when it might, and
not because the architecture would be more interesting. At that point this ADR is superseded
by a new one, and the whole Known Accepted Debt entry reopens with it.

---

## ADR-2 — The database layer stays synchronous

**Accepted 2026-08-05** (PG-0). Ratifies and strengthens the HK-10 deferral in `ROADMAP.md`.

**Decision.** The sync `psycopg` pool stays. Blocking work moves to the threadpool (PERF-1).
Async `psycopg` / `asyncpg` is **rejected**, not deferred.

**Why rejected rather than deferred.** HK-10 deferred the question behind a scale trigger:
"real multi-user adoption **and** inference running off the local GPU". ADR-1 puts that
trigger out of reach — at ≤ 25 users on one node, the event loop is not the bottleneck, and
the threadpool is not a stopgap but the correct answer. A deferral invites the question back
every time async purity itches; a rejection closes it.

The cost of being wrong is bounded, and that is why this is safe to decide now: HK-7 sealed
the data-access boundary, so all DB access already flows through `src/db/` mixins. If this
ADR is ever superseded, the conversion is one layer, not a call-graph-wide rewrite.

**What this rules out:** async database drivers, and the async contagion that would follow
through every caller of `src/db/`.

**Revisit when:** ADR-1 is superseded. Not before — the two decisions stand or fall together.

---

## ADR-3 — The application image is built on a hardened, distroless base

**Accepted 2026-08-19** (#287).

**Decision.** Both build stages use Docker Hardened Images — `dhi.io/python:3.12-dev`
to build the venv, `dhi.io/python:3.12` to run it — pinned by digest, never by tag alone.
The runtime image ships no shell and no package manager and runs as uid 65532.

**Why, stated as what was actually measured.** Base image against base image, scanned
the same day with the same tool:

| | `python:3.12-slim` | `dhi.io/python:3.12` |
|---|---|---|
| Critical | 2 | **0** |
| High | 2 | **3** |
| Medium | 10 | 3 |
| Low | 29 | 12 |
| **Total** | **48** | **19** |
| Packages | 127 | 102 |

Criticals eliminated, total CVEs down ~60%, 25 fewer packages — but **Highs went up**.
This base is not "zero CVE", and the decision does not rest on that claim. All three
Highs are Python packages the base itself ships (`msgpack`, `setuptools`), not OS
packages, and the application runs out of `/opt/venv` where those versions are already
patched.

The number that matters for deployment is the built image. Same `requirements.txt`, same
source, only the base differs — the slim image was rebuilt for this comparison rather than
scanning the older published one, so the dependency pinning of #281 is not confounding it:

| Application image | on `python:3.12-slim` | on `dhi.io/python:3.12` |
|---|---|---|
| Critical | 2 | **0** |
| High | 32 | **4** |
| Medium | 22 | 3 |
| Low | 60 | 12 |
| **Total** | **121** | **20** |
| Packages | 368 | 295 |
| Size | 10.2 GB | 10.1 GB |

Both slim builds — the published image and the freshly rebuilt one — score identically
(2C/32H/22M/60L), which is what establishes that the reduction is the base image and not
the dependency refresh. The 73 packages that disappear are Debian OS packages the
distroless base does not ship.

**Size is not part of the case.** 10.2 GB to 10.1 GB: the base is noise beside ~9.5 GB of
torch and CUDA wheels. Anyone expecting a hardened base to shrink this image is looking at
the wrong layer.

**The durable reason is structural, not numeric.** A CVE count is a snapshot that both
images will churn. What does not churn: no shell means no shell-based exploitation path
and no `docker exec sh` for an attacker who lands a foothold; no package manager means
nothing can install itself into a running container; nonroot-by-default means the
container does not rely on the Dockerfile remembering to drop privileges.

**What this rules out.**

- Installing anything at runtime. Every system library the wheels do not vendor must be
  copied from the builder stage, deliberately.
- Shell-form `CMD`, `HEALTHCHECK`, or `RUN` in the runtime stage — there is no `sh` to
  expand `${VAR:-default}` or chain `|| exit 1`. `docker-entrypoint.py` owns that job.
- `docker exec <container> sh` as a debugging habit. Use `--entrypoint python`.
- Treating a green build as evidence the image works. A missing native library surfaces
  as SIGSEGV on import, not as a build error, which is why `docker-smoke` is a separate
  gate rather than a line in the Dockerfile.

**The cost of being wrong is bounded**, which is what makes this safe to decide: the base
image is two `FROM` lines. Reverting is a one-commit change, and `docker-smoke` would
prove the reverted image still boots.

**Revisit when:** the hardened base's own Python packages accumulate unpatched Highs
faster than Debian slim's OS packages get patched — re-run the base-to-base scan above and
compare, rather than arguing from either vendor's marketing. Or when a dependency the
application genuinely needs cannot run on a distroless base at all; `onnxruntime` 1.29.0
already segfaults there and was pinned around it — 1.28.0, then 1.30.0 once `docker-smoke`
proved it boots (LESSONS_LEARNED Ch. 17). A second such pin would mean the base is dictating the dependency set, and that
is the point at which this trade stops being worth it.

## ADR-4 — Cloud fallback targets OpenAI-compatible endpoints directly, not a multi-provider adapter

**Accepted 2026-09-03.** Supersedes the implicit choice made when `LiteLLMClient` was
written; `litellm` is held at 1.97.0 until the replacement lands.

**Decision.** LocalChat keeps its optional cloud fallback. It reaches it through a direct
OpenAI-compatible HTTP client rather than through `litellm`, and the endpoint it is pointed
at is a deployment choice, not a library feature.

**What forced the decision.** Dependabot #347 bumped `litellm` 1.97.0 → 1.98.0. That
release hard-depends on `boto3`, which pulled `boto3`, `botocore`, `s3transfer`, `jmespath`
and `python-dateutil` into the runtime lock — the AWS SDK, in the image, to reach Bedrock.

`boto3` is not otherwise a dependency of this project. `src/connectors/s3_connector.py`
imported it lazily and refused cleanly when it was absent, which is what made the arrival
visible: `test_raises_import_error_without_boto3` failed, because boto3 was no longer
absent. The test was right, and it caught a supply-chain expansion nobody asked for.

> **That connector was removed on 2026-09-16** (audit M5, decision D5). The reasoning above
> is why it could never run in the shipped image, and a connector that cannot run is not a
> feature — it is an owner-supplied `endpoint_url` and a fallback to the server's own AWS
> credentials, reachable by anyone who could create a connector. This ADR keeps `boto3` out
> of the image; removing the one module that wanted it makes that decision cost nothing.

**Why a direct client is sufficient, measured against the code rather than argued.**
`src/llm_client.py` uses exactly one litellm call:

```python
litellm.completion(model=, messages=, stream=, temperature=, max_tokens=, api_key=, tools=)
# and reads: response.choices[0].message.content, response.model_dump()
```

That is the OpenAI chat-completions request and response shape, unmodified. litellm is a
pass-through here. It appears in **one module** (`src/llm_client.py`) and one comment in
`src/config.py`; the `ModelClient` Protocol already exists in that same file precisely so
the implementation behind it can be swapped.

**Why sovereignty makes the adapter's value close to zero.** litellm's proposition is
breadth: one interface across OpenAI, Anthropic, Bedrock, Vertex, Azure, Cohere. A
deployment constrained to EU-hosted inference excludes essentially all of them. What
remains — Scaleway's Generative APIs, Mistral, OVHcloud AI Endpoints, or a self-hosted
vLLM on a GPU instance — is uniformly **OpenAI-compatible on the wire**. The adapter would
be translating between endpoints that already share one language.

Stated plainly: **litellm buys optionality this project has decided not to exercise.**

**Three costs, in the order they matter.**

1. **Posture.** The README's first claim is that nothing leaves the machine unless web
   search or cloud fallback is enabled. Shipping the AWS SDK inside that image, to reach a
   provider this deployment will never call, contradicts the claim in spirit even though
   `boto3` is inert unless invoked. For a product positioned on sovereignty, what is in the
   image is part of the claim.
2. **Security surface.** `requirements.in` already carries the note `>=1.83.7 fixes auth
   bypass CVEs`. litellm is large, fast-moving, and has an auth-CVE history. It is
   installed whether or not `CLOUD_FALLBACK_ENABLED` is true — lazy import keeps it
   unloaded, not uninstalled, so it remains in scope for every audit and scanner.
3. **Size.** Thirteen lock entries name litellm as a source, plus the five boto3 brought.
   Real, and the least important of the three: [DEPLOYMENT_SCALEWAY.md](DEPLOYMENT_SCALEWAY.md#6-the-image--size-cold-start-and-which-tag)
   measures 6.60 GB of files, of which `sentence-transformers` accounts for ~5.2 GB. litellm
   is not where the weight is, and this ADR should not pretend otherwise.

**What this forecloses.** A fallback provider that is *not* OpenAI-shaped — Anthropic's
native Messages API, Vertex — stops being a configuration change and becomes a code change.
That is a real loss, and it is accepted deliberately: it is precisely the case the
sovereignty constraint rules out. If the constraint is ever lifted, this ADR is what should
be re-read first.

**What it does not foreclose.** Switching between EU providers, self-hosting the fallback
on a GPU instance, or pointing it at a different OpenAI-compatible endpoint entirely — all
of those stay `.env` changes, as they are today.

**Sequencing, and why the bump is held rather than taken or reverted.** Holding `litellm`
at 1.97.0 lets the six other bumps in #347 land now — `cryptography` 50.0.0 → 50.0.1 among
them — instead of waiting on an architecture change. A security patch should not queue
behind a design decision, and a design decision should not be made under the time pressure
of a security patch. The replacement is a separate change, reviewed as the architecture
change it is.

**Also settled here, because the same recompile is its trigger.** `gunicorn` was a runtime
dependency nothing invoked: every service is uvicorn, and `GUNICORN_TIMEOUT` was read by
`config.py` and consumed by nothing. It is removed, along with that constant, its
`.env.example` line and its `CONFIGURATION.md` row — which disagreed with each other anyway
(300 against 600). ROADMAP's accepted-debt entry named "the next `pip-compile` run for any
reason" as the moment to do this. This was that run.

**Revisit when:** the sovereignty constraint changes, and a non-OpenAI-shaped provider
becomes worth reaching. Or if a second maintained OpenAI-compatible client emerges that is
materially better than `httpx` plus forty lines — at which point the question is which
client, not whether to keep the adapter. Re-adopting litellm would mean accepting boto3,
so that trade should be made explicitly rather than by taking a Dependabot bump.

---

## ADR-5 — Workspace isolation is enforced in the database, through row-level security

**Accepted 2026-09-29** (P2-1b). Builds on migration `0017`; does not supersede ADR-1.

**Decision.** A workspace-scoped transaction runs as the restricted role `localchat_scoped`
with `app.workspace_id` set, both transaction-local, so Postgres refuses rows outside the
scope even when the application forgets to. The scope reaches the connection **explicitly**:
every database method that takes a `Scope` passes it to `get_connection(scope=)`, and
`tests/unit/test_object_authorization_matrix.py` fails any method that does not. The
installation-wide paths — `ALL_WORKSPACES`: an admin naming no workspace, the webhook
receiver, `SyncWorker` — stay on the owner role and so bypass the policies by design.

**Rejected alternatives.** *An ambient contextvar bound by the workspace guard*, read by
`get_connection()`: implicit, and it silently drops at context boundaries — the SSE
generator, threadpool handlers, worker threads — so coverage would read as complete while
being partial, the outcome ROADMAP P2-1b warned about. *A second connection pool logging
in as a restricted identity*: the strongest option, since the request path would never
hold owner credentials, but it doubles the pool and adds a credential to every deployment
— more than a single-node appliance needs. `get_connection(scope=)` is the seam it would
plug into, so choosing the first option now does not foreclose it.

**What this commits to** — written down because it deepens a path rather than choosing one:

- **Shared-schema tenancy as the security boundary.** Every workspace lives in one schema,
  told apart by `workspace_id`. Migration `0003` and P0-1 made that choice; this turns it
  from a convention into a mechanism the application depends on. It is a pattern that scales
  well past this deployment — it is not the small-team assumption.
- **Operator = installation owner.** The `ALL_WORKSPACES` paths run as the owner, which
  encodes one trusted operator who may see every workspace. **This is the small-workgroup
  assumption**, and it is contained in one branch of `get_connection()`.
- **Postgres as the enforcement layer.** The second line of defence exists only there.
  Already implied by pgvector, so the marginal commitment is small.

**What this does not commit to.** A single node. The scope is transaction-local, so it
survives a transaction-pooling proxy and multiple replicas, and adds no in-process state.
The constraints that do tie LocalChat to one process are older and are recorded elsewhere:
in-memory rate limits, revocation cache and OAuth state (why M7 aborts a boot with more
than one worker), the synchronous database layer (ADR-2), and in-process SSE.

**The broader point.** The P0 → P1 → P2 hardening is correct *for ADR-1*, and each step
raises the cost of ever leaving it. That is accumulated investment rather than technical
lock-in, and it is recorded here so it is a known quantity when ADR-1's own revisit
condition fires, rather than an unseen reason not to act on it.

**Coverage, stated plainly.** The seam reaches the 18 methods that address an object by id.
34 more — retrieval (`search_similar_chunks`, `search_lexical_chunks`, `search_memories`)
among them — still take `workspace_id: str | None`, where `None` means every workspace: the
pattern P0-1 removed from the by-id paths. They are converted to `Scope` before the role
switch is turned on, so that retrieval is covered from the first day RLS enforces anything.

**Revisit when:** tenant administrators must be separated from platform operators, or a
deployment requires that operators cannot read workspace content. Then the `ALL_WORKSPACES`
paths move off the owner role — to the second-pool design above, through the same seam.
Also revisit for GKB-1: the policies exclude rows whose `workspace_id` is NULL, which is
exactly how the global knowledge base is specified.

---

## Recording a new ADR

Add it here when a choice would otherwise be re-argued. State the decision in one sentence,
what it forecloses, and the condition that would reopen it. If you cannot name that condition,
the decision is not ready to be recorded.
