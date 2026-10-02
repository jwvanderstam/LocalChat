# Changelog

Notable changes to LocalChat. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file starts at v3.0.0-beta.1. Earlier work is in the commit history and, with the
reasoning attached, in [docs/LESSONS_LEARNED.md](docs/LESSONS_LEARNED.md).

## [Unreleased]

### Added

- **Row-level security on the workspace-owned tables** (ROADMAP P2-1b, database half).
  Migration `0017` puts a policy on ten tables — the seven carrying a `workspace_id`, plus
  `document_chunks`, `conversation_messages` and `annotations`, which borrow their parent's —
  keyed on a transaction-local `app.workspace_id`. Written with
  `set_config('app.workspace_id', %s, true)` rather than `SET LOCAL app.workspace_id = %s`,
  because `SET` is a utility statement that takes no bind parameter: the only way to write it
  is to interpolate the one value that decides what the caller can see.
  It also creates a `NOLOGIN` role to switch into, since RLS does not apply to a superuser or
  to a table's owner — without one every policy is inert while every test of it passes.
  `tests/integration/test_row_level_security.py` is the IVP: an unscoped transaction sees zero
  rows from all ten, a foreign scope sees zero, the owning scope sees its own. It creates and
  migrates its own database, because the shared CI one never has the Alembic chain applied and
  the module would otherwise have skipped there.
  **Inert for the application today**, which connects as the owner: the capability is built and
  tested but enforces nothing until the scope is set per transaction. That half needs the
  request scope bound on every guarded route rather than only the chat stream, and is written
  up in the ticket rather than half-done here.

- **ADR-5: workspace isolation is enforced in the database** (ROADMAP P2-1b-i). Records the
  decision for the application half of row-level security — the scope is *passed* to
  `get_connection(scope=)` by the method that already holds it, not bound in a contextvar —
  together with what that commits LocalChat to (shared-schema tenancy as the boundary; the
  operator as installation owner) and what it does not (a single node). The 18 by-id methods
  now hand their scope to the connection, and `test_object_authorization_matrix.py` fails any
  that does not. Migration `0018` grants the application identity `SET` on
  `localchat_scoped`, without which a managed database would refuse the role switch.
  **No behaviour change yet**: `get_connection` accepts the scope and does not act on it until
  the 34 methods still taking `workspace_id: str | None` — retrieval among them — are converted.

- **The object-authorization matrix now runs over HTTP against a real Postgres**
  (ROADMAP P2-2b). `tests/unit/test_object_authorization_matrix.py` walks the AST and
  proves no scoped database call omits `scope=`; every workspace test in
  `tests/integration/` was `MagicMock` throughout, so nothing reproduced the audit's C1
  and C2 the way they were found — through a request. This drives a plain user holding
  workspace A at workspace B's documents, chunks, conversations, memories, annotations,
  connectors and keys: 49 tests, 43 of them one route each.
  The route list is derived from `app.openapi()`, so a route added tomorrow is covered
  tomorrow — `app.routes` is unusable here because this FastAPI version leaves included
  routers wrapped as `_IncludedRouter` with `path=None`, and the naive walk finds zero
  routes while appearing to pass. An unclassified path parameter fails the run rather
  than dropping its routes, and the fixture proves its objects are reachable by their
  owner before any refusal counts, because a 404 is a passing result and an empty
  fixture would otherwise be a flawless green run over nothing. Verified non-vacuous by
  reintroducing C2 on one route: exactly one test went red, naming it.

- **`security-smoke`: the shipped compose, booted and then attacked** (ROADMAP P2-2a).
  Every existing job tests a mechanism in isolation — `test_proxy_trust_is_not_wildcarded`
  drives uvicorn's middleware in-process and has never seen nginx append a header, and
  `docker-smoke` boots `app` with no proxy in front of it. Nothing in CI had ever run the
  two files an operator actually deploys, together. This job boots `docker-compose.yml`
  with `docker-compose.nginx.yml` and `--profile mcp`, then probes over the wire: fifteen
  failed logins from fifteen forged `X-Forwarded-For` addresses must still be rate-limited
  (audit H3), and all three MCP servers must refuse a missing *and* a wrong bearer while
  answering a correct one (audit C3) — the last because with `MCP_AUTH_TOKEN` unset they
  refuse everything, so a refusal alone proves nothing about the token check.
  **Required on `main` since 2026-09-26**, once its own merge (`8e3e32b`) had given it the
  run on the default branch the ruleset needs before it can reference a check. Added ahead
  of the track record the ticket advised waiting for — a deliberate override, recorded in
  ROADMAP P2-2a and in CLAUDE.md beside `docker-smoke`'s and `perf-canary`'s entries. It is
  the only required check that boots eight containers and drives them through TLS, so it
  carries the most flake surface of the six; a probe is never relaxed to clear a red run.
- **`docker-compose.ci.yml`**, the third overlay the job needs, and
  `tests/unit/test_ci_overlay_is_narrow.py`, which stops it growing. Two things a
  GitHub-hosted runner cannot provide: the NVIDIA device reservations on `app` and
  `ollama` — Compose enforces those when it *starts* a container, so a GPU-less host fails
  with `could not select device driver "nvidia"` while `docker compose config` renders
  valid output throughout — and a 9.7 GB Ollama image on top of a ~10 GB app image with
  about 14 GB of runner disk. The overlay replaces exactly those and nothing else, because
  every key it grows is a key the job silently stops testing; the test pins its surface as
  an equality check so an unanticipated key fails too.
  A third runner constraint — `OLLAMA_CPU_LIMIT` 12 and `APP_CPU_LIMIT` 8 against a
  runner's 4 CPUs, which Docker refuses outright — is handled by setting the documented
  env knobs in the job, leaving the compose file itself untouched.

### Fixed

