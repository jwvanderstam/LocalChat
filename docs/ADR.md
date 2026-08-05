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
- The Helm chart is either downgraded to "single-replica only, experimental" in its README
  or deleted in favour of docker-compose. Decided in PG-1; **deletion is the default**
  unless a concrete Kubernetes deployment exists.
- `README.md` stops claiming "production-ready" until the PG Exit Criteria pass.
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

## Recording a new ADR

Add it here when a choice would otherwise be re-argued. State the decision in one sentence,
what it forecloses, and the condition that would reopen it. If you cannot name that condition,
the decision is not ready to be recorded.
