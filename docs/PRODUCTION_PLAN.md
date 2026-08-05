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

### SEC-1 — Delete every authorisation bypass; seed a dev admin instead ⬜

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

### SEC-2 — Token revocation fails closed ⬜

`_verify_jti_not_revoked()` currently swallows DB errors and lets the request through ("fail open rather than locking out users"). For a production claim, revocation that is advisory is not revocation. Change to fail-closed with a **60-second in-process cache of recent revocation-check results** so a DB blip degrades to slightly-stale-but-enforced rather than to open. Single-node (ADR-1) makes the in-process cache correct.

### PERF-1 — Unblock the event loop in `api_chat` ⬜

`api_chat` is `async def` but inline-calls sync `chat.retrieve_contexts` (sync psycopg, sync httpx embedding call, cross-encoder inference) and sync `persist_user_message` / `persist_assistant_message`. One slow retrieval stalls **every** concurrent request, including SSE streams already mid-flight. The inference path is properly async (HK-8); retrieval never got the same treatment — the migration stopped halfway.

Fix: wrap `retrieve_contexts`, `retrieve_plan_and_memory`'s sync internals, and both persist calls in `starlette.concurrency.run_in_threadpool`. Audit the other async routes for the same pattern while in there (upload path in `document_routes.py` is the next most likely offender 🔬). Per ADR-2, this is the *final* fix, not a stopgap.

### PERF-2 — Concurrency benchmark, committed to the repo ⬜

There is currently no measurement of behaviour under concurrency, which is why PERF-1's defect survived this long. Add `scripts/bench_concurrency.py` (or a k6/locust config): **10 concurrent SSE chat clients, record p95 time-to-first-token and p95 total stream time**, against a seeded test corpus. Run before and after PERF-1 and record both numbers in this document. Wire it as a manually-triggered CI job so it becomes a permanent regression check, not a one-off proof.

---

## Phase 2 — Prove behaviour, not coverage (Sprints PG-3..PG-5)

The mutation audit (`TEST_QUALITY_AUDIT.md`) already established internally what the external audit confirmed from the outside: coverage-driven sessions produced tests that run code without checking behaviour, and the whole suite runs with the RBAC bypass on — *coverage without authorisation*. So stop gating on coverage percentage and gate on behaviour.

### TQ-1 — Authz-by-default CI job ⬜

- Add a CI job that boots the app in production-like config (`APP_ENV=production`, auth configured), **introspects the FastAPI route table**, and asserts 401/403 on every route not on an explicit public allowlist. The introspection is the point: a new route added without auth *fails CI by default*. This mechanises the BUG-3 / RBAC-1 lesson — correct enforcement code existing with zero call sites is caught by a mechanism, not a memory.
- Then **delete the testing bypass** (`app.state.testing` in `_is_rbac_bypassed()`) and repair the fallout: every route-authorisation test runs with the bypass OFF. "Coverage without authorisation" ends with this ticket.

### TQ-2 — Deterministic integration CI ⬜

Postgres service container plus a **fake Ollama** — a ~100-line stub returning canned embeddings and completions. The full ingest → ask → cite path runs in CI without a GPU, deterministically. This is the harness TQ-1's production-config boot and OPS-4's restore proof both reuse.

### TQ-3 — Mutation gate, scoped ruthlessly ⬜

Nightly, core modules only: `security_fastapi.py`, workspace scoping, `db/documents.py` filters, retrieval scoping. Gate at an agreed threshold; rewrite tests only where surviving mutants point.

**Explicitly out of scope:** wholesale remediation of the ~31k-line test suite. That is a quarter of solo effort with diffuse payoff. The mutation gate concentrates effort exactly where the three confirmed bugs lived.

### TQ-5a — Alembic chain integrity check ✅ (done)

A pure-Python assertion in the fast suite, no database required:

- `ScriptDirectory.from_config()` resolves to **exactly one head**.
- The number of revisions equals the number of files in `migrations/versions/`, so a duplicate `revision = "NNNN"` cannot hide.

**Why this is its own ticket and not a line in TQ-5b:** it costs ~20 lines, needs no infrastructure, and catches the failure that actually occurred. On 2026-08-05 a backfill migration was numbered `0012`, colliding with the existing `0012_hybrid_search_tsvector.py`. Alembic does not error on a duplicate id — it emits `UserWarning: Revision 0012 is present more than once` through Python's `warnings` module, then `upgrade head` aborts with `MultipleHeads`, so **no migration applies at all**, including previously pending ones. It shipped through review, CI and merge (#219) and was found only by starting the stack (#222).

### TQ-5b — Migrations execute against a real database in CI ⬜ (**after TQ-2**)

Reuses TQ-2's Postgres service container:

- `alembic upgrade head` against an **empty** database; assert `alembic current` equals the single head.
- Run it a second time; assert it is a no-op. Idempotency is the property the "additive migrations only" rule claims and nothing checks.
- Assert on the **command's exit status**, never on log output — see below.

**The gap this closes.** Migrations run only via `bootstrap_app()` at real startup; CI's integration tests use `create_app()`; and no test in the repo connects to Postgres at all, even though the integration job already starts one. So **no CI job has ever executed a migration.** Every migration in `versions/` reached `main` unexecuted, and the first run happens on a deployment.