- **Two routes answered 200 for an object outside the caller's scope**, where P0-1's
  acceptance asks for 404. Neither disclosed anything — both scoped correctly — so this is
  a contract fix, not a leak being closed.
  `GET /api/conversations/{id}/documents` *intended* to refuse: it checks
  `if filenames is None`, and that branch was unreachable because
  `get_conversation_document_filter` was typed `list[str]` and returned `[]` for a missing
  row. It now returns `None` when no conversation is in scope, which is what the sibling
  `get_conversation_messages` has always done ("out of scope reads as not found"). Its one
  internal caller, `src/services/chat.py`, coalesces to `[]`: a conversation the scope
  cannot see means retrieval is unfiltered, as it was before any filter existed.
  `GET /api/chunks/{chunk_id}/annotations` now resolves the chunk through the already-scoped
  `get_chunk_by_id` and 404s when it is not in scope. `get_annotations_for_chunk` joins on
  the document's workspace and never leaked rows, but answering 200 for someone else's chunk
  still confirmed it exists, and left the route unable to say "no such chunk" at all.
  Found by P2-2b's matrix, which held both in `_DISCLOSES_NOTHING` with an assertion that
  their payload stayed empty. Fixing them made those assertions fail — which is what that
  mechanism is for — so the rows are gone and the refusal matrix now covers 45 routes rather
  than 43. Reverting either fix fails exactly its own case.

- **`docker compose --profile mcp up` could not start two of the three MCP servers.**
  The runtime image pins `ENV APP_ENV=production` (`Dockerfile`), so every container built
  from it is in production mode whatever compose says, and `src/config.py` raises
  `JWT_SECRET_KEY must be set in production!` at module import. No `mcp-*` service passed
  that variable — only `app` did. `mcp-local-docs` and `mcp-cloud-connectors` import
  `src.config` at module level and crash-looped on every start; `mcp-web-search` survived
  only because its `src` import is inside a function, and would have failed on the first
  search instead. All three now receive it.
  Found by booting the profile for `security-smoke` — no CI job had ever started it, the
  same blind spot that hid the exec-form defect in 2026-08. The cheap standing check is
  `tests/unit/test_compose_passes_production_required_vars.py`, which derives the required
  set from `config.py`'s own `raise` statements so a third variable fails there rather
  than in a container that will not start.

### Security

- **PyJWT 2.15.0 and urllib3 2.8.0**, for CVE-2026-101918 (PyJWT) and CVE-2026-97687, -97688
  and -97689 (urllib3). Newly published advisories that turned `pip-audit` red on `main` and on
  every open PR at once. urllib3 is transitive, so it moved by a targeted
  `pip-compile --upgrade-package`; nothing else in either lock changed. Dependabot's #401 carries
  the PyJWT bump but not urllib3, which is why this is its own change.

- **Row-level security is enforced** (ROADMAP P2-1b-iii, ADR-5). A workspace-scoped
  transaction now runs as `localchat_scoped` with `app.workspace_id` set, both
  transaction-local, so Postgres refuses every other workspace's rows even from a query that
  forgot its `WHERE` clause; `ALL_WORKSPACES` stays on the owner role. Memory search runs once
  per authorised workspace, since a scoped transaction sees one.
  **The role and its grants are re-applied at every boot**, not only by migration `0017`: a
  role is a cluster object that `pg_dump` never carries, so a restore into a new cluster left
  the database claiming 0017 had run while the role it created did not exist. Re-granting at
  boot also covers tables a later release adds.
  **The managed-Postgres restore recipe was broken on `main` since `0017`, and is fixed.** Its
  `GRANT ... TO localchat_scoped` names a role a new cluster does not have, so
  `pg_restore --exit-on-error` stopped with `role "localchat_scoped" does not exist`. The
  recipe in `OPERATIONS.md` gains `--no-privileges`; the application restores the grants when
  it starts. Verified end to end in a second, empty cluster: a non-superuser identity with
  `CREATEROLE` restored the dump, booted, created the role, and served a scoped query.
  `restore-proof` found the first half of this — an `ALTER DEFAULT PRIVILEGES` this PR briefly
  added cannot be restored by a non-superuser at all — and now asserts the re-grant.
  Measuring the cost found a recall regression the tests could not: under the policy Postgres
  swaps the exact per-workspace vector scan for the HNSW index filtered afterwards, and top-40
  semantic search returned 19 rows on average, as few as 0. Scoped transactions therefore also
  set `hnsw.iterative_scan = strict_order` and `hnsw.ef_search = 400` — all 40 rows, 92%
  overlap with the exact answer, 3.8 ms median against 9.1 ms before. This requires
  **pgvector 0.8 or later**; an older one refuses the setting and scoped queries fail loudly.
  `tests/integration/test_row_level_security.py` proves each part against Postgres and fails
  with it removed.

- **`GET /api/status` reported any workspace's document count.** Status requires only a
  session, and counted documents for whatever `X-Workspace-ID` named — so a caller could read
  the count of a workspace they are not a member of, or of the whole installation by sending
  no header. A count, not content; found because converting the call to `get_scope(request)`
  refused on a route no workspace guard had run on. Status now runs the check without
  requiring it to pass: an authorised caller gets their scope's count, anyone else gets 0,
  and the status bar still renders.

- **Chat retrieved from any workspace named in `additional_workspace_ids`.** The workspace
  guard on `POST /api/chat` authorised the request's own workspace and nothing else; the
  extra ids from the request body went straight into document retrieval (one pipeline run
  per id) and into long-term memory search, and what they found reached the prompt, the
  answer and the streamed `sources`. Any user who knew another workspace's id could read
  from it through chat — and so could a **workspace API key**, whose scope
  `WORKSPACE_API_KEYS.md` documents as impossible to widen. Workspace ids are UUIDs, so this
  needed one; the audit graded the same "reachable by UUID" shape as C2. Reproduced at the
  route layer before the fix: a plain user's request carried a foreign id into
  `retrieve_context` and was answered with 200. Each extra id is now authorised like the
  primary one — membership at viewer or above, admins any, an API key none — and one
  unauthorised id refuses the whole request with 403 rather than being dropped, so a caller
  cannot mistake a partial answer for a complete one. No frontend sends the field.
  P2-2b's over-the-wire matrix did not see it because it addresses objects by **path**
  parameter; this one arrived in the body.

