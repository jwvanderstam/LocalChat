# Lessons Learned

Why LocalChat's architecture and process are the way they are, in the order it was learned.
Built from `git log` and [`docs/ROADMAP.md`](../ROADMAP.md); each chapter cites the commits
or PRs it rests on. `git log` is the changelog; this is the reasoning.

Chapter length is not weight. The early chapters were reconstructed from commit history; the
later ones were written days after the events. The restructure in Chapter 1 and the soft-delete
pattern in Chapter 6 shaped more of this codebase than most of what follows.

---

## 1. Scaffolding, corrected in week one

After three "initial commit"s (2025-12-28), `12fb662` (2026-01-03) moved 45 files into the
`src/`-rooted layout the project still uses.

**Lesson:** fix the foundation before feature weight makes it expensive.

## 2. The RAG pipeline takes shape

`1c1520e` made chunking preserve table structure; `940a6f1` added the `metadata` JSONB
column and GIN index behind citations. Documentation was written alongside the features
(`739d264`), a habit that later drifted (Chapter 8).

## 3. v1.0, and the roadmap reset that followed it

`8a1e323` declared the v1.0.0 roadmap complete, deferring two items with reasons. Days later
`636ec07` replaced it with an agentic roadmap: planning, GraphRAG, MCP, routing, memory,
connectors.

**Lesson:** a version number is a checkpoint, not a finish line. Read a roadmap as "the plan
as of this commit".

## 4. The agentic layer, one feature at a time

GraphRAG, the MCP split with a circuit breaker per server, the aggregator, the model router,
the feedback loop, workspaces and connectors landed between 04-08 and 04-10 (`72e8490` to
`442de3f`). Each was small and verified on its own.

**Lesson:** every new capability shipped disabled by default and degraded when its dependency
was missing, so none of it risked the RAG path that already worked.

## 5. The FastAPI migration was not done when Flask left the imports

`068e561` still split a 618-line "Flask app" factory, and `architecture.md` was referenced
before it was ever committed (`65a536b`, three weeks later). Two coupling fixes (`42a0bbd`,
`7b4408c`) were needed before the migration could be called complete.

**Lesson:** a migration is done when the coupling and the docs have caught up, not when the
old import disappears.

## 6. Clark-Wilson: soft delete as a rule, not a cleanup

`15a2949` made soft delete, the audit trail and the retire/purge split a written rule. The
rollout went pilot first: documents and chunks (`02ba040`), whose ids sit inside citations,
then conversations and users (`e01fa22`), then the other four (`a6705ac`).

**Lesson:** prove a cross-cutting rule on the riskiest case, then repeat it mechanically.

## 7. Security hardening against named findings

`8f1b2d4` replaced `pickle` in the L3 cache to close a deserialisation RCE and sanitised five
log sites; `ceb427b` stopped exception text reaching clients; `bf638dd` added gitleaks and
pip-audit and bound Postgres to loopback. `SECURITY.md` records an old leaked dev credential
openly instead of hiding it.

**Lesson:** each pass targeted a specific finding, which is what makes a fix verifiable
later.

## 8. Coverage and documentation, both trusted too long

Mutation testing found five modules whose tests ran code without checking it. Four of the
five origin commits were framed around a coverage target (`3d3453c`, `a69c977`, `f513073`,
`b11b4ea`); fixed in `613d7ab`, and the assertion-strength checklist in
`.claude/rules/testing.md` came from it. The same audit found about 17 places where the docs
had drifted from the code.

**Lesson:** a proxy, whether a percentage or a description, stays trusted after it stops
matching reality unless something re-checks it. `src/docs/service.py` now renders the help
text from the same markdown people read, so those two cannot diverge.

## 9. An external audit, triaged

The 2026-07 review was sorted into fix now, next, scheduled and parked. One line,
`UVICORN_WORKERS=1` (`a9d9ed4`), retired five findings with one root cause: per-process state.
Re-reading the code the "atomic ingest" ticket touched found a real bug the audit missed:
`document_exists()` ignored the workspace, so a same-named upload could hit another
workspace's document (`14cdfe4`). The same commit replaced an undecided soft-delete-and-insert,
which left a tombstone on every re-ingest, with an explicit update in place. One suspected
gap (`APP_ENV` missing in Helm) was disproved by running the image.

