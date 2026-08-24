# PRODUCTION_PLAN — hardening LocalChat to a defensible production claim

> **Provenance:** written in the 2026-08-04 external code-audit session; reconstructed and committed 2026-08-05.
> The ADR-1 decision line and the TQ-1/TQ-2 ticket bodies were re-derived from the session's prose plan; all
> other sections are recovered verbatim. All code-level claims re-verified against `main` @ `7679939`
> (2026-08-05): `_is_rbac_bypassed()` fail-open on empty `ADMIN_PASSWORD` / `DEMO_MODE`, the
> `app.state.testing` bypass, and `_verify_jti_not_revoked()`'s silent no-op on DB unavailability are all
> still present.
>
> **Position in the plan of record:** runs after ROADMAP Sprint 6b. ROADMAP Sprints 8–12 (GKB, PC, PR-1)
> queue behind the Exit Criteria at the bottom of this document.

---

## Phase 0 — The governing decision (Sprint PG-0, before any code)

### ADR-1 — Single-node appliance scope ✅ (recorded in [ADR.md](ADR.md))

**Decision:** LocalChat v3.0 is a single-node, self-hosted RAG appliance for a small team (≤ 25 users).
Multi-tenant SaaS and horizontal scaling are explicitly out of scope.

This is the decision the codebase has been avoiding. The Helm chart, distributed cache backends and JWT/RBAC layers imply multi-replica scale; module-level TTL caches, the per-process admin salt and in-memory rate limiting assume one process. Run two replicas today and cache coherence and rate limits silently break. Choosing single-node makes the in-process state model *legitimate architecture* instead of a latent bug, and deletes months of solo work (Redis-mandatory state, sticky-session SSE, distributed rate limiting) that no actual deployment needs.

**Consequences:**
- Helm chart: downgrade to "single-replica only, experimental" in its README, or delete in favour of docker-compose. Decide during PG-1; deletion is the default unless a concrete k8s deployment exists.
- README first line changes from "production-ready" to "production-patterned, hardening toward v3.0" until the Exit Criteria pass. The claim and the code must match; today they don't.
- Wiki Home and README must state the *same* product. Currently the wiki says "learning journey / reference implementation" and the README says "production-ready" — two products, two obligation levels. The honest position is both: a learning-driven project being hardened to a defensible production claim, for a defined scope.

### ADR-2 — No async database rewrite ✅ (recorded in [ADR.md](ADR.md))

**Decision:** the sync psycopg pool stays. Blocking work is offloaded to the threadpool (PERF-1); async psycopg / asyncpg is **rejected**, not deferred.

This ratifies and strengthens the existing HK-10 deferral ("deliberately deferred — see its ticket for the scale trigger"). At ≤ 25 users the threadpool is the correct production answer, and with ADR-1 in force the scale trigger can no longer fire. Recording it as an ADR stops the question from being re-litigated every time the async-purity itch returns.

---

## Phase 1 — Safe and correct (Sprints PG-1..PG-2)

Order matters: safety before performance, because the auth fixes change what the tests must assert. BUG-3 (Sprint 5b) and RBAC-1 (Sprint 6) land first per the existing ROADMAP; nothing here duplicates them.

### SEC-1 — Delete every authorisation bypass; seed a dev admin instead ✅ (done)

> **Unblocked and largely done (2026-08-07).** AUTH-1 added the login route, so the bypasses
> could go. `DEMO_MODE` is deleted outright — constant, branch, status payload, compose,
> Dockerfile, `.env.example`, and the stale comment claiming it suppressed web search, which
> no code ever did. The `not _ADMIN_PASSWORD_RAW` branch is gone too, because an admin is now
> always seeded, so an empty password no longer means "no way in".
>
> Seed-and-start is implemented as decided: outside production an unset `ADMIN_PASSWORD`
> generates one and logs it once, guarded on `APP_ENV` rather than on the password being
> empty, and seeding only when the account does not exist so a restart cannot reset a real
> password.
>
> **Remaining:** `app.state.testing`, which 23 call sites across 17 test files depend on.
> That is TQ-1's job — it deletes the bypass *and* supplies the authz-by-default CI job that
> makes the rewritten tests worth having. `_is_rbac_bypassed()` now has exactly one branch
> left; when TQ-1 lands it has none and the function goes.

> **Rewritten 2026-08-05** after checking the code the original ticket described, and after
> the owner chose the dev-seed approach over the loopback-binding one it proposed.

**Correction first: the production half is already done.** The ticket asked to "extend the
existing startup secrets validation so `APP_ENV=production` with an empty `ADMIN_PASSWORD`
refuses to start". `validate_secrets()` (`config.py:112-143`) already appends
`"ADMIN_PASSWORD must be set in production"` and raises `SystemExit(1)`, and it is called
from `create_app()` (`app_fastapi.py:32`). **Production cannot boot without an admin
password today.** No work remains there.

**What actually remains is that development runs with authorisation switched off**, through
three separate mechanisms, and that is why defects in this exact subsystem keep reaching
`main`. `_is_rbac_bypassed()` returns True when *any* of these hold:

| Bypass | Reachable in production? | Dies in |
|---|---|---|
| `not _ADMIN_PASSWORD_RAW` | No — `validate_secrets()` blocks the boot | SEC-1 |
| `config.DEMO_MODE` | Yes, if someone sets it | SEC-1 |
| `_is_testing(request)` (`app.state.testing`) | No — test-only flag | TQ-1 |

When all three are gone, `_is_rbac_bypassed()` has no remaining branch and the function
itself is deleted. That is the goal: **not a safer bypass, no bypass.**

**The approach: seed, don't bypass.**

- Delete `DEMO_MODE` entirely — config constant, `_is_rbac_bypassed()` branch, the
  `get_current_user_id()` early return (`security_fastapi.py:140`), the `demo_mode` field in
  the status payload (`settings_routes.py:108`), the `.env.example`/compose/Dockerfile entries,
  and the stale comment at `config.py:520` claiming it "suppresses web search" — **there is no
  such code**; `web_search.py` has never referenced it.
