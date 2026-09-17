# Changelog

Notable changes to LocalChat. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file starts at v3.0.0-beta.1. Earlier work is in the commit history and, with the
reasoning attached, in [docs/LESSONS_LEARNED.md](docs/LESSONS_LEARNED.md).

## [Unreleased]

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