**Lesson:** an audit is a list of hypotheses. Re-derive each from the current code or the
running target; a plausible gap and a real one cost the same to verify.

## 10. A fix with a second bug, and a stopwatch

A follow-up review of the hybrid-search fix (`08237a9`) found it could never let a
lexical-only chunk through at the shipped defaults, and that it diluted semantic results.
`ce2e4ee` decoupled survival from ranking. Its unit test had checked the merge, not the
filter three lines later. Separately, `/api/metrics.json` showed chat at 8.65 s: `num_ctx` was
being sent a *character* limit, three times the intended context (`771d420`; 1.15 s after).

**Lesson:** a fix is a claim. Close it by observing the running system.

## 11. Sixteen dependency PRs, and the unit of change

Dependabot split one `codeql-action` upgrade across three PRs, each broken alone; `222788d`
moved them together, and `532fd28` added `groups:` so sets always move as one. The ruleset's
`non_fast_forward` blocked Dependabot's own rebases, and the UI stored the exclusion as
`refs/heads/refs/heads/...`, a pattern only the API showed. Grouping freed PR slots and
surfaced ten suppressed updates, a `thinc` major among them. The same day the hand-made
lock file was deleted (`ff73d3c`): nothing installed it, and its rationale was already false.
Required status checks were added to the ruleset, scoped to the default branch.

**Lesson:** the unit a tool changes must match the unit that has to be correct. And a
rationale has a shelf life; re-ask why an artifact exists.

## 12. RBAC-1, and two defects that hid each other

A correct workspace-role dependency already existed with zero call sites, while the routes
it was written for ran fail-open checks of their own and two `/members` routes ran none.
Probing showed the fail-open routes answered 500, masked by a second bug. No test saw any of
it, because the suite ran with an authorisation bypass. A backfill migration numbered from a
stale `file-map.md` collided with `0012`. And `migrations/env.py`'s `fileConfig` had disabled
every application logger, hiding the `MultipleHeads` error raised on every boot. The first
logging fix restored only `ERROR`s; #225 restored root's level too.

**Lesson:** an absent signal reads exactly like a negative one. Make the system produce the
signal: probe the route, run the migration, read the check list.

## 13. Authorisation without authentication

82 guarded routes, and no login route: nothing had ever issued a token. AUTH-1, AUTH-2,
workspace API keys and SEC-1 (`DEMO_MODE` deleted) followed. Three green signals were empty:
a test run started before the fix, `docker compose up --build` silently serving an old
container, and a stacked PR whose CI never ran. Then the owner used the app and found four
defects that 2,545 passing tests had not, one of them a viewer reading another workspace's
documents.

**Lesson:** name the specific thing expected (this log line, this start time, this row
count), and use the feature as the role it is for.

## 14. The fix was one layer too high

Scoping `/api/workspaces` did not help an editor whose browser still held an admin's
workspace in `localStorage`. The stored choice now counts only while the server still offers
it, and sign-in clears it. `test_frontend_workspace_selection.py` runs the real JavaScript
under node; 5 of its 7 tests fail with the fix reverted.

**Lesson:** when a fix changes what the server sends, check what the client keeps.

## 15. The bypass nobody used, that everything depended on

Deleting `app.state.testing` (TQ-1b) broke 290 tests in 30 files, 17 of which never named
the flag: a `MagicMock` state returned a truthy `testing`. The first converted file was green
and authenticated nothing. Deleting first and repairing after worked; breaking token
verification then turned 95 of 148 tests red, which proved they test authentication.

**Lesson:** count what a mechanism reaches, not who names it. A default is used by everything
that never mentions it.

## 16. Two fixes that closed no alert