- Outside production, when the user table is empty, seed one admin account with a known
  password and log the credentials once at startup. The developer logs in **through the real
  login form**, against the real JWT issuance, and every subsequent request carries a real
  token.
- Remove the `not _ADMIN_PASSWORD_RAW` branch. With a seed, there is always an account.

> **Explicitly rejected: auto-login.** An earlier phrasing of this ticket said the UI would
> "log itself in locally". That is the same defect wearing a different hat — a code path that
> behaves differently in dev than in production, which is precisely what let BUG-3, the
> fail-open membership checks and the 49 unguarded routes stay invisible. The cost of the
> honest version is one login per session. The benefit is that a local instance behaves
> **identically** to production, so an authorisation defect shows up while you are working
> rather than during an audit.

**Decided 2026-08-05 — seed and start.** Outside production with an empty `ADMIN_PASSWORD`,
generate a random password, create the admin, and log the credentials once at startup. A fresh
clone still comes up with `docker compose up` and no `.env` edit, and it comes up with
authorisation **on** rather than off — which is the whole point of the change.

Two consequences to handle in the implementation, both of which make the difference between
this being a convenience and being a new hole:

- The generated password is in the startup log. That is acceptable on a local box and not
  acceptable anywhere else, so the seed must refuse to run when `APP_ENV=production` — the
  guard is the environment, not the emptiness of `ADMIN_PASSWORD`.
- Re-running must be inert. Seed only when the user table is empty; never reset an existing
  account's password, or a restart silently hands out a known credential for a real user.

Rejected alternative: refusing to start outside production too. One rule everywhere is tidier,
but it turns a fresh clone into a `.env`-editing exercise before anything runs, and the getting-
started friction buys nothing — a local instance with a seeded admin is already authorised.

**Files:** `src/config.py`, `src/security_fastapi.py`, `src/routes_fastapi/settings_routes.py`,
`src/db/users.py` (seed), `src/app_bootstrap.py` (call the seed), `.env.example`,
`docker-compose.yml`, `Dockerfile`, `docs/DEPLOYMENT.md`.

**Tests required:**
- `_is_rbac_bypassed` no longer exists, or returns False for every input — assert the absence
- a guarded route returns 401 unauthenticated with `DEMO_MODE=true` still set in the
  environment, proving the variable is inert rather than merely undocumented
- the seed creates exactly one admin when the user table is empty, and **does nothing** when it
  is not (re-running must never reset a real password)
- the seed does not run when `APP_ENV=production`
- a token issued after logging in as the seeded admin passes `require_admin_dep`

**Acceptance:** delete the `state.testing = True` line from one existing route test and confirm
it now fails with 401 rather than passing. That is the property being bought: tests can no
longer pass through checks that never ran.

### SEC-2 — Token revocation fails closed ✅ (done)

`_verify_jti_not_revoked()` swallowed DB errors and let the request through ("fail open rather than locking out users"). For a production claim, revocation that is advisory is not revocation. Now fail-closed, with a 60-second in-process cache of successful checks so a DB blip degrades to slightly-stale-but-enforced rather than to open. Single-node (ADR-1) makes the in-process cache correct.

> **The trade was smaller than it looked.** Failing open was justified as avoiding a lockout, but it prevented nothing: every workspace-scoped route already answers 503 without a database, so the application is unusable in that state either way. What it did buy was a window in which a token revoked minutes earlier was accepted again. Checked before implementing rather than assumed.
>
> The cache is a fallback for outages, never a shortcut past a working check — a live `is_token_revoked` still wins over a warm entry, and a refusal is never cached as usable. It is bounded (4096 entries, stale-first eviction) so a stream of distinct tokens cannot turn it into a leak.

### SEC-3 — Rate limiting keys on the real client, and covers more than login ✅ (done)

Found by the 2026-08-19 external audit, which reported the first defect; verifying it turned up two more in the same control.

`Limiter` was keyed with `get_remote_address`, which reads `request.client.host`, and nothing anywhere trusted a proxy header — no `ProxyHeadersMiddleware`, no `--forwarded-allow-ips`. Under `docker-compose.nginx.yml` — the deployment `DEPLOYMENT.md` documents — nginx is a **separate container**, so its peer address is a bridge IP and uvicorn's `127.0.0.1` default never matched. `X-Forwarded-For` was set by nginx and discarded by the app. Every caller keyed on the nginx container.

That inverts the guarantee `config.py` claims for `RATELIMIT_LOGIN` in a comment two lines above it — *"Per source address, so one attacker cannot lock out a legitimate user by exhausting a shared budget."* It was a shared budget, and exhausting it was exactly how one attacker locked out everyone.

**Also fixed, found while confirming the above:**
- `RATELIMIT_STORAGE_URI` was computed in `config.py` and never passed to `Limiter()`, so the limiter kept private in-process counters and the configured Redis was never touched — and CI's Redis service comment claimed the opposite.
- `RATELIMIT_CHAT`, `RATELIMIT_UPLOAD`, `RATELIMIT_MODELS` and `RATELIMIT_GENERAL` decorated **zero** routes. `/auth/login` was the only limited endpoint in the application. Config that reads as a control and enforces nothing is worse than no config, because it answers the question when someone checks.

**Files:** `src/config.py` (`TRUSTED_PROXY_IPS`), `src/security_fastapi.py` (`storage_uri`, `default_limits`), `src/app_fastapi.py` (`_init_security`), `api_routes.py`/`document_routes.py`/`model_routes.py` (decorators), `docker-compose.nginx.yml`, `docker-entrypoint.py`, `app.py`.

**Tests:** `tests/unit/test_sec3_rate_limit_keying.py`.

