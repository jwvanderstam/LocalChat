# Lessons Learned

A chronological account of LocalChat's architecture and process decisions,
built from `git log` (935 commits, 2025-12-28 → present) and
[`docs/ROADMAP.md`](ROADMAP.md). Each chapter cites the commits it's built
from so the rationale stays traceable back to source, the same way this
project's own root-cause investigations are expected to work
(see Chapter 7). This is a history, not a changelog — `git log` already
gives you the changelog; this document exists for the *why*.

**On reading this document:** the chapters are not equal in length, and
length here is not weight. The later chapters run longer because they were
written within hours of the events they describe, while the early ones
compress months into a paragraph reconstructed from `git log` alone.
Proximity inflates detail. Chapter 1's 45-file restructure and Chapter 6's
soft-delete pattern shaped more of this codebase than anything in the
recent chapters, and they get a fraction of the words. Read the density as
a record of when something was written down, not of how much it mattered —
the same proxy-for-the-real-thing trap Chapter 8 describes, applied to this
document itself.

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

## 10. A shipped fix gets a second bug, and a live app gets a stopwatch

Two more defects surfaced the same night, through two different discovery
modes than Chapter 9's audit — worth recording separately because neither
was found by reviewing a finding; both were found by re-deriving behavior
from the running system.

A follow-up, independent review of `08237a9` (Chapter 9's hybrid-search
fix) found that the fix itself was numerically dead. At the shipped
defaults (`SEMANTIC_WEIGHT=0.70`, `MIN_SIMILARITY_THRESHOLD=0.30`), filtering
on the blended score made survival mathematically impossible for the exact
case the fix was written to solve: a lexical-only chunk's `semantic_score`
is `0.0`, so `combined_score = 0.30 × lexical_score`, and `ts_rank_cd`'s
`rank/(rank+1)` normalization never reaches `1.0` — no lexical-only chunk
could ever clear the threshold, regardless of match quality. Worse, the
same blend diluted *every* pure-semantic result the moment the lexical arm
returned anything at all for that query, so hybrid search could return
*fewer* correct results than plain semantic search did before it existed —
a regression hiding inside a fix. `ce2e4ee` decoupled survival from
ranking (`semantic_score >= min_similarity OR lexical_score > 0`) rather
than adjusting the blend weights, because the bug was in *what gated
membership*, not in the numbers themselves. The existing test for this
code path checked `_merge_semantic_and_lexical` in isolation and never
exercised the pipeline-level filter three lines later — coverage of the
unit, no assertion on the behavior, the exact failure mode
`docs/TEST_QUALITY_AUDIT.md` was written to catch, recurring in code that
audit didn't touch.

Separately, a plain "why is this slow" question was answered entirely from
data already being collected: `/api/metrics.json`'s histograms showed
`/api/chat` at 8.65s, and `docker exec localchat-ollama-1 ollama ps` showed
the active model running a 29%/71% GPU/CPU split at a 24576-token context —
three times the intended 8192. `771d420` found why: `_build_chat_options`
sent `config.MAX_CONTEXT_LENGTH` as Ollama's `num_ctx`, but
`MAX_CONTEXT_LENGTH` is a *character* limit for prompt-formatting
truncation (`OLLAMA_NUM_CTX × 3`, by its own comment) — never meant to
size the model's context window. The correct value, `OLLAMA_NUM_CTX`, was
sitting unused the whole time. Fixed, rebuilt, and measured on the next
real request: 100% GPU, 8192 context, 1.15s. The same confusion had a
second, quieter instance: `.env.example` hardcoded `MAX_CONTEXT_LENGTH=8192`
(silently overriding its own intended `OLLAMA_NUM_CTX × 3` default) and
never mentioned `OLLAMA_NUM_CTX` at all — so a fresh setup following the
example file would have reproduced a version of the same mix-up in a
different place.

A smaller, related pair: the models page's "Connection Info" box called
`/api/admin/stats`, a route that had never existed under that path (the
data lives at `/api/settings/stats`); and the model-pull form never checked
`response.ok` before treating the body as an SSE stream, so a validation
error's plain JSON response fell through the empty parse loop into the
success path and displayed "Pull completed!" for a request rejected before
it reached Ollama. Neither `fetch()` call would ever throw on an HTTP error
status — that's not a bug in either call site alone, it's the same
unchecked assumption in two unrelated files.

**Lesson:** an audit or a fix is a claim about behavior, and the only way
to close the loop is to run the actual system and read what it actually
did — a merge function's own unit test, a shipped fix's commit message, and
an unread histogram are all, in their own way, a description standing in
for an observation. `ce2e4ee` and `771d420` were both found by preferring
the observation.

## 11. Sixteen dependency PRs, and the unit-of-change problem

