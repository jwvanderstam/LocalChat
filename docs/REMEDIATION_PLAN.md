# LocalChat remediation plan

> ## Status — committed 2026-09-17, after every P0 and P1 fix shipped in v3.1.0
>
> This document was **private until the fixes it describes were merged** — its original
> status line read *"PRIVATE. Contains unfixed, reproduced security findings. Do not commit
> to the public repository until the P0 fixes are merged (decision D1)."* Decision D1 was
> taken as **B, fix in public**, in one PR (#380, squash-merged as `5e9c2d6`), and the plan
> is committed unchanged below it so the findings, the reasoning and the decisions stay
> readable against the code they were made about. Only this banner is new.
>
> **Where each row landed** — every entry in [CHANGELOG 3.1.0](../CHANGELOG.md) names the
> finding it closes; the commits are the branch that became #380.
>
> | Ticket | Findings | Status | Where |
> |---|---|---|---|
> | P0-1 | C1, C2 | ✅ | `src/utils/scope.py`; `tests/unit/test_object_authorization_matrix.py` is the acceptance test, and it walks the AST of `src/` rather than the route table |
> | P0-2 | C3 | ✅ | `af3729d` — D4 taken as **B**: MCP kept, bearer-authenticated, `search` requires a workspace; residual in [SECURITY.md §10](../SECURITY.md) |
> | P0-3 | C4 | ✅ | `a3884c7` — D3 as **A** |
> | P0-4 | H1, H2, M1 | ✅ | `75e21f0` — `resolve_principal()`; D6 as **A** (bootstrap-only credential), residual in [SECURITY.md §7](../SECURITY.md) |
> | P0-5 | H3 | ✅ | `019781b` — both halves: nginx sends `$remote_addr`, and the overlay pins the `frontend` subnet |
> | P1-1 | H4, M2 | ✅ | `1eb02ca` |
> | P1-2 | M4, M5 | ✅ | `d8cb5db` (`src/utils/safe_fetch.py`), `77dc09f` — D5 as **A**; residual (no address pinning) in [SECURITY.md §9](../SECURITY.md) |
> | P1-3 | M3 | ✅ | `d7bbaba` — the inference was right: the callback could not read the session |
> | P1-4 | M6, M8 | ✅ | `ab7f66e`, `2966310`, `dcc2559` |
> | P1-5 | M7 | ✅ | `1eb02ca` |
> | D7 | README claim | ✅ | "Hardened beta", 2026-09-16 |
> | P2-1 | driver 1 | ◐ | The `Scope` value object and the static CI check shipped with P0-1. Row-level security has not |
> | P2-2..P2-8 | drivers 2–6 | ⏳ | Not scheduled. Not in [ROADMAP.md](ROADMAP.md) yet |
> | §4.1 sweep | docs | ⏳ | Delivered as a bundle, **not merged**: `.env.example` still carries the unread variables, OPERATIONS.md still mentions Kubernetes, `test_env_example_is_read.py` does not exist. The README and `onnxruntime` rows were overtaken by D7 and Dependabot #371 |
>
> What this episode taught is [LESSONS_LEARNED Ch. 20](LESSONS_LEARNED.md#20-every-route-had-a-guard-and-a-green-check-said-so).

**Status (as written, 2026-09-16):** PRIVATE. Contains unfixed, reproduced security findings.
Do not commit to the public repository until the P0 fixes are merged (decision D1).
**Basis:** external audit of `main` at `3532a89`, 15 to 16 September 2026.
**Owner:** JW van der Stam. **Prepared by:** Claude.

Confidence labels: **[repro]** reproduced in the sandbox; **[code]** established by reading
the code; **[inference]** reasoned, not executed.

---

## 1. Findings register

### Critical

| ID | Finding | Evidence |
|---|---|---|
| C1 | **Missing object-level authorization.** The workspace guard authorizes the caller against their *own* workspace; the database call then acts on objects in *any* workspace. `DELETE /api/documents/clear` hard-deletes every document in the installation for any user who owns a workspace, and any user can create one. | [repro] plain user, HTTP 200, `delete_all_documents()` called |
| C2 | Same class, other routes: `POST /api/documents/search-text` searches chunk text across all workspaces (deleted documents included); `GET /api/documents/chunks/{id}/context` reads any chunk by sequential integer id; `DELETE /api/documents/{id}` retires any document; `DELETE` all memories retires every user's memories; update and delete of conversations, memories, annotations and connectors act on any id (UUIDs, so harder to reach). | [code], static scan of all routes |
| C3 | **Workspace isolation lost with `MCP_ENABLED=true`.** `get_rag_context` drops `workspace_id`; the MCP `search()` cannot accept one; retrieval treats `None` as "all workspaces". MCP servers have no authentication. | [repro] stubbed call |
| C4 | **Any user can read server files.** Any user creates a workspace, becomes owner, and creates a `local_folder` connector on any readable path. | [repro] `/etc` validated, listed, fetched |

### High

| ID | Finding | Evidence |
|---|---|---|
| H1 | **Revoked tokens still accepted** by `check_workspace_access` (documents, chat, memory, feedback, annotations, connectors) and `require_admin_dep` (31 admin routes). Only `require_auth` checks revocation. Bounded by the 2 h expiry. | [repro] |
| H2 | **Demoted admin keeps owner access** to every workspace via the stale JWT `role` claim. | [repro] |
| H3 | **Rate limiting bypassed behind the bundled nginx.** `TRUSTED_PROXY_IPS="*"` makes uvicorn take the leftmost `X-Forwarded-For` entry, which the client controls because nginx appends. Login brute force is unthrottled on the public-ingress path. The SEC-3 test never exercises the shipped overlay. | [repro] |
| H4 | **Upload collision.** All uploads share `UPLOAD_FOLDER` under their sanitized name; workspace A's pending ingest can read workspace B's file, and A's cleanup deletes B's file. | [repro] mechanism; frequency [inference] |

### Medium

| ID | Finding | Evidence |
|---|---|---|
| M1 | Env-var `admin` bypasses the database: cannot be disabled or demoted; no strength check (the `.env.example` placeholder passes production validation); stays valid next to a changed database admin password. | [code] |
| M2 | Upload size not enforced: `MAX_CONTENT_LENGTH` is a Flask-era value only echoed in stats; `file.file.read()` is unbounded. nginx has no `client_max_body_size`, so uploads over 1 MB fail with 413 behind it. | [code] |
| M3 | OAuth connect probably broken in browsers: the `SameSite=Strict` cookie is not sent on the provider's redirect, so the callback returns 401 after the code exchange. State is not bound to a user and never expires. | [inference] |
| M4 | SSRF guards are hostname-string checks only: DNS names resolving to private addresses and compose service names pass; redirects are not re-validated. Web search and webhook fetch. Webhook secret is optional and compared with `!=`; no response size cap. | [code] |
| M5 | S3 connector: owner-controlled `endpoint_url`; falls back to the server's own AWS credentials; `boto3` is not in the image, so the connector cannot work as shipped. | [code] |
| M6 | No CSP or security headers (app and nginx); one inline `onclick` in `ingestion.js` with HTML-escaped values inside a JS string. | [code] |
| M7 | `UVICORN_WORKERS` is a live knob although ADR-1 depends on one process; >1 silently splits rate limits, revocation cache and OAuth state. | [code] |
| M8 | CORS default origins lack a scheme and `setup_cors` falls back to `*`. CORS is off by default. | [code] |

**Correction to the part 2 report:** the Scaleway shared rate-limit bucket is already analysed
and accepted in DEPLOYMENT_SCALEWAY.md (D8). It is not a new finding.

---

## 2. What drives the score besides the defects

Ranked by estimated effect on the scores (judgement, not measurement).

1. **Scoping is optional by design** (architecture). `workspace_id=None` means "everything",
   and enforcement is per-route convention. This one property produced C1, C2 and C3. Fixing
   the defects one by one leaves the next route free to repeat them.
2. **Tests verify mechanisms, not the system** (testing). There is no role × route ×
   foreign-object matrix and no test of the shipped compose configurations. 96 to 100% line
   coverage on the modules that held the defects shows the gap.
3. **Thin RAG quality evidence** (general impression). 20 pairs on the repo's own docs; no
   faithfulness or citation-correctness measure. GraphRAG and active learning ship without
   evidence.
4. **Documentation architecture** (documentation). About 95k words; current-state documents
   mixed with the project journal; correctness depends on manual re-verification.
5. **Surface area versus scope.** MCP servers, six connectors, GraphRAG, active learning;
   two of these produced findings.
6. **Code hygiene.** 115 blind `except`, production `assert`s, about 3 GB image from CUDA
   torch, `python-jose`.

Counterargument considered: ADR-1 limits LocalChat to one trusted team, so insider threats
could be out of scope. Rejected: the product explicitly sells workspace isolation and RBAC
inside that team, and C1 lets any member destroy everyone's data.

---

## 3. Plan

One PR per row, in order. Each PR carries its own tests and the documentation it makes true
(section 4). P0 PRs are developed privately (D1).

### P0: before any exposure beyond localhost

| PR | Fixes | Change (best practice) | Acceptance |
|---|---|---|---|
| P0-1 | C1, C2 | **Object-level authorization, deny by default.** Every route addressing an object by id resolves the object's `workspace_id` in the same query (`WHERE id = %s AND workspace_id = %s AND deleted_at IS NULL`) and returns 404 when it does not match. `search-text` takes the workspace. Installation-wide operations per D2. | New `test_object_authorization_matrix.py`, generated from route introspection: for each role, each object route, an object in a foreign workspace yields 404 or 403. Fails on today's code. |
| P0-2 | C3 | **Retrieval fails closed.** Every retrieval and database read that accepts `workspace_id` raises when it is `None`, except in explicit admin paths that pass `ALL_WORKSPACES`. MCP per D4. | Unit test: `workspace_id=None` raises; MCP path forwards the scope, or MCP removed. |
| P0-3 | C4 | **`local_folder` least privilege** per D3: admin-only creation, roots restricted by `CONNECTOR_LOCAL_ROOTS`, checked with `os.path.realpath` plus `os.path.commonpath`; empty means the connector type is disabled. | `/etc`, `..` and symlink escapes rejected; non-admin gets 403. |
| P0-4 | H1, H2, M1 | **One authentication resolver.** A single function decodes the token, checks revocation (fail closed), and reads the global role from the database; `check_workspace_access`, `require_admin_dep` and `require_auth` all call it. The JWT `role` claim is ignored for decisions. Env admin per D6. | Route-introspection test: a revoked token gets 401 on every protected route; a demoted admin gets 403 on foreign workspaces. |
| P0-5 | H3 | **Proxy trust.** nginx: `proxy_set_header X-Forwarded-For $remote_addr;`. Compose: a fixed subnet on the `backend` network and `TRUSTED_PROXY_IPS` set to it instead of `*`. | Test of the shipped overlay: a spoofed `X-Forwarded-For` does not change the rate-limit key. |

### P1: hardening

| PR | Fixes | Change | Acceptance |
|---|---|---|---|
| P1-1 | H4, M2 | Unique temp file per upload (`tempfile.mkstemp` in `UPLOAD_FOLDER`); streamed write with a byte cap returning 413; `MAX_CONTENT_LENGTH` enforced; nginx `client_max_body_size` set to match; the sync read moved off the event loop. | Two same-name uploads get distinct paths; an oversized upload returns 413 without buffering. |
| P1-2 | M4, M5 | One `safe_fetch` utility: resolve DNS and reject any private or reserved address in the result, connect to the resolved IP, follow redirects manually with re-validation, cap bytes and time, check content type. Used by web search and webhook. Webhook secret mandatory, compared with `hmac.compare_digest`. S3 per D5. | Tests for DNS-to-private, redirect-to-private, oversize. |
| P1-3 | M3 | OAuth `state` stored with `user_id` and expiry at `/authorize`, resolved in the callback without requiring the session cookie; PKCE added. | Callback without cookie succeeds for a valid state; expired or foreign state fails. |
| P1-4 | M6, M8 | Security-headers middleware (CSP without `unsafe-inline` for scripts, `X-Content-Type-Options`, `Referrer-Policy`, HSTS behind TLS); remove inline handlers; CORS default origins with scheme and no `*` fallback. | Header assertions in tests; `repo-hygiene` bans inline `on*=` handlers. |
| P1-5 | M7 | Boot refuses `UVICORN_WORKERS != 1`. | Unit test. |

### P2: structural score drivers

| PR | Driver | Change | Acceptance |
|---|---|---|---|
| P2-1 | 1 | A mandatory `Scope` value object in the database mixins (no optional `workspace_id`). Then Postgres row-level security as defence in depth, with `SET LOCAL app.workspace_id` per transaction. | Static CI check (productised version of the audit scan): no guarded route calls an unscoped database method. RLS test: a query without scope returns nothing. |
| P2-2 | 2 | Security smoke job that boots `docker-compose.yml` and the nginx overlay and asserts: spoofed XFF does not bypass limits; MCP (if kept) rejects unauthenticated calls; the object-authorization matrix passes against real Postgres. | Required check in the ruleset. |
| P2-3 | 3 | Evaluation set of at least 100 question/answer/source triples on a representative private corpus; retrieval recall@k and MRR plus answer faithfulness and citation correctness (LLM judge calibrated on a human-scored sample); nightly with thresholds. Decide GraphRAG and active learning on the results. | Baseline recorded; regression threshold enforced. |
| P2-4 | 6 | Ruff `BLE001` enabled with per-line justification; production `assert` replaced by explicit exceptions. | Ruff clean with the rule on. |
| P2-5 | 6 | CPU-only torch in the image; measure before and after. | docker-smoke green; size recorded in DEPLOYMENT.md. |
| P2-6 | 6 | `python-jose` replaced by PyJWT (removes the `ecdsa` accepted-risk entry). | Auth tests green; SECURITY §2 removed. |
| P2-7 | 4 | Move journal documents (ROADMAP history, PRODUCTION_PLAN, LESSONS_LEARNED, DEPLOYMENT_LOG, TEST_QUALITY_AUDIT, AUTH_PLAN) under `docs/history/`; operator docs stay current-state; extend doc tests (see 4.3). | Docs catalogue test updated; links green. |
| P2-8 | 5 | Surface reduction per D4 and D5. | Removed code, tests and docs in one PR each. |

**Estimated scores after P0 to P2** (judgement): architecture about 8, testing about 8.5,
documentation about 8, code about 8, overall about 8.

---

## 4. Documentation

### 4.1 Consistency sweep: done

Branch `docs/consistency-sweep-2026-09`, five commits on `3532a89`, delivered as
`localchat-docs-consistency.zip` (bundle plus patches). No unfixed-vulnerability content.
Verified: `ruff check .` clean, 532 doc and config unit tests pass. Not run: integration,
e2e, docker-smoke.

| Area | Inconsistency | Fix |
|---|---|---|
| `.env.example` | 26 variables nothing reads (`MAX_UPLOAD_SIZE_MB`, `MAX_FILE_SIZE`, SMTP block, gunicorn `WORKERS` block, `DEBUG`, `OLLAMA_TIMEOUT`, ...); `HOST`/`PORT` instead of `SERVER_HOST`/`SERVER_PORT`; RAG values (`CHUNK_SIZE=768`, `CHUNK_OVERLAP=128`, `TOP_K_RESULTS=15`, `OLLAMA_EMBED_TIMEOUT=300`) overriding code defaults; Helm reference | Rewritten; guard test `test_env_example_is_read.py` (fails on the old file) |
| CONFIGURATION.md | Unread `OLLAMA_DEFAULT_MODEL`, `REDIS_DB`, `DEBUG`; OAuth redirect defaults shown empty; `SERVER_*`, `UVICORN_WORKERS`, `UVICORN_TIMEOUT` undocumented; `UVICORN_TIMEOUT` described as a request timeout (it is keep-alive) | Fixed; nginx 300 s read timeout noted as the real ceiling |
| TROUBLESHOOTING.md | `OLLAMA_MODEL`, `OLLAMA_EMBED_MODEL`, `EMBEDDING_CACHE_MAX_SIZE` (5000) do not exist | Real names; cache size is a 500-entry constant |
| `src/config.py` | Gunicorn timeout comment | Removed |
| `requirements.in`, ADR-3, SECURITY §5 | Describe a 1.28.0 `onnxruntime` pin; Dependabot moved it to 1.30.0 (#371) | Updated; 1.29.x exclusion kept. #371's CI result not verified (API rate limit) |
| SECURITY §4 | Cites the unbuilt plugin contract as a control | Clarified |
| OPERATIONS.md | Kubernetes deployments | Removed |
| README | Quick start fails as written (compose requires five non-empty values) and promises a generated password that cannot happen under Docker; S3 advertised without `boto3`; plugin contract presented as built; test numbers stale; ruff command differs from CI | Fixed; test numbers re-measured |
| CLAUDE.md | Upload types; reranker "optional" (on by default); table `messages` (real name `conversation_messages`); every CDI "carries deleted_at and deleted_by" (not `document_chunks`, not `conversation_messages`); ruff command | Fixed |
| `.claude/rules/file-map.md` | `conversation.js` exports `sendMessage` (it does not) | Fixed |
| CHANGELOG | | Entry added |

Checked and clean: 87 routes against every documented endpoint; relative links and anchors;
repo paths in current docs (remaining hits are history docs or self-flagged).

### 4.2 Deferred to the fix PRs

These statements are false only because the code is wrong. Correcting them before the fix
would publish the hole.

| Document | Statement | Updated in |
|---|---|---|
| SECURITY.md §3 | Revocation checked on every authenticated request; move "Reviewed as of" date after | P0-4 |
| SECURITY.md (new entries) | Threat model for connectors (local folder, S3, webhook) and MCP | P0-2, P0-3, P1-2 |
| PERMISSIONS.md | `/clear`, `local_folder` connector roles | P0-1, P0-3 |
| DEPLOYMENT.md, DEPLOYMENT_SCALEWAY.md, `docker-compose.nginx.yml` comment | "`*` is safe behind the bundled nginx" | P0-5 |
| CONFIGURATION.md, TROUBLESHOOTING.md | `MAX_CONTENT_LENGTH` as upload ceiling | P1-1 |
| CLAUDE.md Clark-Wilson | "a delete TP never issues DELETE FROM on a CDI" (violated by `/clear`) | P0-1 |
| CONFIGURATION.md | `TRUSTED_PROXY_IPS` guidance, `UVICORN_WORKERS` enforcement, CORS default | P0-5, P1-5, P1-4 |
| README | "Production-ready" claim | D7 |

### 4.3 Keeping it consistent

- Extend the pattern of `test_env_example_is_read.py`: every variable named in
  CONFIGURATION.md is read by code; every backticked `src/...` path in current docs exists;
  every documented `/api/...` endpoint exists (the audit script, productised).
- Split current-state and history documents (P2-7) so the tests can target current docs only.
- A dated "verified against commit" line at the top of each operator document, moved only by
  a PR that re-checks it.

---

## 5. Decisions

Defaults are my advice; P0 work starts once D1 and D2 are answered.

| ID | Question | Options | Advice and reasoning |
|---|---|---|---|
| D1 | Disclosure and sequence | **A** private GitHub security advisory with its temporary private fork for P0; docs branch merges now; LocalChat stays off public endpoints until P0 lands. **B** fix in public. | **A.** The repo is public and C1 is a one-request wipe. The docs branch contains nothing exploitable. |
| D2 | Installation-wide wipes (`/clear`, delete-all-memories) | **A** remove. **B** workspace-scoped soft delete for owners plus an admin-only installation purge with preconditions. **C** admin-only as is. | **B.** Keeps the UI feature, restores Clark-Wilson (retire versus destroy), removes the cross-workspace effect. |
| D3 | `local_folder` connector | **A** admin-only plus `CONNECTOR_LOCAL_ROOTS` allowlist, empty means disabled. **B** remove. | **A.** Keeps a useful on-premises feature with least privilege and safe default. |
| D4 | MCP servers | **A** remove until a deployment needs them. **B** add token auth and scope, keep off by default. | **A** unless you actively use them. They share the app's database singletons, so a correct fix is non-trivial, and they are off by default already. |
| D5 | S3 connector | **A** remove. **B** optional `boto3` extra with explicit credentials only and endpoint validation. | **A.** Consistent with ADR-4 keeping `boto3` out of the image; it cannot run as shipped anyway. |
| D6 | Env-var admin | **A** disabled once a database admin exists. **B** break-glass with strength check and every use logged. | **A.** A credential nobody can demote or disable is the wrong default; B is acceptable if you want recovery without database access. |
| D7 | README "production-ready" | **A** generic wording now ("hardened beta; see ROADMAP"). **B** leave until P0 merges. | **A.** The claim is inaccurate today and generic wording discloses nothing. |

---

## 6. Verification gaps

- Integration, e2e, perf and docker-smoke suites not run (no Postgres or Ollama in the
  sandbox). The unit suite ran: 2,914 tests, 2,913 passed, 1 failure caused by the sandbox
  (no `sentence_transformers`), 0 skipped.
- M3 (OAuth) not run end to end.
- #371's CI result not checked.
- The app was never run live with a browser.