- **`POST /api/documents/test` returned chunk previews from every workspace.** The
  retrieval-diagnostics route is open to viewers, and called `retrieve_context` with no
  workspace — which reads as every workspace — so any viewer could query the whole
  installation and receive the first 200 characters of each matching chunk, with filename
  and page. It now searches the workspace the guard authorised, as its neighbours do.

- **The `list_documents` LLM tool listed every workspace's documents.** It called
  `db.get_all_documents()` with no argument, which reads as installation-wide, so any
  chat user could ask the model what documents exist and get back other workspaces'
  filenames, chunk counts and upload dates — metadata, not content, but the C1/C2 class.
  Tool calling is on by default (`TOOL_CALLING_ENABLED=true`), so this was reachable as
  shipped. It now reads the request's scope the way its sibling `search_documents` has
  since P0-2, and refuses when none is bound. Found while sorting the
  `workspace_id: str | None` methods for P2-1b-ii; not in the September audit, whose
  static scan covered routes rather than tools.

- **`python-jose` replaced by `PyJWT`** (ROADMAP P2-6). The old library pulled `ecdsa`,
  whose timing side-channel has no upstream fix and had been an accepted risk in
  SECURITY.md §2 with a `pip-audit --ignore-vuln` suppression holding CI green. PyJWT
  signs HS256 over `hmac`/`hashlib` and pulls nothing, so `ecdsa`, `rsa` and `pyasn1`
  are gone from both locks and from the image, the suppression is gone with them, and
  that step now runs with none at all. Same algorithm and same claims, so tokens issued
  before the swap still verify — `tests/unit/test_jwt_library_is_pyjwt.py` pins that
  against a token minted by jose before it was uninstalled, which is evidence that
  cannot be reproduced afterwards.

### Changed

- **"Every workspace" is now a value you pass, never a default you fall into**
  (ROADMAP P2-1b-ii). Fifteen database methods took `workspace_id: str | None = None` and
  read `None` as every workspace — the pattern P0-1 removed from the by-id paths, still
  present on the listings, the counts, and retrieval itself (`search_similar_chunks`,
  `search_lexical_chunks`, `search_memories`). Each now takes a mandatory keyword-only
  `scope: Scope`, builds its SQL through `scope_predicate` (which refuses `None` and `""` at
  runtime), and hands the scope to `get_connection(scope=)`; the retrieval chain above them
  (`retrieve_context`, `MemoryRetriever.retrieve`, `suggest_documents`, chat's
  `retrieve_contexts`) takes a `Scope` too, so the translation happens once, at the route,
  through `get_scope(request)`. **Behaviour is unchanged** by construction: every place that
  passed `None` now passes `ALL_WORKSPACES` where a reviewer can see it — SyncWorker's stale
  sweep, connector loading, the boot-time count, the admin stats, and the two token-authenticated
  MCP `list_sources` calls. `test_object_authorization_matrix.py` lists all 33 scoped methods,
  fails any call that omits the scope, and fails any that opens a connection without it.
  Not converted, deliberately: `document_exists` and the five inserts take the workspace a row
  is *written to*, where `None` means "no workspace", not "every workspace"; and the thirteen
  methods in `workspaces.py` and `workspace_keys.py` take the workspace itself as the object.

- **No production `assert`** (ROADMAP P2-4a). All 27 in `src/` were mypy type-narrowing
  invariants — `row is not None` after an `INSERT ... RETURNING`, `_pypdf is not None`
  behind an `AVAILABLE` flag — and `python -O` discards every one of them, which would turn
  a named, located invariant into an `AttributeError` somewhere downstream. Each is now
  `if <cond>: raise AssertionError(<the same message>)`: same exception type, same text,
  and the interpreter can no longer drop it. `S101` is selected in `pyproject.toml` so
  `ruff check .` holds the line, with `tests/**` still exempt.
  Nothing here runs `python -O` or sets `PYTHONOPTIMIZE` — not the Dockerfile, the
  entrypoint, compose or any workflow — so this closed a latent hole rather than a live
  one. Recorded that way on purpose: the reason to fix it is that the invariants were
  written in the one form the shipping interpreter may discard, not that they were being
  discarded.

### Documentation

- **P2-1b's pooler precondition is settled, with the probe committed** as
  `tests/integration/test_set_local_scope_mechanism.py`. The ticket had asked whether a
  per-transaction workspace scope would be dropped behind a pooler the way
  `hnsw.ef_search` is. It is not, and the difference is the mechanism: `ef_search` is a
  session-level `SET` made once per physical connection that every later transaction
  depends on; a transaction-local scope cannot outlive its own transaction, and a
  transaction-pooling proxy holds one server connection for the whole of a transaction by
  definition. Two implementation findings came out of running it — `SET LOCAL x = %s`
  takes no bind parameter, so `set_config(..., true)` is the form that avoids
  interpolating the value that decides visibility; and RLS is inert for a superuser or the
  table owner, so the app must connect as neither.
- **`_warn_if_ef_search_did_not_stick` no longer explains the failure with a mechanism
  that was corrected months ago.** Its docstring said a transaction pooler resets session
  state between transactions. DEPLOYMENT_SCALEWAY.md §4 established that pgbouncer does
  not reset it, it *leaks* it between clients — which is why a passing read-back is not a
  clean bill of health. That correction never reached the code.

- **P2-2's prerequisites are established by trying them, not by reading.** The shipped TLS
  overlay **cannot boot**: `nginx/certs/` does not exist in the repository and
  `docker-compose.nginx.yml` mounts it, so nginx refuses at config load with
  `cannot load certificate`. A CI job that boots the overlay has to generate a throwaway
  self-signed pair first. Also recorded: the probe should send `Host: YOUR_DOMAIN` rather
  than rewrite the config it is meant to verify, and `--profile mcp` needs
  `MCP_AUTH_TOKEN` actually set — with it empty the servers refuse every call regardless,
  so the token test would pass without testing the token.