> **`TRUSTED_PROXY_IPS` defaults to empty, and that is the point.** Believing `X-Forwarded-For` from an untrusted peer is the mirror-image defect — any caller forges its own bucket — so the default trusts nobody and the nginx overlay opts in. The tests assert both directions, and the two guarding the fix go red when it is reverted while the two guarding against over-correction stay green.
>
> **One place decides proxy trust.** Uvicorn ships its own answer (`--forwarded-allow-ips`, default `127.0.0.1`), and two mechanisms disagreeing is what let the header be silently dropped here. It is now started with that flag empty, so `config.py` is the only authority.
>
> **The limiter is disabled under test, deliberately.** slowapi's decorator evaluates limits from the `Limiter` object, not from `app.state.limiter` — which `_init_security` was already skipping when testing. Limits were therefore enforced in the suite with no handler registered to turn them into a 429. Nothing noticed only because login was the sole decorated route; adding chat and upload, which the suite hits ~120 times, would have surfaced as unexplained exceptions.
### SEC-4 — Enforce ENCRYPTION_KEY; drop the encryption that did nothing ✅ (done)

From the 2026-08-19 external audit. `validate_secrets()` aborted production startup on a weak `SECRET_KEY`, `JWT_SECRET_KEY`, `ADMIN_PASSWORD` or wildcard CORS, but never mentioned `ENCRYPTION_KEY` — so a deployment could run indefinitely with OAuth tokens, message content and long-term memories in plain text in Postgres. The only signal was one `logger.warning` on the first `encrypt()` call, per worker. An *invalid* key was no different from an absent one: `_get_fernet()` returns `None` on the exception and `encrypt()` returns its input.

Now checked at boot alongside the other secrets, both for presence and for being Fernet-constructible.

**The audit stopped one step short, and the step matters.** Enforcing the key does not protect document text, and cannot. `documents.content` was passed through `encrypt()` on write and **never decrypted** — `src/db/documents.py` imported only `encrypt`, and nothing `SELECT`s that column. Meanwhile the same text, chunked, sat in plain text in `document_chunks.chunk_text`, which is what retrieval actually reads and sends to the model. Encrypting *that* is foreclosed: `chunk_tsv` is `GENERATED ALWAYS AS (to_tsvector('simple', chunk_text)) STORED`, so ciphertext tokenises to nothing and the lexical arm of hybrid search disappears.

So the encryption was cost with no confidentiality, plus a schema that read as though document content were protected. Removed, and the real limit is now written down (SECURITY.md §6) with disk-level encryption named as the actual control.

**Files:** `src/config.py` (`validate_secrets`), `src/db/documents.py`, `SECURITY.md`, `.env.example`, `docker-compose.yml`, `docs/DEPLOYMENT.md`, `docs/SCHEMA.md`.

**Tests:** `tests/unit/test_config_complete.py` (`TestValidateSecrets`), `tests/unit/test_db_operations.py`.

> **This is a breaking change for existing deployments.** `docker-compose.yml` sets `APP_ENV=production` by default, so `ENCRYPTION_KEY` is now required to start; compose fails fast with a named variable rather than booting a container that quietly stores plaintext. No data migration is needed — `decrypt()` already returns unrecognised values unchanged, so rows written before a key was set keep reading correctly while new writes are encrypted.

### PERF-1 — Unblock the event loop in `api_chat` ✅

`api_chat` is `async def` but inline-calls sync `chat.retrieve_contexts` (sync psycopg, sync httpx embedding call, cross-encoder inference) and sync `persist_user_message` / `persist_assistant_message`. One slow retrieval stalls **every** concurrent request, including SSE streams already mid-flight. The inference path is properly async (HK-8); retrieval never got the same treatment — the migration stopped halfway.

Fixed: `retrieve_contexts`, `retrieve_plan_and_memory`'s sync `MemoryRetriever.retrieve`, both persist calls and `update_chunk_stats` now run via `starlette.concurrency.run_in_threadpool`. The audit also moved the upload ingest and `api_test_retrieval` in `document_routes.py`. It found ~20 further async routes with an inline `db.` call, all single indexed writes of a few ms — left alone deliberately, since wrapping them tripled the diff for no measurable gain. Per ADR-2 this is the *final* fix. Measured before/after: see PERF-2.

### PERF-2 — Concurrency benchmark, committed to the repo ✅

`scripts/bench_concurrency.py`. Drives N concurrent SSE chat clients and reports p50/p95
time-to-first-token and total stream time — **plus a canary** that polls `/api/health`
every 100 ms throughout and reports how long that cheap call took.

**Measured, 5 concurrent clients / 10 requests, same corpus, one uvicorn worker:**

| | without PERF-1 | with PERF-1 |
|---|---|---|
| TTFT p50 / p95 | 4.33s / 9.19s | 3.91s / 8.82s |
| loop responsiveness p50 / p95 | 3ms / 6ms | 3ms / 5ms |
| **loop responsiveness max** | **848ms** | **305ms** |

**Two findings that change how this should be measured.**

*Chat latency cannot see this defect.* TTFT is dominated by the queue at Ollama, which
serialises generation regardless of the event loop. Three runs of the same build gave
p95 TTFT of 8.25s, 9.38s and 8.82s — the between-build difference is smaller than the
between-run spread, so any TTFT-based verdict here is noise. The canary is the metric
that discriminates: a request that should take milliseconds cannot hide a stalled loop.

*The win is in the tail, not the average.* p50/p95 were already healthy; only the worst
case moved. Retrieval on this corpus takes a few hundred ms, so the loop was held
briefly and rarely. The gap widens with a larger corpus, a slower reranker or more
clients — the fix is right, but the ticket's framing ("one slow retrieval stalls every
concurrent request") overstates the impact at current scale.

*Still open:* 305 ms of worst-case stall remains after the fix, so something in the chat
path still blocks. Not chased in this PR.

