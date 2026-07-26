# Lessons Learned

A chronological account of LocalChat's architecture and process decisions,
built from `git log` (924 commits, 2025-12-28 → present) and
[`docs/ROADMAP.md`](ROADMAP.md). Each chapter cites the commits it's built
from so the rationale stays traceable back to source, the same way this
project's own root-cause investigations are expected to work
(see Chapter 7). This is a history, not a changelog — `git log` already
gives you the changelog; this document exists for the *why*.

---

## 1. Scaffolding and the first structural correction

The repository's earliest commits (`5499093`, `77fc7b7`, `09e095c` — all
"initial commit," 2025-12-28) show a project that was pushed to GitHub more
than once during setup, followed immediately by `ce23529` "docs: add
repository move documentation" the same day. Within the first week,
`12fb662` ("refactor: organize project files into standard folder
structure (45 files)," 2026-01-03) moved the codebase from an ad hoc layout
into the `src/`-rooted structure the project still uses.

**Lesson:** the project corrected its own foundation early, before feature
weight made a restructure expensive. The 45-file reorganization happened in
week one, not year one.

## 2. The RAG pipeline takes shape

`1c1520e` ("perf: optimize RAG for large documents with tables — 2x faster
ingestion, 80% better table accuracy," 2025-12-28) and `940a6f1` ("feat: Add
database migration for enhanced citations (Phase 1.1)," 2026-01-16) mark the
core retrieval pipeline's early hardening — chunking that preserves table
structure, and a `metadata` JSONB column + GIN index added specifically to
support citation accuracy. `739d264` ("docs: Phase 3 documentation — schema,
troubleshooting, architecture diagram") shows documentation being written
alongside features from early on, not bolted on afterward — a habit that
later drifted (see Chapter 8) but was clearly the original intent.

## 3. v1.0, and the roadmap reset that followed it immediately

Three commits tell a single story:
- `8a1e323` "chore: finalise roadmap v1.0.0 — all phases resolved" — marks
  the v1.0.0 roadmap 100% complete, explicitly deferring two items (L3
  cache wiring, Pyright strict mode) to v2.0 with reasons given, not silently
  dropped.
- `e2b3f50` "docs: clean documentation for v1.0 first production release" —
  strips phase history, date stamps, and version-specific counts from
  CLAUDE.md/README.md so the "developer guide" stops reading like a project
  log. A deliberate choice to keep living docs living, not archival.
- `636ec07` "docs: replace v1.0.0 roadmap with new agentic RAG roadmap
  (v1.0.1)" — replaces the just-completed roadmap with a 4-phase plan
  (source attribution, adaptive chunking, cloud fallback, query planner,
  long-term memory, GraphRAG, MCP split, aggregator agent, multi-model
  router, feedback loop, workspaces, live connectors) within days.

**Lesson, stated plainly:** v1.0 was declared complete and immediately
judged insufficient. That's not a contradiction — a RAG chat app that
retrieves and answers is a genuinely different product from an *agentic*
one that plans, routes, and self-improves — but it means "v1.0" was a
checkpoint on a much longer arc, not a finish line. Anyone reading the
version number alone would be misled about how much was still ahead. This
same pattern repeats at Chapter 5 (v3.0 replacing v2.0's roadmap) and is
worth naming once here rather than re-discovering each time.

## 4. Building the agentic layer, feature by feature

The v1.0.1 roadmap's items landed as a tight, sequential burst in early
April 2026 — each one small enough to land and verify independently rather
than as one large "agentic RAG" rewrite:

| Commit | Date | Feature |
|---|---|---|
| `72e8490` | 04-08 | GraphRAG entity extraction + query expansion (Feature 2.3), gated behind `GRAPH_RAG_ENABLED=false` by default |
| `f52ff7f` | 04-09 | MCP server split per domain — local-docs/web-search/cloud-connectors (Feature 3.1), with a `CircuitBreaker` per server so a down MCP server degrades to direct fallback instead of failing the request |
| `b7b89d7` | 04-09 | Aggregator Agent + Tool Routing (Feature 3.2) — parallel tool dispatch, dedup by chunk_id |
| `da092bc` | 04-09 | Multi-Model Router (Feature 3.3) — rule-based, <1ms, no network call, never raises |
| `99163dc` | 04-09 | Retrieval Feedback Loop + Adaptive Reranker (Feature 4.1) |
| `40e365d` | 04-09 | Workspace / Persona Mode (Feature 4.2) |
| `b4ecb12` | 04-09 | Live Connector Framework (Feature 4.3) |
| `442de3f` | 04-10 | Multi-user + RBAC groundwork (Phase 5.1) + cleanup of stale phase-tag comments |

**Lesson:** every new capability in this burst (GraphRAG, MCP split,
aggregator agent) shipped **disabled by default** behind a config flag and
degrades gracefully if its dependency is unavailable (MCP circuit breaker,
router "never raises"). None of this agentic layer risked the core RAG path
that already worked — new capability was additive, not a gate on the
existing one.

## 5. FastAPI migration and the architecture hardening that followed

The framework migration was not a single commit — Flask remnants persisted
well past the feature build-out. `068e561` ("refactor: decompose
app_factory.py into factory + bootstrap," 2026-05-29) still describes
"Flask app" and `src/app_factory.py` at 618 lines being split for
testability. `33f4ecd` (05-29) and `65a536b` ("docs(rules): add
architecture.md and update for FastAPI migration," 06-20) show the
documentation catching up to the framework change three weeks later —
`architecture.md` itself "was referenced by CLAUDE.md but never committed"
until this commit, per its own message.

Once FastAPI was the only framework, two coupling-fix commits closed gaps
the migration had opened: `42a0bbd` ("PR1 — mechanical coupling fixes")
removed module-level singleton imports in favor of `request.app.state`
access and replaced positional tuple returns with a named `RetrievalResult`
tuple; `7b4408c` ("PR2") made `AppState` I/O opt-out so tests skip file I/O
by default.

**Lesson:** a framework migration that "removes Flask from imports" is not
the same as "the migration is done" — the coupling cleanup and doc sync
lagged the code by weeks, and both were necessary before the migration
could be called complete. This is the same category of gap this project's
own drift audit (Chapter 8) found again later: code moves faster than the
docs describing it unless something forces them back in sync.

## 6. Clark-Wilson: soft-delete as a first-class pattern, not per-table cleanup

`15a2949` ("docs: add Clark-Wilson pattern to CLAUDE.md and create v3.0
ROADMAP," 2026-05-31) is the pivotal commit: it names the Clark-Wilson
integrity model explicitly and commits to soft-delete + audit trail +
retire/purge separation as a *codified rule*, not a one-off fix. The
`docs/ROADMAP.md` CW section explains why: "The current codebase has ~12
hard-delete operations across CDI tables. All of them will be converted."

The rollout was staged deliberately, pilot-first:
- `02ba040` (06-27) — CW-1, documents/chunks only, because "chunk IDs are
  embedded in citation references inside conversation history" — the
  highest-integrity CDI, chosen first specifically to prove the pattern
  against the case with the most to lose if it were wrong.
- `e01fa22` (06-30) — CW-2a/2b, conversations + users.
- `a6705ac` (06-30) — CW-2c/2d/2e/2f, the remaining four CDIs in one sweep
  once the pattern was proven.

**Lesson:** a cross-cutting data-integrity rule was proven once, on the
riskiest case, before being mechanically repeated everywhere else — the
same "prove it small, then repeat" shape as Chapter 4's feature rollout.

## 7. Security and quality hardening

A distinct phase, running throughout but concentrated from April onward:
`8f1b2d4` ("fix: full audit — pickle RCE, log injection," 2026-04-23)
replaced `pickle.loads`/`dumps` in the L3 cache with JSON specifically to
close a deserialization RCE, and sanitized five separate log call sites
against CRLF injection from user-controlled values. `ceb427b` ("fix(security):
resolve CodeQL log-injection and stack-trace-exposure alerts," 06-11)
followed the same theme — replacing `str(exc)` with controlled message
literals so internal exception text never reaches a client or a log line
verbatim. `bf638dd` ("Add secret scanning, dependency audit, and harden
default Postgres exposure," 07-16) added `gitleaks` to CI and pre-commit,
`pip-audit` with one documented, justified exception, and closed the DB
port to `127.0.0.1` by default — and `SECURITY.md` records a *historical
leaked local-dev credential and why it was accepted rather than rotated out
of history*, rather than pretending it never happened.

**Lesson:** each hardening pass targeted a specific finding (CodeQL alert,
audit tool output), not a vague "improve security" sweep — and the project
was willing to document an accepted risk in the open (`SECURITY.md`) rather
than hide it, which is itself a form of the same discipline as this
document.

## 8. This session's own findings, in perspective

Two structural issues were found and fixed in the sessions immediately
preceding this document, both worth recording here because they are the
most recent evidence of a pattern that recurs throughout this history:

- **Coverage-percentage as a proxy for test quality.** `docs/TEST_QUALITY_AUDIT.md`
  used mutation testing to find that 5 modules had tests executing code
  without verifying its behavior. Tracing those weak tests to their origin
  commits found `3d3453c` ("Add 18 RAG module tests (100% pass)"),
  `a69c977` ("...0% → ~95%"), `f513073` ("...0% → 100%"), and `b11b4ea`
  ("...coverage gaps") — four of five origin commits explicitly framed
  around a coverage-percentage target, one bulk AI-co-authored. Fixed in
  `613d7ab`. The corrective pattern (assert exact values, cover the
  fallback-equals-tested-value trap, kill tautological assertions, drive
  accumulation loops with ≥2 iterations) is now codified in
  `.claude/rules/testing.md`'s "Assertion-strength checklist."
- **Documentation drifting from the code it describes.** The same audit
  that produced this document found ~17 concrete drift items — a stale
  PostgreSQL version number in two docs, a Flask reference in CLAUDE.md
  describing MCP servers that had been FastAPI since Chapter 5, an
  undocumented `src/cache/` package, missing CI workflow entries — echoing
  Chapter 5's finding almost exactly: code changes faster than the prose
  describing it, and nothing forced them back in sync until an explicit
  audit did.

Both are instances of the same underlying failure mode: **a proxy metric or
a point-in-time description was trusted past the point where it stopped
matching reality**, because nothing continuously re-verified it. That is
also the direct motivation for the in-app documentation mechanism built
alongside this document (`src/docs/service.py`) — settings-page text and
written docs used to be two hand-authored copies of the same information;
after this change, one is generated from the other, so they cannot silently
diverge again the way Chapters 5 and 8 both show they can.

## 9. An external audit, triaged into four buckets, and the bugs it didn't predict

A 2026-07 external code-quality/architecture review produced a long list of
findings. Rather than working the list top to bottom, it was explicitly
triaged into four buckets — fix now, do next, schedule deliberately, park
and say so in writing — with the reasoning that most of the value was in
one cheap change: `a9d9ed4` ("fix: default UVICORN_WORKERS to 1") retires
AppState divergence, split metrics, the Alembic migration race, duplicate
connector polling, and a duplicate reranker scheduler in one line, because
all five are symptoms of the same root cause (per-process state with no
cross-process coordination) rather than five separate bugs. The chart was
then made to match that reality rather than advertise a capability that
didn't exist: `d68620a` fixed `replicaCount` and deleted `hpa.yaml`.

The audit's own bug list turned out to be less interesting than what
implementing its fixes surfaced. Two real defects were found only by
re-reading the exact code path the "atomic ingest" ticket touched, not by
the audit itself:

- `14cdfe4` — `document_exists()` never took a `workspace_id` parameter,
  so two workspaces uploading a same-named file collided: a hash match
  returned the *other* workspace's document id, and a hash mismatch
  soft-deleted the *other* workspace's live document. Neither the audit
  nor the original ticket ("make delete+insert atomic") mentioned this —
  it surfaced only from reading `document_exists()` cold before extending
  it, per the explicit instruction to re-read cold rather than trust the
  existing scoping.
- The same commit replaced re-ingest's soft-delete-old-insert-new with an
  UPDATE in place. The old behavior wasn't a deliberate design — it was
  whatever `_prepare_for_ingestion` happened to do, and it silently
  accumulated one tombstone document row per re-ingest forever, with no
  constraint to catch it. Making "what does replace mean" an explicit,
  answered design question (not an accident of write order) is the
  difference between `14cdfe4`'s fix and a narrower one that only added a
  transaction around the existing behavior.

Two self-corrections are worth recording precisely because they were
*corrections*, not clean first passes: the `STATE_FILE` entry in
`docs/ROADMAP.md`'s Known Accepted Debt section (`c3ed064`) originally
assumed a Helm replica-count fix would close the `readOnlyRootFilesystem`
issue too — re-checking the actual `deployment.yaml` found the two settings
are independent, and the entry was corrected before being trusted. And
`delete_document`'s severity was initially overstated as data loss when it
is soft-delete (chunks survive, recoverable) — caught by re-reading the
method instead of re-asserting the earlier claim.

Not every suspected gap was real. The Helm chart's `APP_ENV` looked
missing from `values.yaml`'s `env:` map — a plausible production
misconfiguration risk, since `validate_secrets()`'s secret-strength checks
are gated on `APP_ENV == 'production'`. Before writing a fix, a throwaway
Docker image (`ENV APP_ENV=production` + `docker run` with no override)
confirmed empirically that a container's baked-in `ENV` survives when
Kubernetes' `envFrom` doesn't mention that key — the Dockerfile already
sets it, so there was no gap. The lesson isn't "gaps are usually
imaginary" — `document_exists()` above was real — it's that a plausible
gap and a confirmed one require the same amount of verification either
way, and the empirical check was cheaper than the alternative of shipping
an unneeded fix or leaving a real one undiagnosed.

`e34e2d0`'s lockfile generation hit the same "verify against the real
target" theme from a different angle: a local Windows venv failed to
build a transitive dependency requiring Rust, which the actual deployment
target (the Dockerfile's `python:3.12-slim` Linux builder stage) already
builds successfully in CI every run. Generating the snapshot from
`docker build --target builder` + `pip freeze` rather than fighting the
Windows toolchain produced a more accurate result *and* less work — the
dev machine's OS was never the right thing to snapshot in the first place.

Finally, a small process failure worth keeping: the first attempt to split
this session's changes into separate commits accidentally swept in
unrelated file deletions that an earlier `git rm` had already staged and
left sitting in the index. `git reset HEAD~1` undid it before it was
pushed, and every subsequent `git add` was done by explicit path with a
`git status` check in between. The fix was mechanical; the reason it was
needed — assuming a clean staging area instead of checking — is the part
worth remembering.

**Lesson:** an audit is a hypothesis list, not a verified bug list — some
items were real and became worse on inspection (`document_exists`, the
tombstone accumulation), some were true-but-incomplete (`STATE_FILE`'s
first-drafted rationale), and at least one was a false positive that only
looked real until it was actually run (`APP_ENV`). The common thread
across all of them is the same one from Chapter 5 and Chapter 8: reading
the actual current code, or actually running the actual target
environment, beats reasoning from what a document (an audit, a ticket, an
earlier paragraph in this same document) says should be true.

---

## Patterns that recurred

- **Prove it small, then repeat mechanically.** Clark-Wilson (documents
  first, then the rest), the v1.0.1 feature burst (each feature independent
  and disabled-by-default), and MM-1's GPU backend abstraction (NVIDIA +
  Apple prove both memory models before AMD is accepted as a
  community-contributed parser) all follow this shape.
- **A roadmap is a checkpoint, not a contract.** v1.0.0 → v1.0.1 (Chapter 3)
  and v2.0 → v3.0 (ROADMAP.md's own predecessor note) both replaced a
  "complete" roadmap with a new one within the same work session. Reading
  any roadmap as "the plan" rather than "the plan as of this commit" will
  mislead.
- **Documentation lags code, silently, until something forces a sync.**
  Chapter 5 (FastAPI migration docs, three weeks behind) and Chapter 8 (this
  session's drift audit) are the same failure at different scales. The
  fix that generalizes past "audit it again later" is Chapter 8's in-app
  docs mechanism — making the running application read its own
  descriptions from the same files a human would, so there is only one copy
  to drift.
- **A metric that stands in for a goal eventually gets optimized instead of
  the goal.** Coverage percentage (Chapter 8) is the clearest instance;
  "roadmap 100% complete" (Chapter 3) is a softer one, since it was
  explicitly caveated with deferred items rather than treated as literally
  done.
- **Security fixes cite a specific finding, not a vague sweep** (Chapter 7)
  — every hardening commit names the CWE, the tool, or the exact log line,
  which is what makes them verifiable after the fact.
- **An external finding is a hypothesis until re-derived from the current
  code.** Chapter 9's audit produced real bugs (`document_exists`), a claim
  that was true but incomplete until combined with an adjacent fact
  (`STATE_FILE`'s first-drafted rationale), and one false positive that
  only looked real until it was actually run (`APP_ENV`). Re-reading the
  exact function cold, or actually executing the actual target environment,
  is what told these apart — trusting the finding's own framing would not
  have.
- **A default behavior is not the same as a decided one.** Chapter 9's
  tombstone-accumulation bug existed because "replace" had never been an
  answered design question — it was just whatever the original write order
  happened to do. Making the implicit choice explicit (soft-delete-old vs.
  update-in-place) was the actual fix; adding a transaction around the old,
  undecided behavior would not have been.