**Why exit status, not logs.** `_run_alembic_migrations()` catches the exception and logs it, so a failed migration is non-fatal by design — the app serves normally with an unmigrated schema. Worse, until #223/#225 that log line went to a logger Alembic itself had just disabled, so the failure produced *no output at all* for days. A check that greps logs would have passed throughout. The assertion must be the process exit code.

**Acceptance:** deliberately break a migration (duplicate id, or invalid SQL) and confirm CI goes red; revert.

### TQ-4 — One Playwright smoke test ⬜

Login → upload document → ask question → receive answer with citation. **That is the entire frontend test strategy**, deliberately. The vanilla-JS frontend (9 files + an 867-line `settings.html`) is not worth a component-test investment at this scope; one end-to-end proof that the golden path works catches the regressions that matter.

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

### DEL-1b — Remove the unused cloud connectors ⬜ (**must land after TQ-1**)

**Delete:** `google_drive_connector.py` (197), `onedrive_connector.py` (158), `confluence_connector.py` (160), `google_auth.py` (66), plus their routes, tests and OAuth flows.

**Keep:** local folder, S3/MinIO/R2, webhook, SharePoint (+ `microsoft_auth.py`) — the ones with a real user. The plugin contract (PC initiative) and the three MCP servers stay: they are the architecture, not the sprawl.

**Why this half is sequenced behind TQ-1, and DEL-1a is not.** These four files are not isolated. They are threaded through `oauth_routes.py` (3 sites), `settings_routes.py` (3), `workspace_routes.py`, `connector_routes.py`, and are covered by 4 test modules with ~97 references. That is the same shared route surface RBAC-1 just rewrote and TQ-1 will mechanically enforce. Cutting OAuth paths out of those files *before* the authz CI job exists means doing it without the net that proves no route was left unprotected — and then touching the same files again when TQ-1 lands. Cut once, with the test that checks it already in place.

**What is deliberately not an argument here:** `test_confluence_connector.py` has the largest test investment of the three (42 references). That is sunk cost, and if anything it is evidence *for* removal — those tests run on every suite execution, every Dependabot bump and every mutation sweep, for a connector with no user. The only valid reason to drop DEL-1b is a concrete intent to use one of these connectors; absent that, invested test code is a carrying cost, not an asset.
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
| PG-1 | SEC-1 + SEC-2 (fail-closed boot, DEMO_MODE deleted, revocation fail-closed) | 3–4 days |
| PG-2 | PERF-1 + PERF-2 (threadpool offload, concurrency benchmark before/after) | 3–4 days |
| PG-3 | TQ-1 (authz CI job; then delete the testing bypass and repair fallout) | 1 week |
| PG-4 | TQ-2 (fake-Ollama deterministic integration CI) + TQ-5b (migrations executed against a real DB, reuses TQ-2's Postgres) | 1 week |
| PG-5 | TQ-3 + TQ-4 (scoped mutation gate; Playwright smoke) | 1 week |
| PG-6 | DEL-1b + DEL-2 (cloud-connector removal, sequenced after TQ-1; GraphRAG eval verdict) | 1 week |
| PG-7 | OPS-1 + OPS-2 (uv lock; bounded de-globalisation) | 1 week |
| PG-8 | OPS-3 + OPS-4 + OPS-5 (docs mechanism, restore proof, release + topology) | 1 week |
| **Total** | | **~8 weeks** |

> **Freeze rule:** the last depth sprint leaked — connectors and features landed during it. This one has a backstop: until the Exit Criteria below are green, the only valid ticket sources are this table and confirmed bug fixes (bugs never queue behind the gate, per the Sprint 5 precedent).

---

## Exit criteria — the definition of "production grade"

v3.0 ships when **all eight** hold, and not before:

1. **Fail-closed boot** — no configuration path exists in which `APP_ENV=production` runs with authorisation off. (SEC-1, SEC-2)
2. **Authz-by-default CI green** — every route in the table is protected or explicitly allowlisted; a new unprotected route fails CI. Testing bypass deleted. (TQ-1)
3. **Concurrency budget met** — p95 time-to-first-token under the agreed budget at 10 concurrent SSE users; benchmark and numbers committed to the repo. (PERF-1/2)
4. **Mutation score ≥ threshold** on the core security/isolation modules, enforced nightly. (TQ-3)
5. **Restore proven in CI** — the documented backup/restore procedure passes automatically. (OPS-4)
6. **Reproducible release** — tagged version, changelog, uv lock file, published image from the tag. (OPS-1/5)
7. **The claim matches the code** — README, wiki and this document describe the same product (ADR-1), and every statement in them is mechanically or manually verified true at tag time.
8. **Migrations are executed, not merely written** — CI applies the full chain to an empty database, proves it idempotent, and fails on a broken or duplicated revision. No migration reaches a tag having never run. (TQ-5a/TQ-5b)

When these are green: un-queue ROADMAP Sprints 8–12 and resume feature work on a codebase that has earned its first line.