*CI wiring waits on TQ-2.* A `workflow_dispatch` job needs a live Ollama, which means a
multi-gigabyte model pull per run — slow, and flaky in a way that teaches people to
ignore the job. TQ-2's fake Ollama fixes that, and fixes it in the right direction: with
generation stubbed, TTFT becomes meaningless but **the canary stays valid**, so the one
metric that actually catches this class of regression is also the one that survives a
deterministic environment. Wire it there, with `--max-p95-ttft` replaced by a canary
budget.

> **The success criterion below should be restated.** "p95 time-to-first-token at 10
> concurrent users" measures Ollama's throughput, not the application's concurrency. The
> canary max is the number that would have caught PERF-1.

---

## Phase 2 — Prove behaviour, not coverage (Sprints PG-3..PG-5)

The mutation audit (`TEST_QUALITY_AUDIT.md`) already established internally what the external audit confirmed from the outside: coverage-driven sessions produced tests that run code without checking behaviour, and the whole suite runs with the RBAC bypass on — *coverage without authorisation*. So stop gating on coverage percentage and gate on behaviour.

### TQ-1a — Authz-by-default route introspection ✅ (done)

`tests/unit/test_authz_by_default.py` walks the route table of the real application and
asserts every route refuses an unauthenticated caller, unless it is on an explicit
allowlist carrying a reason. A new route added without a guard fails by default.

**It found a real gap on its first run.** `GET /api/settings/stats` served admin
statistics to anyone. RBAC-2's manual audit had recorded it as `admin` — a false
positive, because the classifier's 14-line window caught the `require_admin_dep` of the
*next* route. That is the case for introspection over counting: 102 routes read by hand
produce mistakes that a walk of the actual table does not.

Two traps this had to avoid, either of which yields a check that passes while verifying
nothing:

- **`app.routes` is not the route table.** This FastAPI version wraps includes in
  `_IncludedRouter`, so a naive walk finds four routes — the built-in docs pages — and
  pronounces the application clean. Paths come from `app.openapi()`.
- **`openapi()` omits `include_in_schema=False` routes.** Those are the eight SPA shells;
  they are enumerated separately and pinned as a set, so a new hidden route fails the
  test rather than slipping past the half of the check that cannot see it.

Placeholder values are type-correct (`int` where the route expects `int`), because a 422
from validation is neither a pass nor a refusal and would hide whether the route is
guarded at all.

**Verified by breaking it:** removing the guard from `POST /api/feedback` turns the check
red and names the route; restoring it turns it green.

### TQ-1b — Delete the `app.state.testing` bypass ✅

The last branch of `_is_rbac_bypassed()`. When it goes, the function has no branch left
and goes with it.

**Done 2026-08-11.** `_is_rbac_bypassed()` and `_is_testing()` are gone, with all five
of their branches. `TESTING` still disables rate limiting — a legitimate test concern —
but no longer touches authorisation, and `app.state.testing` is not written or read
anywhere.

**The count was measuring the wrong thing.** The ticket tracked explicit uses: 23 call
sites, then 39. The real dependency was **290 tests across 30 files**, and *17 of those
files never mentioned the flag*. They built an app with `app.state = MagicMock()`, and
`getattr(state, "testing", False)` reads truthy on a mock. Authorisation-off was not
something a test opted into — it was the default, and a test had to opt *out* to check
authorisation at all. That is the shape of the problem RBAC-2 and BUG-3 were symptoms of.

**Verified against the failure mode the ticket named** — "a test converted carelessly
gets quietly weaker rather than loudly red". The first conversion attempt passed while
authenticating nothing, because the `MagicMock` state kept the bypass alive. So the
order was inverted: delete the bypass first, then fix what falls over, which fails
loudly by construction. The finished conversion was then checked by sabotaging token
verification — 95 of 148 tests in the converted files go red, so they genuinely depend
on a valid token.

Three assertions changed meaning rather than being repaired, and all three were
recording the bypass instead of the rule: `deleted_by`, `owner_id` and
`create_workspace(owner_id=…)` now name the authenticated caller instead of `None`.
That is the Clark-Wilson audit trail working for the first time in the tests.

Also removed: 14 dead flag assignments and 7 `_rbac_on` fixtures that neutralised a
bypass SEC-1 had already deleted. `tests/utils/auth.py` holds the replacement, and
`TestNoBypassRemains` fails if `src/` ever consults a testing flag again.

### TQ-2 — Deterministic integration CI ✅

`tests/utils/fake_ollama.py` (the stub) and `tests/integration/test_ingest_ask_cite.py`
(the path). Ingest → chunk → embed over HTTP → pgvector → hybrid retrieval → rank →
cite → workspace isolation, all real except the model process. Runs in the existing
integration job; no GPU, no new service container.

**The embeddings are a bag of words, not noise.** With random vectors the harness would
"work" while making every ranking assertion arbitrary — the expected chunk would come
first by luck. Bag-of-words makes cosine similarity track word overlap, so the ordering
is a property of the retrieval code. `TestTheHarnessIsWhatIsUnderTest` guards that
property, because a stub that answers wrongly makes every test above it vacuous.

**It found two defects on its first real run**, both invisible while the layer above was
mocked:

- `processor.py` passed the *module-global* Ollama client to `BatchEmbeddingProcessor`
  instead of the injected one. A caller supplying a client got it for some calls and the
  global for the batch. Verified by restoring the bug: the whole file goes red.
- A database built by `_ensure_extensions_and_tables()` alone is missing every column
  added since — it failed on `document_chunks.deleted_at` from migration 0005.
  Production applies migrations at startup, so the test now does too. That closes
  TQ-5b's *premise* — a CI job now executes migrations against a real database — but
  not TQ-5b itself, whose head, idempotency and exit-status assertions came next.