A routine "check for PRs" found 16 open Dependabot PRs. Thirteen were
green. The three that weren't shared one cause, and it was structural
rather than a bad release: Dependabot had split a single `codeql-action`
upgrade across three PRs (#170 `init`, #171 `analyze`, #173 `autobuild`),
each bumping one workflow step from 4.37.1 to 4.37.3. Because `init`
writes a config file stamped with its own version, every one of the three
produced a workflow running mixed versions and failing identically —
`Loaded a configuration file for version '4.37.3', but running version
'4.37.1'`. None could go green alone, and merging them one at a time would
have left `main` red in between. `222788d` (#186) bumped all three in one
commit; the same check that had been failing in 26 seconds passed in 1m6s.

The same shape appeared again in a different file. Ten of the green PRs
each edited a single line of `requirements.lock.txt`, and the `nvidia-*`
packages sort to adjacent lines — so merging any one of them made the rest
conflict. Eight merged; #175 and #181 became unmergeable, exactly as
predicted before the first merge.

Those two then could not fix themselves, for a reason that had nothing to
do with dependencies. The repository ruleset applied `non_fast_forward` to
`~ALL` branches, and a rebase *is* a force-push — so Dependabot's own
branches were protected against Dependabot. It said so plainly in a PR
comment, which is the only place that failure was ever reported. Excluding
`refs/heads/dependabot/**` fixed it, but the first attempt silently did
not: the settings UI prepends `refs/heads/` to whatever is typed, so
entering the full path stored `refs/heads/refs/heads/dependabot/**` — a
pattern matching no branch that can exist. The UI rendered it as though it
were correct. Only reading the ruleset back through the API showed the
doubled prefix. A neighbouring instance of the same class: `dependabot.yml`
had requested the labels `dependencies`, `automated`, and `ci` since it was
written, none of which existed in the repository, so every Dependabot PR
carried a "labels could not be found" error that nothing acted on.

The durable fix was to stop splitting atomic changes. `532fd28` (#187)
added two `groups:` blocks — `nvidia-*`/`cuda-*` for pip, and
`github/codeql-action*` for Actions — so members of each set always move
together. It validated itself in about two minutes rather than on the next
scheduled run: Dependabot closed both stuck PRs as "Superseded by #188" and
opened one grouped PR in their place, resolving by root cause what two
rebase attempts and a proposed manual bump had not.

That grouped PR then exposed a second-order effect nobody had asked about.
It carried **nine** updates, not the two outstanding — seven `nvidia-*`
packages had never received a PR at all, because `open-pull-requests-limit:
10` was fully consumed by one-package-per-PR churn. The limit had been
silently suppressing updates, and one-per-PR made that invisible. Merging
the group freed the slots, and ten further suppressed updates surfaced
immediately (#189–#198) — including a `thinc` 8.3.13 → 9.1.1 *major* bump,
spaCy's core ML library, which the noise had been hiding behind nine
CUDA-driver version numbers.

**Lesson:** the unit a tool changes must match the unit that has to be
correct. Splitting one atomic upgrade into three PRs does not produce three
small safe changes; it produces three broken states and no good merge
order. The corollary is that a fix at the level of the individual artifact
(rebase it, resolve it, bump it by hand) leaves the generator untouched and
the next batch identical — grouping was the only change made that day that
will still be working next Monday.

**Postscript, same day.** Two things above did not survive the afternoon, and
saying so is the point of this document. `requirements.lock.txt` is gone
(`ff73d3c`), and the `nvidia-cuda` group with it — those packages reach the
tree only transitively, so with no lock file they never appear in a manifest
Dependabot reads. The trigger was asking why the file existed at all.
`e34e2d0` had introduced it five days earlier as a reproducibility snapshot,
not as the security control it was half-remembered as — the actual
supply-chain findings were the Docker digest pin (`e63cb11`) and the Actions
SHA pins (`d6248e8`), both untouched and still in place. Its own commit
message assumed "Dependabot keeps managing requirements.txt's ranges exactly
as before," which was false within days: 17 of the file's lines had been
hand-edited by Dependabot since generation, so it described no build that had
ever run, and four open PRs would each have broken a parent's constraint
(`thinc` vs spaCy `<8.4.0`, `tokenizers` vs transformers `<=0.23.0`,
`pydantic-core` vs pydantic's exact `==2.46.4`, `mpmath` vs sympy `<1.4`)
with nothing to catch it, since neither Docker nor CI installed the file.

Two further corrections landed the same afternoon. Requiring status checks
was added to the ruleset — merges had never been gated on CI, so every green
merge that day was green because a human checked, not because anything
enforced it. And the first attempt scoped that rule to `~ALL` branches, which
rejected the push of every *new* branch (no checks exist yet on a fresh one)
until it was narrowed to the default branch. Both are recorded in `CLAUDE.md`
under "Pull Requests and Merging."

The generalisable part is not the lock file. It is that a fix and the belief
that justified it decay at different rates: the belief here ("Dependabot will
keep to `requirements.txt`") was already false while the artifact it produced
still looked reasonable, and nothing re-checked it until someone asked the
question out loud. A rationale is a claim with a shelf life, and Chapter 9's
rule — re-derive it from the current system rather than trusting its framing —
applies to this project's own decisions, not only to an external auditor's.

---

## 12. RBAC-1, and two defects that hid each other

The session began as "check PRs and merge them" — five grouped Dependabot
updates, all green, merged in an hour. Then "check where we are on the
roadmap", which found `ROADMAP.md` three tickets behind `main`: BUG-1
(#208), BUG-2 (#209) and MM-2 (#210) had all shipped without the roadmap
moving in the same PR. #216 corrected it. The interesting part was not the
drift but its shape — each of those three had shipped *differently* from how
it was written, and none of the differences had been recorded. MM-2 used
`deploy.resources.limits` rather than the proposed top-level `mem_limit`;
BUG-1's real defect was on the write path (`insert_memory` never wrote
`workspace_id` at all), not the read path the ticket described; BUG-2
existed a second time in the aggregator path the ticket never mentioned.

Then RBAC-1, blocked since it was written on three scope questions. Reading
the code before asking them made two of the three moot: a workspace-scoped
`viewer`/`editor`/`owner` tier **already existed** — table, mixin, member
routes, `_ROLE_LEVELS`, and a correct enforcement dependency,
`require_workspace_role_dep`, with **zero call sites**. The ticket proposed
adding `viewer` as a third `users.role` plus a new `require_role_dep`, which
would have produced two different roles named "viewer" at different tiers.
Adopting the existing tier deleted most of the ticket.

The dead dependency was not merely unused. The five workspace routes it was
written for had grown their own checks, and those checks were wrong:
`if role is not None and role != "owner"` — a non-member gets `role is None`,
skips the branch, and proceeds. Two `/members` routes had no check at all,
making `POST` an unauthenticated privilege grant: add yourself as `owner`,
then pass every later owner check legitimately.

Severity was initially ranked from reading the code, and that ranking was
wrong. Probing the pre-fix routes directly gave a different answer: the two
unguarded routes returned **200**, but the three fail-open routes returned
**500** — `get_current_user_id(request)`, called directly rather than through
`Depends`, hit `.credentials` on an unresolved `Depends` sentinel and raised
before reaching the fail-open branch. The dangerous logic was real but
unreachable, masked by a second bug; those three routes had simply never
worked outside demo mode. Inspection produced a plausible story, execution
produced the true one (#217).

Why no test caught any of it: the entire suite runs with `state.testing =
True`, which trips `_is_rbac_bypassed` and short-circuits every check. The
routes had coverage. None of it reached authorisation.

Enforcing membership then required a prerequisite the ticket never
anticipated. `create_workspace` wrote no `workspace_members` row, the route
did not either, and the auto-created `Default` workspace has none — so
**nobody was a member of anything**. Enforcing membership as written would
have locked every non-admin out of every workspace, including ones they had
just created. #219 added creator-ownership and a backfill; #220 wired
`check_workspace_access` into 33 routes.

Then the part worth the chapter. The backfill was numbered from
`file-map.md`, which listed migrations only up to `0011` and was already
missing two that existed. The new file collided with `0012_hybrid_search_tsvector.py`.
Starting the stack showed `alembic_version = 0013` and `workspace_members = 0
rows`: the backfill had never run. The first explanation — that Alembic had
silently resolved the duplicate id in favour of one file — was stated with
more confidence than the evidence supported, and it was wrong.

The actual behaviour only became visible after fixing something else.
`migrations/env.py` called `fileConfig(alembic.ini)` without
`disable_existing_loggers=False`; that parameter defaults to `True` and
`alembic.ini` names only `root`, `sqlalchemy`, `alembic`. Every other logger —
all of `src.*`, `uvicorn.access`, the request log — was switched off, on every
boot, for the life of the process. The app kept serving and stopped saying
anything. Adding the keyword surfaced, immediately, an error that had been
raised and logged on every boot for days:

```
ERROR [src.app_bootstrap] Alembic migration failed
alembic.script.revision.MultipleHeads: Multiple heads are present for given argument 'head'; 0012, 0013
```

Nothing had been silent except the logger. Two defects had been concealing
each other: no migrations applied, and no evidence that none had.

The fix was then declared complete a second time, prematurely. `fileConfig`
damages logging in **two** ways, and `disable_existing_loggers=False` addresses
only the first. It also rewrites the *root* logger: `alembic.ini` sets
`[logger_root] level = WARN` and installs its own handler. Application loggers
carry no handlers of their own, so they inherit that level — `ERROR` passes,
`INFO` does not. That is why the post-#223 boot looked repaired: the
`MultipleHeads` traceback appeared, and `Uvicorn running` appeared because
uvicorn installs its own handlers, while `Alembic migrations applied` and
`Documents in database` were still being dropped. The check that was run
("did log lines come back?") returned true; the check that mattered ("did
*this application's* `INFO` come back?") had not been run. #225 added
`_preserve_root_logging()`, restoring root's level and handlers in a `finally`
around the upgrade — the `finally` mattering on its own, since a migration that
raises must not leave the process unable to log for the rest of its life.

Three one-line fixes in the end (#222, #223, #225); the diagnosis was the
entire cost. The premature all-clear is the more useful half of the story:
a verification that checks a proxy for the thing ("some logs returned") rather
than the thing itself is the same failure this chapter is about, committed
while documenting it. Along the way
two other hypotheses — a hung migration, then stdout buffering — were raised
and killed by evidence (`PYTHONUNBUFFERED=1` was set, no query was blocked,
one healthy process, zero restarts).

A process lesson arrived alongside. The four RBAC PRs were stacked on each
other's branches, and `tests.yml` triggers on `pull_request: branches: [main]`
only — so all four reported *no required checks* while showing `MERGEABLE /
CLEAN` for hours. Not a green build: the absence of one. Merging the base with
`--delete-branch` then auto-**closed** the PR pointing at it, because GitHub
closes rather than retargets. Both are now written into `CLAUDE.md`.

The through-line is one claim in three costumes: *an absent signal reads
exactly like a negative one*. A test that never runs its check, a PR whose CI
never fires, and an error whose logger is disabled all present as "fine". The
only reliable counter is to make the system produce the signal in front of you
— probe the route, run the migration, read the check list — rather than
reasoning about what it would produce.

---

## 13. Authentication was never built, and three green signals said otherwise

RBAC-1 and RBAC-2 guarded 82 routes. Then the browser UI returned 401 on every
call, because **there was no login route** — nothing outside `security_fastapi.py`
had ever called `create_access_token`, no frontend request carried an
`Authorization` header, and `POST /api/logout` had no counterpart. Not in the
FastAPI routes, not in the Flask routes before them. The authorisation system had
always been theoretical; it only looked complete while most routes were open, and
I closed them without checking there was a way in.

What followed was AUTH-1 (login, httpOnly cookie), AUTH-2 (users screen, plus the
precondition stopping the last admin from deleting themselves), workspace API keys
(a chatbot bridge is a *workspace endpoint*, not a person's account), and SEC-1
(`DEMO_MODE` deleted — it disabled authorisation when it meant to limit
reachability, so the safety flag was the risk).

The transferable part is not the features. It is that **three different signals
looked exactly like success and were not**:

| Signal | Why it was empty |
|---|---|
| A green test suite | started *before* the fix it was meant to cover. Happened three times; the count only gave it away — 2471 where 2473 was expected |
| `docker compose up -d --build` | the Dockerfile no longer built, and compose kept serving the previous container without a word. `docker compose ps` said "Up About an hour" |
| A `MERGEABLE / CLEAN` PR | stacked on a feature branch, so `tests.yml` never triggered at all |

Each was indistinguishable from the real thing at a glance, and each needed a
*different* second question: how many tests, when did the container start, which
checks actually ran.

The same shape appeared inside the code. Mocked tests confirmed what I already
believed and hid what was there: a `MagicMock` returning a plain dict never
produced psycopg's `UUID`/`datetime`, so key creation 500'd only against a real
database; `_row_to_user` maps positionally and silently dropped a newly selected
column, so every retired user came back looking live. Both were found by comparing
the API's output to the database, not by reading either.

**Then the owner opened the application.** Four defects in two short messages, none
of which 2545 passing tests had seen:

| Reported as | Actually |
|---|---|
| "creating a user doesn't let me grant workspace access" | true — and even after granting it, the user was still refused everything, because a request without `X-Workspace-ID` fell through to the *global* default workspace |
| "the model page says Ollama is not there" | a 403 rendered as a connection failure. Ollama was running throughout |
| "you don't need Prometheus observability as a viewer" | right, and broader: three Settings tabs answered 403 and rendered empty, which reads as broken rather than as not-for-you |
| "why do I see workspaces I have no access to?" | the switcher listed every workspace on the instance, disclosing names before the correct Access Denied ever fired |

Chasing the second of those uncovered a cross-workspace read: a viewer's document
list returned 26 documents where their workspace holds 20. Authorisation resolved to
a workspace they belonged to, and the query behind it then ran unscoped. It is the
same defect fixed for API keys one day earlier — I had pinned the resolved workspace
for keys and not carried it across to user sessions. Recognising a pattern is not the
same as finishing it.

The tests could not have caught most of these. They assert what the API returns to a
caller the test constructs; nobody had constructed a viewer and looked at the screen.

**Rule taken from this:** verification must name the specific thing expected — this
log line, this container start time, this row shape — because "it looked fine" is
what all three failures produced.

---

## 14. The fifth defect was in the browser, one layer below the fourth

The switcher fix in Ch. 13 scoped `/api/workspaces` to the caller's memberships. The
owner then signed in as an editor and landed in a workspace that editor had no access
to, collecting 403s until they picked the right one by hand.

The fix was not wrong; it was one layer too high. `static/js/workspace.js` reads the
active workspace from `localStorage`, which is **scoped to the browser, not to the
session**. Signing out as an admin working in *Default* and in as an editor without
access to it left that id in place — and the branch that picks a workspace only ran
when nothing was stored, so it never got a turn. Two other modules read the same key
and sent it as `X-Workspace-ID` before the switcher had loaded anything to correct it.

Fixed at both ends: the stored choice is honoured only while it is still one the
server just offered, and signing in clears it before any request can carry it.

**Two frontend defects in two days, both invisible to a green Python suite.** The
suites assert what the API returns; neither could reach a branch that lives in
`localStorage`. So this one shipped with `tests/unit/test_frontend_workspace_selection.py`,
which runs the real `static/js` files under node with stubbed browser globals. Asserting
on the source text — the repo's existing habit for frontend checks — would only have
restated the code I had just written. Verified the way any regression test should be:
5 of the 7 fail with the fix reverted, and the 2 that still pass are the ones guarding
against over-correction.

**Rule taken from this:** when a fix targets what the server *sends*, check what the
client *keeps*. Browser-scoped state outlives the session that wrote it.

---

## 15. The bypass nobody used, that everything depended on

TQ-1b's job was to delete `app.state.testing`, the last authorisation bypass. The ticket
sized it by counting the tests that set the flag: 23 in August, 39 by the time it was
picked up. Both numbers were right and both measured the wrong thing.

Removing it broke **290 tests across 30 files — and 17 of those files never mentioned the
flag.** They built an app with `app.state = MagicMock()`, and `getattr(state, "testing",
False)` returns a truthy `Mock`. The bypass was not something a test opted into. It was
the default, and a test had to opt *out* to exercise authorisation at all.

That reframes three earlier findings. BUG-3's fail-open membership check, RBAC-2's 49
unguarded routes, and the cross-workspace document leak were not separate lapses in
care. They are what a suite produces when authorisation-off is the default state: the
tests were accurate reports of a system nobody was testing.

**The failure mode the ticket warned about happened on the first attempt.** It said a
carelessly converted test "gets quietly weaker rather than loudly red". The first file
converted was green, and authenticated nothing — the `MagicMock` state kept the bypass
alive underneath the new code. Ten passing tests, proving nothing, indistinguishable in
CI from ten real ones.

The fix was to invert the order: **delete the bypass first, then repair what falls over.**
Deletion cannot be faked, and every consequence announces itself. Converting first means
grading your own work against a system that has not changed.

Then the finished conversion was checked the only way that settles it — sabotage token
verification and see whether the tests notice. 95 of 148 went red. Tests that pass with
authentication broken are not testing authentication.

Three assertions changed meaning rather than being fixed. `deleted_by`, `owner_id` and
`create_workspace(owner_id=…)` all asserted `None`, each with a comment explaining that
there was no caller under the bypass. They were faithful records of the wrong system;
they now name the authenticated caller, which is the Clark-Wilson audit trail working in
the tests for the first time.

**Rule taken from this:** count what a mechanism *reaches*, not who invokes it by name.
A default is used by everything that never mentions it.

---

## 16. Two fixes that improved the code and closed nothing

Eight CodeQL alerts were open. #283 assessed all eight, dismissed five with reasons
recorded on the alerts themselves, and fixed the two that were real. Both fixes made the
code better. Neither closed its alert.

**#91, stack-trace exposure.** The route caught `ValueError` and returned `str(exc)` to
the caller. #283 replaced the broad catch with a narrow `LastOwnerError`, which genuinely
stopped unrelated exceptions from below reaching the API response. But the expression the
rule matches on — `str(exc)` in the returned body — was never touched. The alert stayed
open because the scanner had never been looking at the catch.

**#87/#88, log injection.** `LocalChatException.__init__` logged messages carrying user
input, so a newline in a filename could forge a log record under the default plain-text
formatter. #283 stripped CR and LF. That is not what flattening has to mean:
`str.splitlines()` — and most log consumers — also break on VT, FF, the ASCII separators,
NEL and the Unicode line/paragraph separators. A crafted value still split into seven
lines. ESC passed through untouched, letting a value clear or overwrite lines in the
terminal of whoever read the log.

The mistake was neither fix. It was predicting that they would close the alerts without
reading what the rules match on. A scanner finding names a specific expression; a change
that improves the code around it is still an improvement, and the alert is still open.

**The duplicate was the real finding.** The sanitiser #284 hardened did not belong in
`exceptions.py` at all. `sanitize_log_value` already existed in `utils/logging_config.py`
with four callers and the identical weak implementation, and `config.set_active_model`
carried a third inline copy of the same two `.replace()` calls. Fixing the copy CodeQL
happened to flag would have hardened one site of six. Hardening the shared function fixed
all of them — `app_fastapi`, `document_routes`, `workspace_routes`, `request_id`,
`exceptions` and `config`. The alert pointed at one line; the defect was a pattern that
had been copy-pasted three times.

**The test that could not tell the fix from the bug.** #283's route test asserted
`"last owner" in message`. Once the route returns a module constant instead of the
exception's text, that assertion passes either way — constant and exception message both
contain the phrase. #284 made the raise site use a *different* string, so the test now
distinguishes them. This is the tautological-assertion shape from
[`.claude/rules/testing.md`](../.claude/rules/testing.md): an assertion that holds by
construction regardless of which branch produced it. It is also why the first fix looked
convincing.

**The bug demonstrating itself inside its own fix.** The hardened character class was
first written with the literal separator characters in the source. The edit script's own
`splitlines()` split that source line on U+2028 and corrupted it. The regex had to be
written with explicit `\uXXXX` escapes instead — the vulnerability reproducing itself,
one layer up, in the tooling writing the patch.

**Rule taken from this:** an alert is closed by changing the expression it names, not by
improving the code around it, and it is confirmed by re-running the scan rather than by
reasoning about it. Before fixing, run the attack — the old sanitiser was *measured*
leaving a test string in seven pieces, and that measurement is what separated a plausible
fix from a sufficient one.

---

## 17. A base image that turns a missing library into no error at all

The task was to move the application image onto a hardened, distroless base and make
"deploys on a secure container" something CI checks. The base swap itself is two `FROM`
lines. Everything that made this work interesting came from what the new base *removes*.

**Four things the Dockerfile did that the base no longer permits.** No `apt-get libpq5` —
there is no package manager, and `psycopg[binary]` vendors libpq in the wheel anyway. No
`groupadd`/`useradd` — the base already runs as uid 65532 and carries no `/etc/passwd`
entry, so `USER` and every `--chown` became numeric. No `mkdir` for `/app/logs` — no shell,
so the directories arrive by `COPY --from=builder`. And no `sh -c` around `CMD`, which
silently took `${SERVER_PORT:-5000}`, `${UVICORN_WORKERS:-1}` and `${UVICORN_TIMEOUT:-600}`
with it — three knobs `docker-compose.yml` actually sets. `docker-entrypoint.py` exists to
expand them and then `exec` uvicorn, so the server stays PID 1 and still takes signals.

**The failure mode that justifies the whole gate.** A native library the wheels do not
vendor does not produce a build error or an `ImportError`. It produces **SIGSEGV**: the
image builds, publishes, starts, and dies with exit 139, no traceback, the last log line an
unrelated `METRICS_TOKEN` warning. Here that was `onnxruntime` 1.29.0 — reached
transitively through `pymupdf-layout`, which nothing in this codebase imports by name, and
**unpinned**, so the published image had been running 1.28.0 while a fresh resolve produced
1.29.0. Isolating it took four comparisons: 1.29.0 on slim (fine), 1.28.0 on the hardened
base (fine), 1.29.0 on the hardened base (segfault), and the same crash under the base's own
interpreter rather than the copied venv one, which ruled out the venv. `ldd` was clean and
the library diff showed nothing relevant; the root cause is still unknown, and the pin is
recorded as a workaround with its reason, not as a fix.

**Two wrong hypotheses, one of which shipped a change.** `libgomp.so.1` really is absent
from the hardened base, so a copy from the builder stage looked obviously right — and the
segfault persisted. Masking `libgomp` to `/dev/null` afterwards proved every import still
succeeded, so it had never been needed, and the change came back out. A missing thing that
is genuinely missing is not thereby the cause.

**The `.dockerignore` near-miss.** Generic advice — exclude tests, docs, build cruft — is
wrong in this repository. `DocsService` reads `docs/*.md` and `.claude/rules/*.md` **at
runtime** to serve the in-app viewer and the settings help text. Excluding them would have
produced an empty documentation viewer with no error anywhere: nothing raises, the
catalogue simply resolves to missing files. It was caught before building only because the
exclusion list was checked against what the application reads rather than against a
best-practices list. The smoke job now asserts every catalogued document is present in the
image, so the near-miss became a test.

**Three CI defects that only appeared by running the job.** The `docker-smoke` YAML was
reviewed, parsed, and reasoned about, and it was still wrong three ways. `JWT_SECRET_KEY`
in the shared `env:` block is 22 characters and `APP_ENV=production` requires 32 — no Python
suite catches this because none of them run in production mode, so the container was the
first thing that ever did. `HEALTHCHECK` hardcoded port 5000 while `SERVER_PORT` was now
configurable, so Docker reported the container unhealthy while it served correctly on 5050.
And the job has no `setup-python` step, so bare `python` on the runner was not safe to
assume. Each would have been a red first run; none was visible in the file.

Fixing the second one improved the assertion that found it: because the healthcheck now
routes through `docker-entrypoint.py --healthcheck`, "Docker reports the container healthy"
also proves the check follows `SERVER_PORT`. The weaker "still running" step was replaced.

**What the migration actually bought, measured rather than claimed.** Same requirements,
same source, only the base differing: 121 CVEs to 20, criticals 2 to 0, highs 32 to 4, 73
fewer packages. The freshly rebuilt slim image scores identically to the published one,
which is what rules out the dependency pinning as the cause. What it did *not* buy: size
(10.2 GB to 10.1 GB — the base is noise beside torch and CUDA), and not "zero CVE" either,
since the hardened base's *own* Python packages carry three Highs that Debian slim does not.
The honest case is structural — no shell, no package manager, nonroot by default — and
that is what [ADR-3](ADR.md) records, with a revisit condition that can be re-measured
rather than re-argued.

**Rule taken from this:** a CI job is not verified by reading it. Run it, against the real
thing, before trusting it to gate anything — the same discipline Ch. 13 applied to tests
that pass with authentication broken, turned on the pipeline itself.

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
- **A test that covers the unit can still miss the behavior.** Chapter 8's
  coverage-percentage failure and Chapter 10's hybrid-search regression are
  the same gap at different scales: `_merge_semantic_and_lexical` had a
  passing, specific test, and the pipeline-level filter that undid its
  result three lines later had none. Coverage answers "did this line run,"
  never "was the outcome correct" — only an assertion on the actual output
  answers that.
- **A shipped fix is a new claim, not a closed question.** Chapter 10's
  hybrid-search regression was found by re-deriving the fix's own math, not
  by trusting that "fixed and tested" meant done — the same discipline
  Chapter 9 applied to the audit's findings, turned on this session's own
  output. Chapter 16 is that shape against an automated grader: two correct
  fixes, both alerts still open, because neither changed the expression the
  rule actually named.
- **The unit of change must match the unit of correctness.** Chapter 11's
  `codeql-action` split is the sharpest instance: three separately-correct
  PRs that were each individually broken, because the thing that had to be
  atomic was the set, not the member. Fixing the members (rebase, resolve,
  bump by hand) would have left the generator producing the same batch next
  week; changing what the generator emits was the only durable fix.
- **Configuration that is never exercised fails silently.** Chapter 11's
  doubled `refs/heads/` prefix rendered as correct in the UI that created
  it, and `dependabot.yml` requested three labels that had never existed.
  Neither surfaced as a failure — one produced an inert rule, the other a
  comment nobody read. Config is only verified by reading back the stored
  state, or by watching it actually do its job.

### What each pattern produced

The mechanism column is the point: a pattern that recurred and produced
only a resolution is one that will recur again. Rows without a durable
guard are marked as such honestly.

| Pattern | What was done | What now prevents recurrence |
|---|---|---|
| Prove it small, then repeat mechanically (Ch. 3, 6) | Clark-Wilson applied to `documents` first, then the other eight CDIs | Migrations `0005`–`0011` follow the proven shape; `plugins.md` requires the echo plugin to prove a capability before a domain plugin uses it |
| A roadmap is a checkpoint, not a contract (Ch. 3) | v1.0 → v1.0.1 and v2.0 → v3.0 replaced "complete" roadmaps mid-session | `ROADMAP.md` carries its own predecessor note; roadmaps are read as of-this-commit |
| Docs lag code silently (Ch. 5, 8) | ~17 drift items fixed in an explicit audit | `src/docs/service.py` renders the same markdown the humans read, so settings help text and docs cannot diverge |
| A proxy metric replaces the goal (Ch. 3, 8) | Mutation testing found 5 modules with executing-but-unverifying tests; fixed in `613d7ab` | `.claude/rules/testing.md` assertion-strength checklist, written against the four observed root-cause shapes |
| Security fixes cite a specific finding (Ch. 7) | Every hardening commit names the CWE, tool, or log line | Convention holds because it is what makes a fix verifiable afterwards — no automated guard |
| An external finding is a hypothesis (Ch. 9) | Audit triaged into four buckets; each finding re-derived from current code | Re-derivation is the standing rule; one false positive (`APP_ENV`) is the worked example |
| A default is not a decision (Ch. 9) | Tombstone accumulation fixed by deciding soft-delete-old vs. update-in-place | Clark-Wilson section of `CLAUDE.md` makes the delete semantics an explicit design question |
| A test can cover the unit and miss the behavior (Ch. 8, 10) | `ce2e4ee` decoupled survival from ranking; regression test added at pipeline level | Assertion-strength checklist; coverage is treated as necessary, never sufficient |
| A shipped fix is a new claim (Ch. 10) | Independent re-review of `08237a9` found the fix numerically dead | Follow-up review of the fix itself, not just the original bug |
| The unit of change ≠ the unit of correctness (Ch. 11) | `222788d` bumped all three `codeql-action` steps atomically | `532fd28` added `groups:` to `dependabot.yml` — the generator no longer emits splittable sets |
| Config that never runs fails silently (Ch. 11) | Created the three missing labels; corrected the doubled ruleset prefix | Ruleset verified by reading it back through the API, not by trusting the UI's rendering |
| A limit hides what it suppresses (Ch. 11) | Grouping freed nine of ten PR slots, surfacing a `thinc` major bump behind CUDA noise | `tests.yml` reports full version drift on every run, majors called out separately — visibility no longer depends on a PR existing. `minor`/`patch` are grouped so the limit stops binding |
| Merges are not gated on CI (Ch. 11) | Every merge that day was verified by hand before merging | Ruleset requires `unit-tests`, `integration-tests`, `repo-hygiene` on the default branch. Auto-merge stays off deliberately — the gate proves the tests ran, a human still decides |
| A rationale has a shelf life (Ch. 11) | The lock file's justification was false within days of being written, while the file still looked reasonable | Asking why an artifact exists is a periodic check, not a one-off; `CLAUDE.md` records the *reason* a rule exists so a stale one is recognisable |
| An absent signal reads as a negative one (Ch. 12) | A disabled logger, a PR whose CI never fired, and a suite that bypassed every auth check all presented as "fine" | `migrations/env.py` keeps its loggers and `_preserve_root_logging()` keeps root's level (both pinned by tests); `CLAUDE.md` records that a non-`main` PR runs no CI. The general case has no automated guard — the standing rule is to make the system emit the signal, not to reason about what it would emit |
| A green signal that predates the change (Ch. 13) | A suite started before the fix, a build that never ran, a PR whose CI never fired — three times, all indistinguishable from success | Each needs its own second question: how many tests ran, when the container started, which checks are listed. `CLAUDE.md` records the non-`main` PR case; the others have no automated guard and rely on naming the expected value before looking |
| Authorisation without authentication (Ch. 13) | 82 routes were guarded while no login route existed — the system was theoretical and looked complete only because most routes were open | `docs/AUTH_PLAN.md` sequences login before enforcement work; SEC-1 and TQ-1 are marked blocked on it rather than silently reordered |
| Tests answer the question you wrote down (Ch. 13) | 2545 passing tests missed four defects the owner found in two messages, including a cross-workspace read — nobody had constructed a viewer and looked at the screen | No automated guard, and probably none possible: the standing rule is that a feature is not done until someone has used it as the role it was built for. TQ-4's Playwright smoke test is the nearest mechanical approximation |
| A machine wearing a person's schema (Ch. 13) | A chatbot bridge had to log in as a user — no reset path, a session that expires mid-conversation, an audit trail naming someone asleep | Workspace API keys: the credential belongs to the workspace, so there is no password to reset and the log names the key. `WORKSPACE_API_KEYS.md` |
| Verifying a proxy instead of the thing (Ch. 12) | The logging fix was called complete when *some* lines returned; the app's own INFO was still being dropped, and it took a second pass (#225) to notice | The verification has to name the specific line expected, not "logs are back". `TROUBLESHOOTING.md` splits the symptom into the two halves so the wrong one cannot be matched by accident |
| Inspection yields a plausible story; execution yields the true one (Ch. 12) | BUG-3 severity was mis-ranked from reading code — probing showed 200s where 500s were assumed, and vice versa; the migration looked correct and had never run | `docs/MIGRATIONS.md` now requires `alembic heads` / `upgrade` / `current` against a real database before trusting a new revision. No CI job runs migrations, so this stays manual and explicit |
| A stale index becomes an authority (Ch. 12) | A migration was numbered from `file-map.md` while that table was missing two existing migrations, producing a duplicate revision id | `MIGRATIONS.md` states the directory is the only authority for revision numbers; `file-map.md` is a convenience index and is documented as such |
| Coverage without authorisation (Ch. 12) | Every route test ran with `state.testing = True`, tripping the RBAC bypass — the checks were executed by nothing | New auth tests run with the bypass **off**; RBAC-2 must verify each route has a check *and* a test that exercises it unbypassed |
| A dead abstraction is worse than none (Ch. 12) | `require_workspace_role_dep` was correct and had zero call sites while the routes it was written for ran their own fail-open checks | The dependency is now the single mechanism behind `check_workspace_access`, used by all 33 workspace-scoped routes — no parallel implementation to drift from |
| A fix is not a closed alert (Ch. 16) | #284 changed the flagged expression itself, and hardened the one shared `sanitize_log_value` instead of the copy CodeQL happened to point at | Re-run the scan rather than predicting it. Six sites now share one sanitiser, so there is no duplicate left to fix in isolation |
| A build that succeeds is not an image that runs (Ch. 17) | `docker-smoke` builds the image, asserts uid/shell/native-import/docs invariants, and boots it against postgres | Required check on every PR. The failure it targets — a missing native library becoming SIGSEGV with no traceback — is invisible to `docker build` |
