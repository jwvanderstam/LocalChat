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
already segfaults there and is pinned back to 1.28.0 because of it (LESSONS_LEARNED
Ch. 17). A second such pin would mean the base is dictating the dependency set, and that
is the point at which this trade stops being worth it.

---

## Recording a new ADR

Add it here when a choice would otherwise be re-argued. State the decision in one sentence,
what it forecloses, and the condition that would reopen it. If you cannot name that condition,
the decision is not ready to be recorded.