#283 improved two sites CodeQL flagged, and both alerts stayed open: the rules matched
expressions the fixes never touched. The CR/LF-only sanitiser still let a value split into
seven lines. The real finding was a weak `sanitize_log_value` copied to six sites (#284). The
route test passed with or without the fix.

**Lesson:** an alert closes when the named expression changes, confirmed by re-running the
scan. Run the attack before calling a fix sufficient.

## 17. A missing library that fails as SIGSEGV

Moving to the hardened distroless base removed the shell, the package manager and the named
user, so the entrypoint now expands the port and worker settings itself. `onnxruntime` 1.29.0,
reached transitively and unpinned, built fine and died with exit 139 on the new base; it is
pinned as a workaround, cause unknown. A `.dockerignore` from generic advice would have
removed the docs the app reads at runtime. `docker-smoke` failed three ways on its first real
run. Measured gain: 121 CVEs down to 20 ([ADR-3](../ADR.md)).

**Lesson:** a CI job is verified by running it against the real thing, not by reading it.

## 18. A deletion ticket that was wrong about what it deleted

DEL-1b's own exemption applied to two of its four connectors, and its inventory missed three
sites. Keeping SharePoint exposed a live defect: connectors spent the OAuth token of whatever
`user_id` the config named. The fix made the owner a column (`connectors.created_by`).
SonarCloud, not required, caught duplicated guards and dead code. PERF-2's benchmark had been
measuring the rate limiter (190 of 200 requests returned 429), and the canary had once passed
on a single probe.

**Lesson:** before executing a plan, re-ask the question it answered.

## 19. A recommendation that became a production bypass

`DEMO_MODE` (`e89f998`) implemented a review's suggestion two days after it was made. It was
asked to limit reachability and instead switched off authorisation, and the "suppresses web
search" half was only ever a comment. Its boot warning was accurate and reached no one who
copies an `.env` to a server. SEC-1 deleted it, and a test keeps it gone.

**Lesson:** before relaxing a control, name the layer it acts on: reachability,
authentication or authorisation.

## 20. Every route had a guard, and a green check said so

v3.0.0 shipped with every route guarded. Sixteen days later an audit cleared every document
in the installation as a plain user (C1). The guard checked a role in *a* workspace; the query
acted on the object wherever it lived. `workspace_id=None` meant "everything", and it produced
three of the four criticals. The fix made a scope a value (`src/utils/scope.py`): a workspace
or `ALL_WORKSPACES`, never `None`, with an AST test that fails on any call omitting `scope=`.
Two highs were documentation that had run ahead of the code.

**Lesson:** a guard proves the caller may act, not that the object is theirs. Test role ×
route × foreign object, and make the widest grant something that must be written down.

## 21. Isolation that every test passed while it did nothing

Row-level security does not bind a superuser or a table's owner, and compose and every test
connected as `postgres`. A `localchat_scoped` role and migration 0018 fixed that. The RLS suite
would have skipped in CI, reading as a pass, so it migrates its own database. Making the scope
mandatory found three more unauthorised reads (#405). The aggregator lost the request scope in
its thread pool and failed closed, silently (#409). Filtered HNSW returned 19 of 40 rows until
iterative scan restored them. And on managed Postgres the role grant failed, because the tests'
identity was not production's (#430).

**Lesson:** test a control as the identity production uses, and make a missing precondition
fail rather than skip.

## 22. Every ranking metric measured the alphabet

`retrieve_context` returns results in reading order, and every eval script read that order as
rank (#410, #423). The DEL-2 decisions were re-run by relevance (#425): GraphRAG still changed
nothing; the reranker lifted neither corpus, which was recorded and not acted on. A local
`app_state.json` had also leaked into one baseline and one comparison path.

**Lesson:** a harness is code under test, and its bugs look like plausible numbers. Check a
metric on a case whose answer is known, and fix sibling scripts the same day.

## 23. A gate that could not go red

EV-1 was proven by zeroing the lexical arm, and it stayed green. The arm's `plainto_tsquery`
ANDed every word, stop words included, and matched 1 of 20 questions. Hybrid search had been
semantic search. ORing content words (#422) made it fire on 105 of 105, and the same mutation
then turned the gate red.

**Lesson:** prove a gate by breaking what it guards. When the proof fails, suspect the product
first.

## 24. The documentation audit after the documentation tests

P2-7's test checks that every path and endpoint a document names exists. A full audit three
days later still found the rules files sending schema changes to the wrong place, an
app-creation example using a deleted bypass, the wrong required-check count, a quick start
with no embedding model, and a SCHEMA.md missing row-level security.

**Lesson:** a reference test checks that a name exists, not that a sentence is true. Audit
the instruction files hardest; they are acted on without being questioned.

## 25. The refactor, and the review after it

The October 2026 plan moved routes onto services (QP-4) and made every database path name its
scope (QP-5), and a separate agent session then reviewed the result (QP-9).

- **QP-4 moved the layering, not the scoping.** Its checklist never listed the second job, so
  47 repository methods still ran on the transition policy when QP-5 began. ADR-5 records the
  correction.
- **With scoping finished, the review's two High findings were both `ALL_WORKSPACES` paths a
  workspace user could reach.** Document statistics sampled every workspace's chunks (R-1).
  A connector's delete event retired a filename everywhere (R-2). The explicit flag made each
  bypass visible in the code; it did not make it right.
- **The authorisation matrix tested as an editor only.** Owner-guarded routes refused the
  editor on role before scope was ever checked, which hid R-7. It now runs as an owner too,
  and probes ids in bodies and headers, which found the active-workspace leak (#510).
- **Two silent fallbacks.** A Dependabot bump of the `pymupdf4llm` shim dropped `pymupdf`
  from the lock, and PDF loading fell back to pdfplumber with every check green;
  `docker-smoke` now asserts the module. The mutation gate filed a mutant that broke test
  collection as a survivor; the runner now reports any failure as a kill.

**Lesson:** an explicit escape hatch still needs a reason per use. And test a guard with the
role that gets past it, or you test only the role check.

---

## Patterns, and what guards against each

| Pattern | Chapters | What prevents recurrence |
|---|---|---|
| Prove it small, then repeat | 4, 6 | Migrations `0005`–`0011` follow the CW-1 shape; `plugins.md` requires the echo plugin before a domain plugin |
| A roadmap is a checkpoint | 3 | Roadmaps are read as of their commit; ROADMAP carries its predecessor note |
| Docs lag code | 5, 8, 24 | `src/docs/service.py` renders the docs people read; `test_docs_reference_what_exists.py` checks names. No guard for a false sentence |
| A proxy metric replaces the goal | 8 | The assertion-strength checklist; the nightly mutation gate |
| An external finding is a hypothesis | 9, 19 | Re-derive from current code before acting. No automated guard |
| A default is not a decision | 9 | Clark-Wilson rules make delete semantics an explicit choice |
| A test covers the unit, misses the behaviour | 10, 23 | Pipeline-level tests; `retrieval-gate` (required) scores real questions |
| The unit of change ≠ the unit of correctness | 11 | Dependabot `groups:` |
| Config that never runs fails silently | 11 | Read the ruleset back through the API |
| A rationale has a shelf life | 11, 18 | CLAUDE.md records why each rule exists. No automated guard |
| An absent signal reads as a negative one | 12, 13, 21 | Loggers pinned by tests; non-`main` PRs flagged in CLAUDE.md; a missing precondition fails |
| A stale index becomes an authority | 12 | `MIGRATIONS.md`: the directory is the only authority for revision numbers |
| Migrations that never ran | 12 | `test_migrations_apply.py` applies the chain in CI; `restore-proof` round-trips the schema |
| Coverage without authorisation | 12, 15 | The bypass is deleted (TQ-1b); tests authenticate through `tests/utils/auth.py` |
| Use it as the role it is for | 13, 14 | Eight browser paths in `e2e` (required); the node harness for frontend branches |
| A fix is not a closed alert | 16 | Re-run the scan; one shared sanitiser |
| A build that succeeds is not an image that runs | 17 | `docker-smoke` (required) |
| A plan is not evidence | 18 | Re-derive a ticket's premise before executing it. No automated guard |
| A guard is not ownership | 20, 25 | `scope=` is mandatory, checked by AST; the wire matrix runs as editor and owner with foreign objects |
| A control tested as the wrong identity | 21, 25 | RLS tested as `localchat_scoped`; requests run as `localchat_app` |
| The measuring instrument is code under test | 22, 25 | Rank is relevance, asserted; the mutation runner reports collection errors as kills |
| A detector that cannot see a mutation | 23 | Every gate is proven by breaking what it guards |
| An escape hatch without a reason | 25 | `ALL_WORKSPACES` uses are reviewed; the per-use ratchet is QP-10 (R-5b) |