Also recorded in TROUBLESHOOTING: on Windows, `PG_HOST=localhost` resolves to IPv6 while
Docker publishes on `127.0.0.1`, so every connection costs 5 s and the pool times out.

### TQ-3 — Mutation gate, scoped ruthlessly ✅ (done)

Nightly, core modules only: `security_fastapi.py`, workspace scoping, `db/documents.py` filters, retrieval scoping. Gate at an agreed threshold; rewrite tests only where surviving mutants point.

**Explicitly out of scope:** wholesale remediation of the ~31k-line test suite. That is a quarter of solo effort with diffuse payoff. The mutation gate concentrates effort exactly where the three confirmed bugs lived.

**Gate decided: `security_fastapi.py` + `src/utils/workspace.py`, threshold 80%.**
The other two modules are measured and reported nightly but do not fail the build
until they have a baseline and a remediation pass of their own. A per-module
threshold set to today's score would ratify the status quo rather than gate it —
80% against a measured 58.9% is the point.

**Measured (2026-08-15), `mutmut<3`, per the corrected method in [TEST_QUALITY_AUDIT.md](TEST_QUALITY_AUDIT.md):**

| Module | Killed | Survived | Rate |
|---|---|---|---|
| `src/security_fastapi.py` | 191 | 37 | **83.8%** (112 → 119 → 132 → 151 → 171 → 191) |
| `src/utils/workspace.py` | 5 | 0 | 100% (was 4/5) |

> **Green as of 2026-08-22.** The gate had been failing every night since
> 2026-08-19. Two batches of tests written against named survivors — 42 in
> `test_security_contract.py` and `test_workspace_access_contract.py`, both added
> to the gate's own module list — took the score from 66.2% through 75.0% to
> 83.8%. Each mutant was verified by applying the mutation and watching a test go
> red, never by reasoning that it should.
>
> **The gate found code problems, not only test problems.** The default in
> `_ROLE_LEVELS.get(role, -1)` is what an unrecognised role scores: flip it to
> `+1` and any role not in the table outranks `viewer` and is admitted. Nothing
> objected, because every existing test used a role that was in the table.
>
> **Two survivors are left deliberately, and both are questions rather than gaps:**
> - `_ROLE_LEVELS.get(min_role, 0)` — an *unknown minimum* is treated as no
>   requirement, so any known role passes. Killable by pinning that behaviour;
>   pinning it would enshrine something that looks wrong. Left as a question.
> - `claims.get("sub", "admin")` in `require_admin_dep` — the default is
>   unreachable, since `_current_global_role` already returns `None` without a
>   subject. An equivalent mutant, and dead code in an authorisation guard.
>
> **Five of the fifteen mutants I attacked first appeared to survive, and all five
> were my own measurement errors:** a `MagicMock` whose `state.resolved_workspace_id`
> was a truthy stand-in, so the "no workspace" branch was never reached; twice
> mutating the first of two identical lines, in a function the tests never call;
> and a boundary test that did not sit on the boundary — which, once moved onto it,
> tripped the clear-everything fallback and had to be given something evictable
> before the comparison could decide anything. The lesson the ticket already
> recorded from the previous round repeated itself exactly.

Three of the second batch's tests initially killed nothing, and each failure is a
reusable lesson rather than a slip:

- A stub that **raised** inside the fail-open check landed in the `except Exception`
  branch, which refuses anyway — so the test passed with the default flipped. It has
  to *answer* for the mutant to reach the accept path and become visible.
- The "exactly TTL" boundary test read the clock before patching it, making the gap
  `TTL + call duration`, which both `<` and `<=` reject identically. **A boundary
  test that does not sit exactly on the boundary tests nothing about it.**
- Constants referenced symbolically by every test (`_REVOCATION_CACHE_TTL`) move
  together with the code when mutated. Pinning the documented value is what catches it.
| `src/db/documents.py` | — | — | not yet measured |
| `src/rag/retrieval.py` | — | — | not yet measured |

**Done so far:** seven mutants moved from survived to killed, all in code that
authenticates or scopes — five in `verify_credentials` (including one that makes
the admin password work for any username), one in the `workspace_id` query-parameter
fallback, and the `hmac.compare_digest` inversion that only becomes killable once a
password is pinned. Each was verified against the exact mutant, not assumed.

**Three measurement corrections**, all of which had already distorted a number
before being caught, are now in the audit doc's environment notes: CI's env vars
must be exported into the run or whole functions are unreachable and score for free;
`mutmut` buckets partly on wall-clock, so a loaded machine files kills as
"suspicious" (a first run read 4 killed / 108 suspicious, the same scope idle read
112 / 0); and `python:3.12-slim` has no `git`, which one test shells out to.

**The gate is wired** — `scripts/mutation_gate.py`, run nightly by
`.github/workflows/mutation.yml` and on demand with a threshold input. It exports
CI's environment variables, passes `--test-time-base`, runs one module at a time,
and fails the job on a working tree left dirty by an abandoned mutant.

It screens the score before judging it, because during TQ-3 two different broken
runs produced plausible numbers. `killed == 0` is reported as *"the runner is not
exercising this module"* rather than as 0%, and any mutant classified *suspicious*
voids the run rather than being counted — those are opposite conclusions that look
identical in a percentage. A void run exits 2; a genuine miss exits 1.

**Expect it red until the survivors are dealt with.** At 65.3% against a threshold
of 80% the nightly fails by design; it is a work queue with teeth, not a merge
blocker — the job is scheduled, not required. Raise the score, not the threshold.

**The threshold was checked for reachability, not assumed.** Triaging the 70
survivors (see [TEST_QUALITY_AUDIT.md](TEST_QUALITY_AUDIT.md)) puts ~40 in the
behavioural class, ~24 in message/log text, and ~4 equivalent. Thirty behavioural
kills clear 80%; killing all forty reaches roughly 85%. So the gate is meetable
**without** asserting error strings — and if a session ever finds itself pinning log
text to move the number, that is evidence the threshold is wrong, not the tests.

