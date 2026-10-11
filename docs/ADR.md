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

**Coverage, stated plainly.** The seam reaches 33 methods: the 18 that address an object by
id (P2-1b-i) and the 15 filters — retrieval among them — that took
`workspace_id: str | None` with `None` meaning every workspace (P2-1b-ii). Deliberately
outside it: the inserts and `document_exists`, which take the workspace a row is written to,
and the methods in `workspaces.py` and `workspace_keys.py`, which take the workspace itself.
The inserts matter for the switch: a policy with only `USING` checks new rows against it too,
so a scoped transaction can only write into its own workspace. (Sorting those 34 methods
first found 16 filters; `document_exists` turned out to be a write-side check.)

**Enforced 2026-09-29 (P2-1b-iii), with one consequence the design did not predict.** The
policy changes the vector-search plan: an exact per-workspace scan becomes the HNSW index
filtered afterwards, which on its own returned 19 of 40 requested rows on average and as few
as 0. Scoped transactions therefore also set `hnsw.iterative_scan = strict_order` and
`hnsw.ef_search = 400` (full counts, 92% overlap with the exact answer, faster than before);
the benchmark is in ROADMAP P2-1b-iii. This ties the enforcement to pgvector 0.8 or later.

**The role is re-applied at every boot, not owned by a migration.** A role is a cluster
object, so `pg_dump` never carries it, and a restore into a new cluster left the database
recording 0017 as applied while its role did not exist. `_ensure_extensions_and_tables()`
now creates the role if missing and re-grants it the tables, which also covers tables a
later release adds. The application identity therefore needs `CREATEROLE`, or the provider
must create `localchat_scoped` once — the same requirement 0017 already had.

**Revisit when:** tenant administrators must be separated from platform operators, or a
deployment requires that operators cannot read workspace content. Then the `ALL_WORKSPACES`
paths move off the owner role — to the second-pool design above, through the same seam.
GKB-1 (2026-10-09, migration 0019) answered the question this ADR left open about rows
with a NULL `workspace_id`: a second, `FOR SELECT` policy makes the global tier readable
from every scope and writable from none, and it too requires a scope, so "no scope, no
rows" still holds. The marker is a NULL workspace *and* `contributed_at`, never the NULL
alone.

---

## ADR-6: The generation path is a deterministic pipeline; agentic orchestration is an experiment until an answer-level eval says otherwise

**Proposed 2026-10-01.** Supersedes nothing. Records a choice the code has been making
implicitly, and in two directions at once.

**Decision.** LocalChat answers through a fixed retrieve-then-generate pipeline. A loop in
which the model decides what to retrieve next is **not** part of the product. It may be
built as an experiment, off by default, and it ships only when P2-3 shows it earns its place.

**Why this had to be written down.** The codebase carries two answers to "who decides what
gets retrieved", which is the condition ADR-1 was written to end in a different layer.
The vocabulary says agent: `src/agent/aggregator.py` calls itself a "ReAct-style
orchestrator", the planner emits a `tools` list and `estimated_hops`, and `ToolExecutor`
runs a multi-round function-calling loop. The wiring says pipeline. Verified at `5707cc1`:

| Component | Default | What it actually decides |
|---|---|---|
| `QueryPlanner` | on, when RAG is on and the query is ≥ 7 words | Sub-questions only. Its `tools` field is never read by the default path, and the aggregator path takes tools from the UI flags `use_rag` / `enhance` instead. The schema offers `calculator`, which `ToolRouter.dispatch` would reject with `ValueError`. |
| Multi-hop retrieval | on, when the plan says so | Sub-questions are retrieved **in parallel**. Hop 2 cannot use what hop 1 found, so these are not hops. |
| `ToolExecutor` loop | on (`TOOL_CALLING_ENABLED`) | Runs **only when retrieval returned nothing**: `api_routes.py:346`, `tool_executor = None if (local_ctx or web_ctx)`. Any retrieved context, however irrelevant, removes the model's ability to search again. |
| `AggregatorAgent` | off (`AGGREGATOR_AGENT_ENABLED`) | Parallel fan-out with retry and dedup. No observe-reason-act cycle. |
| `ModelRouter` | off (`MODEL_ROUTER_ENABLED`) | Regex classification of the query text. |

Each piece is careful work; together they are a pipeline wearing agent vocabulary. That is
a latent defect in the same sense ADR-1 meant: nothing errors, but every reader of the
code, including the next session of whoever maintains it, is told the system does
something it does not.

**The two options, each at its strongest, and where each breaks.**

*Build a real harness*: sequential hops, a sufficiency check, retrieval available as a
tool even after context was injected.
- For: bounded re-query is a RAG-quality feature, inside ADR-1's scope rather than against
  it. Multi-hop questions ("compare contract A's SLA with contract B's penalty clause") are
  where single-shot retrieval genuinely fails. And leaving the split identity standing is
  not neutral.
- Against, and decisive today: there is **no evidence of lift**. No answer-level eval
  exists, and the one comparable measurement, DEL-2's GraphRAG run, saw clever retrieval
  fire on 3 of 20 questions. ADR-4 confines inference to local or EU OpenAI-compatible
  models, which are the ones weakest at tool calling (`ToolExecutor` already carries
  workarounds for llama3.2 emitting schema dicts as arguments). Every extra round is a full
  inference on the GPU line `DEPLOYMENT_SCALEWAY.md` already names as the largest cost. A
  loop over retrieved content amplifies prompt injection, so it should not precede handling
  for it. And the strongest *motive* on record is that harness-building is worth learning,
  which is exactly the reason ADR-1's revisit clause excludes: "not because the architecture
  would be more interesting."