- **TROUBLESHOOTING names the `build-and-push` transient that reads like a broken pin.**
  A ~30-second failure resolving the hardened base digest (`unexpected media type
  application/octet-stream … not found`) is not an expired digest: `docker-smoke` builds
  from the identical digest on every PR and was green on the same commit minutes later,
  and a re-run of the failing job built cleanly with no change. The entry says to re-run
  first, records that a local `docker manifest inspect` reports a failure that looks like
  confirmation and is not, and names anonymous-pull throttling as the hypothesis with the
  authenticated-pull fix behind a credentials decision. Written because an hour and a
  withdrawn PR went into re-pinning digests that were never broken.

- **`except Exception` is now an argument rather than a reflex** (ROADMAP P2-4b). `BLE001`
  is selected in `pyproject.toml` and every one of the 120 sites in `src/` was read rather
  than swept. **4 were narrowed** — three connectors and `oauth_tokens` parse an ISO-8601
  string out of a JSON payload and now catch `(ValueError, TypeError, AttributeError)`, so
  an unexpected error surfaces instead of being absorbed. **11 were failing silently** —
  `pass` or a bare fallback with no record whatsoever — and gained a
  `logger.debug(..., exc_info=True)`; one of them, the settings page handler, had no logger
  in the module at all and would have rendered an empty admin panel with nothing anywhere
  saying why. The rest carry `# noqa: BLE001 — <reason>` naming what degrades and to what.
  `tests/**` and `scripts/**` are exempted with a stated reason; `mcp_servers/` is held to
  the same standard as `src/`.
  Worth recording what the measurement showed, because it contradicts the ticket's framing:
  of the 237 `except Exception` handlers in `src/`, **195 already logged** — ruff exempts a
  handler that calls `logging.exception` or re-raises, which is why only 120 were flagged.
  The codebase was not careless. The 15 handlers that were genuinely wrong are the value
  here; the other 105 comments are the price of a rule that makes the next one deliberate.

- **Dependabot watches the Dockerfile's base images.** `.github/dependabot.yml` declared
  `pip` and `github-actions` and nothing else, so both hardened base digests sat untouched
  from #287 (2026-08-19) with nothing ever proposing a newer one — 33 days on an image
  whose whole selling point is that it is rebuilt continuously for CVE patching. Grouped,
  because the builder and runtime stages are the same upstream image and are only correct
  together. The digests themselves are current and were not changed: `docker-smoke` builds
  from them on every PR and has stayed green throughout.