**Remaining:** baselines for `db/documents.py` and `rag/retrieval.py`; the 83
`security_fastapi.py` survivors (clusters listed in the audit doc — revocation-cache
boundaries, the two fail-open `is_connected` defaults, the error-envelope key, and
the `SESSION_COOKIE`/`jti` contracts).

### TQ-5a — Alembic chain integrity check ✅ (done)

A pure-Python assertion in the fast suite, no database required:

- `ScriptDirectory.from_config()` resolves to **exactly one head**.
- The number of revisions equals the number of files in `migrations/versions/`, so a duplicate `revision = "NNNN"` cannot hide.

**Why this is its own ticket and not a line in TQ-5b:** it costs ~20 lines, needs no infrastructure, and catches the failure that actually occurred. On 2026-08-05 a backfill migration was numbered `0012`, colliding with the existing `0012_hybrid_search_tsvector.py`. Alembic does not error on a duplicate id — it emits `UserWarning: Revision 0012 is present more than once` through Python's `warnings` module, then `upgrade head` aborts with `MultipleHeads`, so **no migration applies at all**, including previously pending ones. It shipped through review, CI and merge (#219) and was found only by starting the stack (#222).

### TQ-5b — Migrations execute against a real database in CI ✅

`tests/integration/test_migrations_apply.py`, on a database it creates and drops, so no
assertion depends on what an earlier test left behind:

- The upgrade succeeds, judged by **exit status**. `_run_alembic_migrations()` catches
  and logs failures, so the application starts happily on an unmigrated schema — and for
  several days in August 2026 that log line went to a logger Alembic had just disabled,
  producing no output at all. A check reading output would have passed throughout.
- The database lands on the single head the script directory declares, and `current`
  reports it as `(head)` rather than some revision partway along.
- A second upgrade exits zero, leaves the revision alone, and **runs no revision at
  all** — the stronger form, since an identical end state can also mean both runs
  failed the same way.
- A fourth class guards the other three: a bad revision target and an unmigratable
  database must both exit non-zero. A runner that reports success regardless would make
  everything above vacuous.

**Correction: "against an empty database" was wrong**, and measuring said so.
`alembic upgrade head` on a genuinely empty database fails at `0002`, which opens with
`ALTER TABLE conversations` — `IF NOT EXISTS` guards the column, not the table. The base
schema comes from `_ensure_extensions_and_tables()` and the migrations are additive on
top; two halves of one schema, by design (CLAUDE.md). The test therefore runs the
sequence production runs. The empty-database case is kept, as the assertion that it
*fails*.

**Acceptance met:** invalid SQL added to `0012` turns 5 of the 8 tests red; the 3 that
stay green are the guards, which assert failures and so pass either way. Reverted.


### TQ-4 — One Playwright smoke test ✅

Login → upload document → ask question → receive answer with citation. **That is the entire frontend test strategy**, deliberately. The vanilla-JS frontend (9 files + an 867-line `settings.html`) is not worth a component-test investment at this scope; one end-to-end proof that the golden path works catches the regressions that matter.

`tests/e2e/test_golden_path.py`, against a server `tests/e2e/conftest.py` starts itself —
uvicorn in a subprocess, the integration job's Postgres, and TQ-2's fake Ollama in place
of a GPU. Only the model process is faked; auth, templates, the SSE upload stream,
ingest, pgvector retrieval and the SSE chat stream are the real ones. CI runs it in a
new `e2e` job, **deliberately not in the ruleset** — a browser test is the one job whose
flake would block every merge, and the same path is proven at the service layer by
`integration-tests` regardless.

Three things were wrong on the way, and each is why the test reads as it does:

- **`tests/e2e/test_smoke.py` had not run against this product since TQ-1b.** All five
  tests fail: they were written against a UI with no login, so every page they open
  redirects to `/login`. Nothing caught it because Playwright is installed nowhere, and
  `pytest.importorskip` turns "these tests are broken" into "these tests are skipped" —
  the same silence TQ-2 found in the `ollama`-marked suites. Deleted rather than fixed;
  the golden path is the strategy now.
- **Asserting on the answer text would have been vacuous.** The stub replies with the
  prompt it was handed, and the prompt carries the retrieved context — so the filename
  appears in the reply whether or not a citation was ever rendered. The assertion is on
  the sources panel the frontend builds.
- **The first version was flaky against a database that was not empty.** Every run
  uploads the same prose under a fresh name, so an earlier run's identical chunk could
  win the top rank and the answer cited *that* file. Found by accident while breaking
  the test on purpose; CI would never have shown it, since CI's database is always new.
  The document and the question now share a per-run codename, and the test retires its
  document afterwards.

**Acceptance met:** three separate breakages each turn it red, and each hits a different
assertion — not rendering the sources panel (the citation), disabling the similarity
threshold so every chunk passes (the unrelated-question check, which is what stops the
citation assertion from passing for a retriever that cites everything), and removing
auth.js's 401 redirect (the unauthenticated guard). All reverted.

---

## Phase 3 — The deletion sprint (Sprint PG-6)

**Delete, don't flag.** Flagged-off code still passes through every future authz audit, every Dependabot bump, every mutation run, every CodeQL scan. Git history preserves everything; re-adding a connector later costs days, while carrying it costs a tax on every sprint forever. The counterargument is real — the project's stated purpose is learning, and deletion destroys playgrounds — but the production claim was chosen over it, and depth on the retained core *is* the learning this project's own lessons file keeps pointing back to.

### DEL-1a — Remove the self-contained subsystems ⬜ (no gate; runs alongside PG-0)