*Strip it to a plain pipeline*: delete the planner, the aggregator and the agent framing.
- For: it matches what ADR-1 and ADR-4 already imply. Fixed pipelines suit small models.
  Latency and cost stay predictable, and the planner's extra non-streaming LLM call goes.
- Against, and also decisive: deleting on intuition is the mirror image of building on
  intuition. DEL-2 set the project's standard: when the measurement cannot yet be made,
  **defer, do not delete**. It would also declare multi-hop out of scope permanently,
  which is a product decision nobody has made.

**Why neither.** Both options fail the same test: each acts before the evidence exists.
This ADR takes the position DEL-2 took for GraphRAG and applies it to orchestration: the
pipeline is the product, the harness is a hypothesis, and P2-3 is the instrument that
settles it.

**What this rules out:**
- The model choosing tools or retrieval targets on the default chat path.
- Unbounded tool rounds. Any experimental loop has a hard round cap and a per-request token
  budget, both enforced in code rather than by `TOOL_MAX_ROUNDS` alone.
- Describing any component as an agent, ReAct, or multi-hop unless its behaviour is that.
- Merging an orchestration experiment to the default path on a qualitative impression.

**Consequences to execute.** These make the code agree with the decision; none needs P2-3.
- ⬜ **Multi-hop retrieval drops the caller's scoping** (a live defect, found while writing
  this record). `get_rag_context_multi_hop` takes neither `source_ids` nor
  `additional_workspace_ids`, so a user who narrowed the chat to specific sources and asks a
  ≥ 7-word question the planner judges multi-hop gets retrieval across the whole workspace,
  and a request spanning additional workspaces silently loses them. Workspace isolation
  itself holds; `workspace_id` is still passed. Fix first: it is a correctness bug on the
  default path, independent of everything else here.
- ⬜ The aggregator path passes `filename_filter=[]` and receives no `source_ids` or
  `additional_workspace_ids` (`services/chat.py`, `retrieve_via_aggregator`). Latent while
  the flag is off; enabling it would change what gets searched. Wire them through or delete
  the path.
- ⬜ Planner schema: remove `tools` (and `calculator` with it), or make the pipeline read
  it. A field the model is asked to fill and nothing reads is a prompt-token cost with no
  return.
- ⬜ Measure the planner. Latency it adds against multi-hop questions it changes the answer
  for. If it does not pay for its call, it goes the way of DEL-1, by the same rule.
- ⬜ `api_routes.py:346` becomes documented behaviour, not an accident: tools are the
  fallback when retrieval finds nothing. A comment at the line citing this ADR.
- ⬜ Honest naming: the aggregator docstring loses "ReAct-style"; "multi-hop" in comments
  and the planner becomes "multi-query" unless hops are made sequential.
- ⬜ `ModelRouter` regex: `\bfigure\b` sends "figure out" to VISION, `\bclass\b` and
  `\bscript\b` send "class action" and "film script" to CODE. Latent (router off by
  default); fix or remove before anyone enables it.

**The experiment this ADR licenses.** A bounded re-query: retrieve; let the model judge
whether the context answers the question; if not, let it write one follow-up query;
retrieve once more; answer. At most two retrieval rounds, a fixed token budget, behind a
flag that defaults off, built only after P2-3 exists so that it is measured the day it
runs. Tool results enter `sources` and the persisted trace like any other retrieval, so
the experiment is observable with the instruments the rest of the product already uses.

**The cost of being wrong is bounded.** If the pipeline is the wrong answer, the
experiment above is already the path to the right one, and the retrieval layer it would
call is unchanged. If the harness was never going to earn its place, what this ADR cost is
the consequences list: work that makes the existing code honest either way.

**Revisit when:** P2-3 has a recorded baseline **and** the bounded re-query beats it on the
multi-hop subset of that eval by a margin written into the baseline **before** the
experiment runs, using a model ADR-4 permits. Not when a harness would be more
interesting, and not on a demo that felt better. A second trigger keeps this from becoming
a polite way of never deciding: **if P2-3 has not started by 2026-12-31, this ADR is
re-read on that date**, because a decision whose only revisit condition can be indefinitely
postponed is a deferral, which ADR-2 explains is the weaker form.

> **Status, 2026-10-06.** Two of the facts above have moved; the decision has not. P2-3's
> answer-level baseline exists (`tests/eval/answer_baseline.json`, recorded 2026-10-02 and
> re-taken 2026-10-05), so the first half of the revisit condition is met — but its 105
> cases have no multi-hop subset, so the comparison it asks for cannot yet be run. And GR-1
> (retrieved content as untrusted input) shipped, which was the precondition named for any
> loop over retrieved content. What remains between this ADR and the experiment is a
> multi-hop case set with its margin written down first.

---

## Recording a new ADR

Add it here when a choice would otherwise be re-argued. State the decision in one sentence,
what it forecloses, and the condition that would reopen it. If you cannot name that condition,
the decision is not ready to be recorded.