- **The configuration example and reference say only true things** (remediation plan
  §4.1, redone rather than merged from the audit's bundle). `.env.example` carried 29
  variables nothing reads — an SMTP block, gunicorn `WORKERS`, `DEBUG`, `HOST`/`PORT`
  where the code reads `SERVER_HOST`/`SERVER_PORT` — and four values that silently
  overrode the code's defaults (`CHUNK_SIZE=768` against 1200). Rewritten;
  `tests/unit/test_env_example_is_read.py` fails on a dead variable or a drifted value,
  and on a CONFIGURATION.md reference row nothing reads. CONFIGURATION.md gains
  `UVICORN_TIMEOUT` (keep-alive, not a request timeout), `SERVER_*` and `BIND_*`, and the
  real OAuth redirect defaults. TROUBLESHOOTING named three settings that do not exist;
  OPERATIONS described Kubernetes deployments there are none of; SECURITY §5 and ADR-3 had
  `onnxruntime` at a pin Dependabot moved a week ago; SECURITY §4 cited the unbuilt plugin
  contract as a control. README's quick start now says which five values compose refuses
  to start without, and no longer promises a generated password Docker cannot produce.
  CLAUDE.md names every ingested format, the real `conversation_messages` table, and which
  CDI tables lack `deleted_by`. The lint command in both is `ruff check .`, as CI runs it.
- **The audit's P2 tier is scheduled** — ROADMAP Initiative 10, Sprints 15–18, one ticket
  per row of the plan with what has already shipped marked (P2-1a with P0-1; P2-8 by
  decision).
- **The September 2026 remediation plan is in the repository** as
  [docs/REMEDIATION_PLAN.md](docs/REMEDIATION_PLAN.md), now that every fix it withheld
  publication for has shipped. The text is as written on 2026-09-16; a banner maps each
  ticket and decision to where it landed and names what is still open. What the episode
  taught is [LESSONS_LEARNED Ch. 20](docs/LESSONS_LEARNED.md).

## [3.1.0] — 2026-09-17

The security release. A September 2026 external audit of the v3.0.0 code returned
findings graded critical to medium (C1–C4, H1–H4, M1–M8), the worst of them one shape: the
guard authorised the caller against *their own* workspace, and the query then acted on an
object in *any* workspace. Every P0 and P1 ticket of the remediation plan is closed
here, in one PR (#380), and each entry below names the finding it closes. The
residuals that were accepted rather than fixed are recorded as entries 9 and 10 of
[SECURITY.md](SECURITY.md).

The rest is what running the product on a real cloud host for the first time turned
up — a health check that stayed green through a database outage, a pool that handed
out closed connections, a stack that could not chat and did not say so — plus the
Scaleway scripts that made that deployment repeatable.

### Security

- **Object-level authorization on every route that addresses an object by id** (P0-1,
  external audit findings C1 and C2). The workspace guard authorised the caller against
  *their own* workspace and the database call then acted on an object in *any* workspace.
  The worst case, `DELETE /api/documents/clear`, hard-deleted every document and chunk in
  the installation for any user holding `editor` in any workspace — and any user can
  create one. Also affected: chunk text search and chunk-context reads across all
  workspaces, single-document retire, delete-all-memories, and update/delete of
  conversations, memories, annotations and connectors by id.
  - Database methods that reach a workspace-owned object now take a mandatory
    keyword-only `scope`, and `src/utils/scope.py` removes `None` as a value for it:
    a scope is a workspace id or the explicit `ALL_WORKSPACES`. Forgetting the argument
    is a `TypeError`, and passing `None` a `ValueError`, where it used to mean
    "every workspace".
  - `check_workspace_access` now pins the authorised scope for all three principals,
    including the global-admin path, which previously returned without pinning anything
    and so left the query unscoped.
  - `tests/unit/test_object_authorization_matrix.py` walks the AST of `src/` and fails on
    any call that omits the scope, so a newly added route cannot repeat the pattern.
- **`DELETE /api/documents/clear` retires instead of destroying, within one workspace**
  (decision D2). It requires `owner`, sets `deleted_at`/`deleted_by`, and touches only the
  caller's workspace. The irreversible operation moved to a separate admin-only
  `DELETE /api/documents/purge-all`, which acts only on documents already retired. This
  restores the Clark-Wilson rule the old endpoint broke outright: a delete TP never issues
  `DELETE FROM` on a CDI, and destroy is a distinct, explicitly authorised TP.
  `DELETE /api/memory/` is likewise `owner` and workspace-scoped.

- **A URL the application is asked to fetch can no longer point inward** (P1-2, audit
  finding M4). Two places retrieve a URL supplied from outside — the web-search result
  fetcher and the webhook connector — and both guarded it by inspecting the hostname
  *string*. An IP literal in a private range was refused; a DNS name was waved through, with
  a comment in the source admitting the check could not resolve it. So a name pointing at
  `10.0.0.5`, or a bare compose service name, was fetched by a process sitting on the same
  network as the database and the model server.
  - `src/utils/safe_fetch.py` is now the one way either fetches. It resolves the name and
    refuses if **any** address it answers with is non-public — so a round-robin record
    cannot be retried until the public answer wins — re-validates every redirect hop, and
    caps the body and the time. Neither path had any cap, and neither re-checked redirects,
    which made the first check decorative.
  - **The webhook secret is mandatory**, at creation as well as at delivery, must be at
    least 16 characters, and is compared with `hmac.compare_digest`. It was optional — a
    connector without one accepted anything that knew its id — and compared with `!=`.
  - The rebinding residual this does not close is recorded in SECURITY.md §9.

- **Connecting a Microsoft or Google account works in a browser, and the flow uses PKCE**
  (P1-3, audit finding M3). The callback resolved the user from the session — but it is
  reached by a redirect *from the provider*, which is a cross-site navigation, and the
  session cookie is `SameSite=strict`. No cookie was sent, so the callback returned **401
  after exchanging the authorization code**: the code was spent, the account was never
  connected, and retrying required starting over.
  - The `state` now carries the user who began the flow, so the callback needs no cookie.
    It also carries an expiry (10 minutes) — entries were previously kept for the life of
    the process and never pruned — and is single-use, not interchangeable between
    providers, and consumed even when rejected so it cannot be probed and retried.
  - **PKCE (S256)** is added to both flows. Without it, anyone who intercepts the redirect
    — a shoulder-surfed URL, a leaky proxy, browser history — can exchange the code for a
    token.
- **Three destructive actions used the native `confirm()` dialog** — deleting a model and
  the two memory-clearing actions. `repo-hygiene` has banned that since a QA pass lost a
  document to one, but the calls sat in inline `<script>` blocks where the check could not
  see them. Extracting those blocks for the CSP surfaced all three; they now use the
  application's own confirmation modal.

- **Every response now carries security headers, and CORS cannot fall back to a
  wildcard** (P1-4, audit findings M6 and M8). The application sent no
  `Content-Security-Policy`, `X-Content-Type-Options`, `Referrer-Policy` or framing
  header at all, and neither did nginx.
  - A CSP that bans objects, pins `base-uri` and `form-action`, denies framing, limits
    scripts to this origin plus the one CDN the pages use, and **does not allow inline
    scripts**. Getting there meant extracting ~680 lines of inline JavaScript from three
    templates into `statusbar.js`, `models.js` and `settings-page.js`, and replacing all
    nineteen inline `on*=` handlers — fifteen in templates, four in markup generated by
    JavaScript — with listeners and event delegation.
  - One inline script remains by design: the theme applier in the `<head>` of `base.html`
    and `login.html`, which must run before first paint or every navigation flashes the
    wrong theme. CSP permits exactly it, **by hash**; a test recomputes that hash from the
    templates so the two cannot drift apart silently.
  - `style-src` still allows inline styles. 43 `style=` attributes across the templates,
    and none of them is a lever for executing code — recorded in the tests rather than left
    looking like an oversight.
  - `repo-hygiene` now fails on a new inline `on*=` handler or a third inline `<script>`,
    because under this policy both are silently dead markup rather than a visible error.
  - `Strict-Transport-Security` only over TLS, so a development server cannot pin a
    developer's `localhost` to HTTPS.
  - nginx repeats them with `always`, because it answers some responses itself — a 413, a
    502, its own error pages — and those never reach the application's middleware.
  - **CORS**: the default origins were `localhost,127.0.0.1`, which carry no scheme and so
    match no browser `Origin` header — the default permitted nothing while appearing to
    permit something. They now carry schemes, a scheme-less entry aborts the boot, and the
    `allow_origins=["*"]` fallback is gone: with `allow_credentials=True` it let any site
    make authenticated cross-origin calls, and an empty `CORS_ORIGINS` reached it by
    accident rather than by anyone choosing it. Nothing configured now means CORS stays off.

- **One upload can no longer read or delete another's file, and none is unbounded**
  (P1-1, audit findings H4 and M2). Every upload was written to
  `UPLOAD_FOLDER/<sanitized name>`, so two workspaces uploading `report.pdf` shared one
  path: one overwrote the other, one ingest could read the other's bytes, and whichever
  finished first deleted the file the other was still using. Each upload now stages into
  its own directory — a directory rather than `mkstemp` because the ingest takes the
  document's name from the file's basename, and a randomised filename would land in the
  library.
  - `MAX_CONTENT_LENGTH` is **enforced**, having been a Flask-era value applied to nothing:
    the body streams to disk in 1 MB chunks and is refused with **413** the moment it passes
    the limit, instead of being read into memory whole. `nginx.conf` gains a matching
    `client_max_body_size`, without which the proxy's own 1 MB default would silently
    override it.
  - The read and the write were also being done inline in an async route, so one large
    upload held the event loop for its whole duration. They now run in the threadpool.
- **More than one uvicorn worker aborts the boot** (P1-5, audit finding M7). `AppState`, the
  metrics collector, the rate limiter's counters, the revocation cache, the Alembic runner,
  connector polling and the reranker's scheduler are all in process memory with no
  coordination, so a second worker did not fail — it diverged silently, with two rate-limit
  budgets and an OAuth callback unable to find the state the other worker stored. Refused in
  every environment, because the failure is not production-specific.

- **Enabling the MCP servers no longer removes workspace isolation, and they are no
  longer open** (P0-2, audit finding C3, decision D4). Three holes that were only
  exploitable together:
  - `get_rag_context` **dropped `workspace_id`** when `MCP_ENABLED=true` and returned the
    MCP result, so turning the flag on silently un-scoped chat retrieval.
  - The MCP `search` tool **could not accept a workspace at all**, and retrieval reads a
    missing workspace as *every* workspace. It is now required, by the handler and by the
    schema the model is given, on both servers that retrieve.
  - The servers had **no authentication of any kind** — whatever reached `POST /mcp` was
    served, by a process sitting on the `backend` network with the database. They now
    require an `MCP_AUTH_TOKEN` bearer, compared in constant time.
  - Unset fails closed in three places rather than one: the servers refuse every call, the
    app refuses to boot with `MCP_ENABLED=true`, and `get_rag_context` falls through to the
    direct (scoped) path rather than calling an unscoped search.
  - The LLM's own document-search tools (`search_documents`, `ToolRouter._local_docs`) had
    the same hole and no argument to fix it with, since the model calls them mid-answer.
    They now read the workspace the request bound, and **raise** when nothing bound one.

- **Rate limiting can no longer be bypassed behind the bundled nginx** (P0-5, audit
  finding H3). The TLS overlay shipped `TRUSTED_PROXY_IPS: "*"` while `nginx.conf` set the
  header with `$proxy_add_x_forwarded_for`. Together those are a bypass: `*` makes uvicorn
  trust every peer and take the **leftmost** `X-Forwarded-For` entry, and
  `$proxy_add_x_forwarded_for` *appends* to whatever the caller already sent — so a request
  carrying its own header chose its own rate-limit key, and **login brute force was
  unthrottled on the one path that faces the internet**. The overlay's comment had argued
  the wildcard was safe because nginx is the sole ingress; the header is forged by the
  external client, which that reasoning did not cover.
  - nginx now sends `$remote_addr`, discarding anything the caller supplied, and the
    overlay pins the `frontend` network to `172.31.240.0/24` and trusts only that. Either
    half alone closes it; both are in place because they can be changed independently.
  - **Fronting this nginx with another proxy reverses the first half** — see the note in
    `DEPLOYMENT.md`.


- **One authentication resolver, so revocation and the current role apply everywhere**
  (P0-4, audit findings H1, H2 and M1, decision D6). Three guards each answered "who is
  this?" their own way, and two of them answered it badly.
  - **H1**: only `require_auth` checked the revocation deny-list. `check_workspace_access`
    (every document, chat, memory, feedback, annotation and connector route) and
    `require_admin_dep` (31 admin routes) never did, so a **revoked token kept working on
    all of them** until it expired. SECURITY.md §3 had claimed the check ran on every
    authenticated request since before it was true.
  - **H2**: `check_workspace_access` read `role` from the JWT, which is minted at login and
    lives as long as the token — so a **demoted administrator kept the global short-circuit**,
    and with it owner-equivalent access to every workspace. The role now comes from the
    database on every request, which also means a *promoted* user gets access without
    signing in again.
  - **M1**: the `ADMIN_PASSWORD` account was a permanent second credential that nobody could
    see, demote or disable, and it kept working beside a changed database password. It is now
    a **bootstrap credential**: valid only while the database holds no live administrator,
    which a normal boot ends on first start. The one case left open — an unreadable database,
    where the question cannot be answered — is recorded in SECURITY.md §7 rather than
    silently kept.
  - `resolve_principal()` is the single answer all three call. An AST test fails if any guard
    reads the `role` claim again.

- **The `local_folder` connector is confined, and creating one is an administrator's
  decision** (P0-3, audit finding C4, decision D3). Any user can create a workspace and
  become its owner, and `ws:owner` was the only check on creating a connector — so any user
  could point one at any path the server process could read, `/etc` included, and then ask
  questions about the contents. Two independent conditions now apply: creating *or
  reconfiguring* a `local_folder` connector requires a global administrator, and its path
  must resolve inside the new `CONNECTOR_LOCAL_ROOTS` allowlist, which is **empty by default
  and therefore disables the connector type**. Paths are resolved with `realpath` and
  compared by whole components, so `..`, a symlink pointing out of an allowed root, and a
  sibling directory sharing a prefix all fail.
  - `PUT /api/connectors/{id}` was the same finding through another door: it wrote a new
    `config` with no validation and no re-authorisation, so an owner could repoint a
    connector an administrator had created. A config change now faces both checks.

### Added

- **Scaleway deployment, scripted end to end** (#353–#359, #363, #368, #373, #376).
  `scripts/scaleway/` provisions the project, the Serverless SQL Database and a
  project-scoped IAM identity (`provision.sh`), deploys the container
  (`deploy_container.sh`), the private network and an Ollama instance behind an
  inbound-drop security group (`deploy_embeddings.sh`), gates the result
  (`verify_deployment.py`, `verify_database.py`), and tears it all down most-expensive-first
  (`panic_teardown.sh` — dry run unless `CONFIRM=DESTROY`). Every script is idempotent, and
  each has a unit test of its decisions against a recording `scw` shim. Documented in
  [DEPLOYMENT_SCALEWAY.md](docs/DEPLOYMENT_SCALEWAY.md), with one log entry per session in
  [DEPLOYMENT_LOG.md](docs/DEPLOYMENT_LOG.md).

### Fixed

- **`/api/health` reports the database it can reach now, not the one it reached at boot**
  (#357). It echoed `startup_status['database']` and stayed green through a total outage.
  It now runs a query through the pool, with a 5 s TTL.
- **The pool no longer hands out a connection the server already closed** (#361). Both pool
  constructions — the normal one and the database-does-not-exist recovery path — now pass
  `check`; an integration test kills the pool's backends with `pg_terminate_backend` and
  proves the next caller still gets a working connection.
- **An embedding model can no longer become the active chat model** (#369). The candidate
  filter fell back to the unfiltered list, which made `nomic-embed-text` the chat model on
  any host holding only embedders and turned every chat into an opaque `GenerationError`.
  `/api/status` now reports `ready: false` when no model can chat; `/api/health` stays
  healthy on purpose, so no container is restarted for it.
- **Setting `METRICS_TOKEN` no longer blinds the admin dashboard** (#366). The metrics
  endpoints admitted the scraper's bearer and nothing else; an admin session cookie is
  now accepted too.
- **Staged uploads an interrupted ingest left behind are cleared at startup** (#362).
- **Static assets are referenced root-relative, not through `url_for`** (#364). Starlette's
  `url_for` returns an absolute URL carrying the scheme the app thinks it serves — `http`
  behind a TLS-terminating proxy — and the browser then blocked every stylesheet and script
  as mixed content.
- **The Docs viewer resolves cross-document links** (#374) — `[X](X.md)` rendered as
  `/docs/X.md`, which nothing serves — **and keeps the document list in view while the
  content scrolls** (#375).
- **The nginx TLS overlay could not reach the application.** `nginx` declared no
  `networks:`, so it joined the implicit `default` network while `app` is on
  `frontend`/`backend` — `proxy_pass http://app:5000` had no DNS entry to resolve. Found
  while fixing H3 above, by reading `docker compose config` rather than the file. It now
  joins `frontend`.

### Changed

- **The cloud fallback will target OpenAI-compatible endpoints directly rather than through
  `litellm`** ([ADR-4](docs/ADR.md)). `litellm` is held at 1.97.0: 1.98.0 hard-depends on
  `boto3`, which put the AWS SDK into the image of a sovereignty-scoped appliance in order
  to reach Bedrock this deployment will never call. The fallback capability is unchanged;
  the multi-provider adapter is what goes. Caught by
  `test_raises_import_error_without_boto3`, which failed because `boto3` was no longer
  absent.
- Dependency bumps taken alongside it: `cryptography` 50.0.1, `spacy` 3.8.16, `pypdf`
  6.16.2, `ddgs` 9.16.0, and `responses` 0.26.3 in the dev lock.

### Removed

- **The S3 connector** (P1-2, audit finding M5, decision D5). It accepted an owner-supplied
  `endpoint_url` and fell back to the server's own AWS credentials when none were given —
  and it could not run in the shipped image at all, because `boto3` is deliberately absent
  ([ADR-4](docs/ADR.md)). Anyone using it was on a host install with `boto3` added by hand;
  for them this is a removal, and for every containerised deployment it removes a
  credential-fallback path that never worked. `src/connectors/s3_connector.py`, its tests,
  its registry entry and its documentation all go.
- **`gunicorn`**, a runtime dependency nothing invoked — every service is uvicorn — along
  with the `GUNICORN_TIMEOUT` constant no code consumed, its `.env.example` line and its
  `CONFIGURATION.md` row. The three had drifted to different values (300, 600, 600), which
  is what an unused setting does. ROADMAP's accepted-debt entry named the next
  `pip-compile` run as the trigger; this was that run.

## [3.0.0] — 2026-08-31

The stable release. `3.0.0-beta.1` shipped on 2026-08-26 with seven of the eight
[PRODUCTION_PLAN](docs/PRODUCTION_PLAN.md) exit criteria met; the eighth — migrations
executed against a real database in CI, not merely written — closed on 2026-08-27, and
the hardening gate was lifted on 2026-08-31. The scope is unchanged and is the point:
a single-node, self-hosted appliance for a team of 25 or fewer, per [ADR-1](docs/ADR.md).

Dated ahead of the tag, as `3.0.0-beta.1` was in #331.

The substance of the v3.0 cycle is in the beta entry below; this section covers what
changed between the two.

### Fixed

- **PowerPoint ingest did not work for any real deck.** `_process_pptx_slide`'s title
  guard called `hasattr()` on a python-pptx property whose getter raises `ValueError` —
  and `hasattr` swallows only `AttributeError`, so the probe written to make the access
  safe was itself what raised. Any deck leading with a plain textbox rather than a title
  placeholder — which is every deck from a corporate template — failed to load entirely.
  Slide **tables** were also dropped, being `GraphicFrame`s rather than text frames, so a
  deck whose substance is tabular ingested "successfully" with the substance missing.
  Found by running the retrieval eval against real documents for the first time; 5 of 5
  business decks had been failing.
- **A connection pooler silently dropping `hnsw.ef_search` now warns** instead of quietly
  degrading recall (#336).
- **A pgvector dumper registered for `list` broke every `= ANY(%s)` query** — the document
  filename filter, `source_ids`, and GraphRAG's entity lookup (#342).
- **The `mcp` compose profile could not start against the hardened image** (#341).
- **The retrieval eval harness could not read the corpus its own ticket asks for** —
  `--corpus` accepted any directory but only ever ingested `*.md`, so a real document set
  scored against an empty database with no warning.

### Changed

- **Dependency locks are `pip-compile` output**, with test tooling split out of the runtime
  image (#335).
- **GraphRAG (DEL-2) is deferred, not deleted** — measured on a real-world corpus: 1-hop
  expansion fires on at most 2 questions in 20 and changes no ranking when it does. It is
  off by default. See `docs/PRODUCTION_PLAN.md` for the numbers and the re-review trigger.

### Removed

- **The Kuzu graph backend** (#345). It was reachable only via `GRAPH_BACKEND=kuzu`, had no
  route and no caller outside the factory; `PostgresGraphStore` is the only backend.

### Documentation

- **The production-hardening gate is lifted** (2026-08-31): all eight exit criteria green,
  ROADMAP Sprints 8–14 un-queued, and the README now claims production-readiness for
  ADR-1's scope rather than "production-patterned".
- The production topology, the wiki closure, and a document-wide re-derivation from the
  code (#337, #339, #340, #343, #344).
- One note recorded rather than buried: answering DEL-2 meant exercising the product on
  real documents for the first time, and that found three defects in an afternoon — two of
  them in an advertised supported format — that eight criteria of mechanical verification
  did not. See the gate banner in PRODUCTION_PLAN.

## [3.0.0-beta.1] — 2026-08-26

The v3.0 cycle: 19 June – 26 August 2026, 89 feature and fix commits, ~1,074 commits on
`main` in total.

A beta, deliberately. [ADR-1](docs/ADR.md) scopes LocalChat to a single-node, self-hosted
appliance for 25 users or fewer, and [PRODUCTION_PLAN](docs/PRODUCTION_PLAN.md) lists eight
conditions that gate the stable claim. Seven held at the time of this release; the
eighth closed on 2026-08-27 and the gate was lifted on 2026-08-31.

### Security

- **Authentication exists.** There was no login route; 82 routes were guarded against a
  session nobody could obtain. Local login, an httpOnly session cookie, user management,
  and self-service password change.
- **Fail-closed boot.** `DEMO_MODE` and the empty-`ADMIN_PASSWORD` bypass are deleted, not
  flagged off. No configuration path leaves `APP_ENV=production` running with
  authorisation off; the app seeds a dev admin instead.
- **Token revocation is enforced.** `_verify_jti_not_revoked()` silently passed when the
  database was unreachable — a revoked token worked during an outage. It now fails closed.
- **Rate limiting keys on the real client** and covers more than the login route.
- **`ENCRYPTION_KEY` is required**, and the encryption that silently did nothing is gone.
- **Authorisation by default.** A route table walk fails CI on any route that is neither
  guarded nor explicitly allowlisted; 49 of 102 routes had no check at all when the audit
  ran. The permission matrix is generated from the handlers, in [PERMISSIONS.md](docs/PERMISSIONS.md).
- **Workspace roles are enforced** — `viewer`/`editor`/`owner` wired into 33 routes across
  six routers, with `create_workspace` recording its creator as owner in the same
  transaction.
- **A connector spends its creator's OAuth token, nobody else's.** Which token to use came
  from client-supplied config on a `ws:owner` route, so any workspace owner could name
  another user's UUID and sync that person's Drive into a workspace they controlled.

### Data integrity

- **Clark-Wilson soft delete across all nine constrained data items** — documents, chunks,
  conversations, messages, users, workspaces, memories, annotations, connectors. A delete
  sets `deleted_at`; purge is a separate, admin-only operation with preconditions, so a
  citation never points at a row that vanished.
- **Migrations are executed, not merely written.** CI applies the full chain to an empty
  database and proves it idempotent. A duplicate revision id had previously made a
  backfill unreachable on every database.
- **Restore is proven, and the runbook it disproved is corrected.** `OPERATIONS.md` warned
  that the `vector` extension had to exist before restoring; it does not — `pg_dump` writes
  `CREATE EXTENSION` into the archive. The case that genuinely needs preparation, a
  non-superuser restore to managed Postgres, was not named at all and needs two further
  flags. Both paths are documented and asserted in CI.

### Retrieval and models

- **Hybrid search** — independent semantic (pgvector) and lexical (tsvector/GIN) arms with
  a weighted blend, and a cross-encoder reranker that now *drops* the chunks it rejects
  rather than merely ranking them low.
- **Environment-aware model availability.** Models that do not fit the hardware are shown
  with the reason rather than silently offered; a replaced model is unloaded.
- **A retrieval eval set** — 20 question/source pairs with a harness that scores recall@1,
  recall@5 and MRR, and refuses to report a comparison when the feature under test never
  fired.
- **Long-term memory is scoped to its workspace.** It was not, and one workspace's memories
  reached another's answers.
- **Web-search results reach citations.** They were used to ground answers and then dropped
  from the sources panel.

### Interface

- **Redesigned around one accent, hairlines and type.** Gradients, hover lifts, two-layer
  shadows, filled status badges and the card-inside-card nesting are removed rather than
  restyled. Chat turns read as one column under speaker labels at a 680px measure;
  citations are numbered footnotes rather than a collapsed disclosure; Settings moves from
  seven horizontal tabs above fourteen cards to a rail with one pane at a time. Light and
  dark from a single token set. Design sources in [design/](design/).
- **Icons are drawn, not typed.** The emoji that stood in for icons are inline SVG that
  inherit the theme, and CI refuses their return.
- **An admin log viewer**, workspace API keys manageable from the Users screen, and an
  in-app confirmation dialog for every destructive action.

### Operations

- **The image is distroless and hardened** — Docker Hardened Images, digest-pinned, no
  shell, no package manager, uid 65532 — with a `docker-smoke` job that boots it, because
  a missing native library surfaces as SIGSEGV rather than a build error.
- **Configurable log sinks** with bounded rotation that degrade rather than fail.
- **A concurrency canary** polls a cheap endpoint while SSE streams run; it is the metric
  that sees a blocked event loop, where time-to-first-token only sees the model queue.

### Testing

- **The testing bypass is deleted.** The whole suite had run with `app.state.testing`
  tripping the RBAC bypass, so route tests passed through checks that never executed;
  290 tests were converted to authenticate for real.
- **A deterministic integration CI** with a fake Ollama whose embeddings are meaningful, so
  ranking assertions mean something.
- **A mutation gate**, nightly, over the isolation-critical modules.
- **A golden path in a real browser** — sign in, upload, ask, cited answer.

### Removed

- **Flask**, entirely, with a CI check that keeps it out. Metrics and request-id tracing
  were *ported* to FastAPI middleware rather than deleted with it.
- **The Confluence connector** and its `html2text` dependency — no user, and the only one
  of three carrying a runtime dependency.
- **`requirements.lock.txt`**, which neither Docker nor CI installed and nothing validated.

[Unreleased]: https://github.com/jwvanderstam/LocalChat/compare/v3.1.0...HEAD
[3.1.0]: https://github.com/jwvanderstam/LocalChat/compare/v3.0.0...v3.1.0
[3.0.0]: https://github.com/jwvanderstam/LocalChat/compare/v3.0.0-beta.1...v3.0.0
[3.0.0-beta.1]: https://github.com/jwvanderstam/LocalChat/releases/tag/v3.0.0-beta.1