> **Measurement corrected 2026-08-05.** The original ticket claimed all three had "no route
> surface and no OAuth flow, so removing them is a `git rm` plus an import sweep, not surgery."
> Re-checked against `main` @ `c750dac` before acting, and two of the three were wrong — following
> the ticket as written would have broken four endpoints. Only the Kuzu backend is actually
> self-contained. The rest is not cleanup; it is a product decision about live features, so it is
> reclassified below rather than deleted.

**Genuinely self-contained — safe to remove (this is DEL-1a):**

- **Kuzu graph backend.** `src/graph/store.py` keeps `PostgresGraphStore` only; `KuzuGraphStore`
  is reachable solely via `GRAPH_BACKEND=kuzu`, has no route and no caller outside the factory.
  `kuzu>=0.11.3` leaves `requirements.txt` line 38. Tombstone the removal commit so restoration
  is a `git revert` away.

**Not self-contained — reclassified, do not `git rm`:**

| Module | What the ticket claimed | What is actually there |
|---|---|---|
| `src/rag/active_learning.py` | no route surface; "**no test module references it at all**" | `GET /api/workspaces/{id}/suggestions` calls `suggest_documents` (`workspace_routes.py:304`), and six tests exercise it in `test_utils_encryption_export.py` |
| `src/rag/feedback_pipeline.py` | no route surface | **four** admin endpoints depend on it — `/reranker/train`, `/reranker/promote/{id}`, `/reranker/rollback/{id}` (`settings_routes.py:259-292`) — plus the scheduler wiring in `app_bootstrap.py:227` and tests in two modules |

Removing either means removing a feature users can reach: knowledge-gap suggestions, and the
adaptive-reranker fine-tune loop. That may still be the right call — neither has a known user —
but it is a scope decision with UI and admin consequences, not a deletion sprint item. **Decide
explicitly before either is touched; the default is that they stay.**

> The generalisable point, and the reason this correction is recorded rather than quietly applied:
> a plan is not evidence. This ticket carried a date, a commit hash and the word "measured", and was
> still wrong about the codebase it described — the same shape as the stale `file-map.md` that
> produced the duplicate revision id a day earlier. Re-derive from the code at the moment of acting,
> per Chapter 9's rule applied to this project's own documents.

### DEL-1b — Cloud connectors: delete Confluence, retain Google Drive and OneDrive ⬜ (TQ-1 gate ✅ satisfied)

> **Rewritten 2026-08-24.** The original ticket deleted all four files on a single "no real user" test.
> That test now has a different answer for two of them: Google Drive and OneDrive are the named
> candidates for actual use, with test cases to be supplied by the maintainer. This document's own
> stated exemption — *"the only valid reason to drop DEL-1b is a concrete intent to use one of these
> connectors"* — is therefore invoked rather than overridden. The original text is in git history.
> **Sequencing gate satisfied:** TQ-1a and TQ-1b are both done, so the authz CI net the original
> ticket waited for is already in place.

**Delete — Confluence only:**

- `src/connectors/confluence_connector.py` (191 lines) and `tests/unit/test_confluence_connector.py` (159)
- `html2text==2025.4.15` (`requirements.txt:40`) — verified to have exactly one import site,
  `confluence_connector.py:32`. Confluence is the only one of the three whose removal shrinks the
  runtime dependency set of a deliberately distroless image.
- `CONFLUENCE_URL` / `CONFLUENCE_EMAIL` / `CONFLUENCE_API_TOKEN` (`src/config.py:578-580`)
- registrations in `src/connectors/registry.py` and `mcp_servers/cloud_connectors/server.py`

Five tracked files plus a requirements line. Tombstone the removal commit so restoration is a
`git revert` away.

**Retain — Google Drive and OneDrive.** `google_auth.py` stays with Google Drive. `microsoft_auth.py`
was never in scope: SharePoint keeps it alive regardless, which is why OneDrive's *marginal* carrying
cost is close to zero — 187 lines plus a test module riding on auth infrastructure already retained.

**Keep as before:** local folder, S3/MinIO/R2, webhook, SharePoint. The plugin contract and the three
MCP servers stay — they are the architecture, not the sprawl.

**What the retained code actually is — measured 2026-08-24, not assumed:**

| Assumption | Verified state |
|---|---|
| "a working feature we would be throwing away" | **No.** `git grep -ril connector` over `templates/` and `static/js/` returns nothing. The entire connector subsystem has never had a UI, so no connector has ever run against a live account. |
| "unused but harmless" | **No.** `docs/PERMISSIONS.md` lists **10 connector routes** as live product surface. The API claims a feature the product does not have — an exit-criterion-7 failure that exists today, independent of this ticket. |
| "no dependency cost" | **True** for Google Drive and OneDrive: both use plain `requests` against Graph / Drive v3. |

So the retained code is **design knowledge** — Graph delta queries, the Drive changes feed, token
refresh, encrypted token storage — and not a shipped feature. Value it accordingly.

**The sunk-cost argument, re-stated correctly.** The original ticket's reasoning against sunk cost
holds *for code with no forward demand*, which is now Confluence alone; it does not apply to code with
a named forward use. The place sunk cost would genuinely bite is not the ~400 retained lines — it is
inheriting `config['user_id']` as an authorisation model because it happened to be there. Answer the
authorisation question on a blank page (ROADMAP CONN-1), fix the defect it exposed (ROADMAP BUG-4),
and keep whatever survives.


### DEL-2 — GraphRAG: earn its place or leave 🔬

Build a small retrieval eval set first (20–30 question/expected-source pairs over the real document corpus — this asset outlives the decision and later serves RAG-tuning work). Measure retrieval quality with GraphRAG expansion on vs off. If 1-hop expansion does not measurably lift answer grounding on our own documents, `src/graph/` goes the way of DEL-1. No sentiment: the eval decides.

---

## Phase 4 — Operate like a product (Sprints PG-7..PG-8)

### OPS-1 — Reproducible builds: uv + lock file ⬜

Adopt `uv` with a committed lock file. **Note the history:** `requirements.lock.txt` was removed in the 2026-07-30 dependency-pipeline repair (LESSONS_LEARNED Ch. 11) — that was the right call for a hand-maintained lock text next to grouped Dependabot. This is a different mechanism: a tool-managed lockfile that Dependabot/Renovate understands, giving reproducible installs without the manual-drift failure that killed the last attempt.

### OPS-2 — Bounded de-globalisation of `config.app_state` ⬜

Migrate **only auth- and workspace-relevant state** from the `config.app_state` singleton to `request.app.state` via FastAPI dependencies. The singleton is the hidden global that let bypass state leak everywhere and made tests lie. RAG tuning parameters (`get_rag_param`) may stay global — they are not security-relevant, and full DI purity is not worth solo months. Scope is the ticket: when the auth and workspace paths no longer touch `config.app_state`, this is done.

### OPS-3 — Docs inside the drift mechanism ⬜

The wiki is the one documentation surface outside every drift-catching mechanism this project built after the Flask-era doc-drift lesson — and it drifted: the March-2026 assessment describes the Flask architecture, cites ~1,000 tests against today's ~2,300, and recommends features that now exist.
- Shrink the wiki to Home + a link to `docs/ROADMAP.md`.
- Date-stamp the March-2026 assessment as a historical snapshot of the Flask-era codebase, or delete it.
- Move `Improvement-feedback` to `.github/ISSUE_TEMPLATE/improvement.md`, where GitHub actually renders the front-matter.
- Add the DEMO_MODE layer-inversion lesson (SEC-1) to `LESSONS_LEARNED.md`.

### OPS-4 — Prove restore in CI ⬜

`OPERATIONS.md` describes backup and restore; an untested restore procedure is a wish. Add a CI job (can share TQ-2's Postgres service): seed data → `pg_dump` per the documented procedure → drop schema → restore → assert row counts and a sample vector query. Green means the ops doc is true.

### OPS-5 — Release discipline + production topology ⬜

- Tag `v3.0.0-beta.1`; the tag-triggered `docker-publish.yml` finally runs; start `CHANGELOG.md` (README's changelog link currently points at zero releases).
- Document the recommended topology in `DEPLOYMENT.md`: nginx/Traefik TLS termination in front, app bound to loopback/internal network behind it, `METRICS_TOKEN` set. One page, one diagram.

---

## Sprint plan

Runs after ROADMAP Sprint 6b. ROADMAP Sprints 8–12 (GKB, PC, PR-1) queue behind the Exit Criteria.

| Sprint | Tickets | Est. duration |
|---|---|---|
| PG-0 | ADR-1 + ADR-2 (written, committed, README/wiki reframed) + DEL-1a (self-contained deletions, no gate) + TQ-5a ✅ (alembic chain check) | 1-2 days |
| PG-1 | SEC-1 ✅ + SEC-2 ✅ (fail-closed boot, DEMO_MODE deleted, revocation fail-closed) | — |
| PG-1b | SEC-3 ✅ + SEC-4 (rate limiting keys on the real client; ENCRYPTION_KEY enforced) — from the 2026-08-19 external audit | — |
| PG-2 | PERF-1 + PERF-2 (threadpool offload, concurrency benchmark before/after) | 3–4 days |
| PG-3 | TQ-1a ✅ (authz-by-default introspection) + TQ-1b ✅ (bypass deleted; 290 tests converted, not the 39 the ticket counted) | done |
| PG-4 | TQ-2 (fake-Ollama deterministic integration CI) + TQ-5b (migrations executed against a real DB, reuses TQ-2's Postgres) | 1 week |
| PG-5 | TQ-3 ✅ (scoped mutation gate, 83.8%) + TQ-4 ✅ (Playwright golden path, self-starting server) | — |
| PG-6 | DEL-1b + DEL-2 (cloud-connector removal, sequenced after TQ-1; GraphRAG eval verdict) | 1 week |
| PG-7 | OPS-1 + OPS-2 (uv lock; bounded de-globalisation) | 1 week |
| PG-8 | OPS-3 + OPS-4 + OPS-5 (docs mechanism, restore proof, release + topology) | 1 week |
| **Total** | | **~8 weeks** |

> **Freeze rule:** the last depth sprint leaked — connectors and features landed during it. This one has a backstop: until the Exit Criteria below are green, the only valid ticket sources are this table and confirmed bug fixes (bugs never queue behind the gate, per the Sprint 5 precedent).

---

## Exit criteria — the definition of "production grade"

v3.0 ships when **all eight** hold, and not before:

1. **Fail-closed boot** — no configuration path exists in which `APP_ENV=production` runs with authorisation off. (SEC-1 ✅, SEC-2 ✅)
2. **Authz-by-default CI green** — every route in the table is protected or explicitly allowlisted; a new unprotected route fails CI (TQ-1a ✅). Testing bypass deleted (TQ-1b ✅).
3. **Concurrency budget met** — p95 time-to-first-token under the agreed budget at 10 concurrent SSE users; benchmark and numbers committed to the repo. (PERF-1/2)
4. **Mutation score ≥ threshold** on the core security/isolation modules, enforced nightly. (TQ-3 ✅ — 83.8% and 100%, green 2026-08-22)
5. **Restore proven in CI** — the documented backup/restore procedure passes automatically. (OPS-4)
6. **Reproducible release** — tagged version, changelog, uv lock file, published image from the tag. (OPS-1/5)
7. **The claim matches the code** — README, wiki and this document describe the same product (ADR-1), and every statement in them is mechanically or manually verified true at tag time.
8. **Migrations are executed, not merely written** — CI applies the full chain to an empty database, proves it idempotent, and fails on a broken or duplicated revision. No migration reaches a tag having never run. (TQ-5a/TQ-5b)

When these are green: un-queue ROADMAP Sprints 8–12 and resume feature work on a codebase that has earned its first line.
