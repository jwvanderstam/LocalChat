# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in LocalChat, please report it privately rather than opening a public issue.

- **Contact**: jw.vander.stam@gmail.com
- Include a description of the issue, steps to reproduce, and the affected commit/version.
- LocalChat is developed on a rolling `main` branch; only the latest commit on `main` is supported — there are no maintained release branches.

## Known & Accepted Risks

The items below are known, deliberately **not remediated via the usual route** (credential rotation / git history rewrite), and are documented here so a reviewer can establish their status from the repo alone. Reviewed as of 2026-09-16 — re-check every entry against the source when editing this file, and move this date. An entry that is merely old reads exactly like one that is still true.

### 1. Historical leaked local-dev database credential

- **What**: A PostgreSQL password (`PG_PASSWORD`) was committed in plaintext starting with the initial commit (`5499093`) and several early commits — confirmed via `git log --all -S <value>` using the value currently set for `PG_PASSWORD` in the local, untracked `.env` file used for Docker Compose development (intentionally not repeated here — this file is tracked and published, and doing so would make the value more discoverable than it already is, for no verification benefit).
- **Scope**: Used only by the local Docker Compose `db` (PostgreSQL) service for local development (see `docker-compose.yml`). Never used in any deployed/production environment, and never reused for any other account or system.
- **Decision — not rotated, not rewritten out of git history**:
  - *Not rotated*: it only ever protected a local, loopback-bound Postgres instance with no externally reachable production data — rotation provides negligible security benefit.
  - *Not rewritten out of history*: rewriting history (`git filter-repo` / BFG) breaks every clone, fork, and commit reference for a credential that carries no real-world risk once its exposure is accepted. Disproportionate for this case.
  - The credential is treated as **burned**: it must never be reused for any new secret, account, or environment.
- **Compensating controls already in place**:
  - `.env` is git-ignored — the live value is not re-committed by normal use; `.env.example` only ships a placeholder (`PG_PASSWORD=your-password-here`).
  - `src/config.py` fails closed at startup if `PG_PASSWORD` is unset (`raise ValueError("PG_PASSWORD must be set in .env file!")`) — the app can never silently fall back to a default.
  - `docker-compose.yml`'s `db` service publishes port 5432 as `"${BIND_HOST:-127.0.0.1}:5432:5432"`, so by default Postgres is bound to localhost only and is **not reachable from outside the host**, even on a machine with a public IP and no firewall — matching the pattern already used by the `app`, `ollama`, `mcp-local-docs`, `mcp-web-search`, and `mcp-cloud-connectors` services in the same file. (`ollama` publishes `"${BIND_HOST:-127.0.0.1}:${OLLAMA_BIND_PORT:-11434}:11434"` so the host-run dev path can reach it; containers use the `backend` network and do not need it.)
- **Forward-looking control**: gitleaks secret scanning now runs in CI (`.github/workflows/gitleaks.yml`) and as a local pre-commit hook (`.pre-commit-config.yaml`) to prevent any *new* credential leak. Both only scan the push/PR diff or staged changes — never full history — so they never re-encounter this historical leak; `.gitleaks.toml` deliberately has no allowlist entry for it (see that file's header comment for why) and only allowlists CI's own non-secret placeholder test credentials.

### 2. `ecdsa` timing side-channel — PYSEC-2026-1325 — resolved 2026-09-20

**No longer an accepted risk.** `python-jose[cryptography]` was replaced by `PyJWT`
(ROADMAP P2-6), which signs and verifies HS256 over the standard library's `hmac`
and `hashlib`. It pulls no `ecdsa`, no `rsa` and no `pyasn1`, so the vulnerable code
is not in either lock and not in the image — the risk is removed rather than reasoned
around. The `pip-audit --ignore-vuln PYSEC-2026-1325` suppression in
`.github/workflows/tests.yml` went with it, and that step now runs with no suppressions
at all.

The entry is kept at its number because `CHANGELOG.md` and four current documents cite
the sections below it by number; renumbering would silently break those references for
a gain of one deleted heading.

### 3. JWT revocation honours a bounded 60-second grace window on database outage

- **What**: `resolve_principal()` (`src/security_fastapi.py`) checks a token's `jti` against
  the `revoked_tokens` deny-list (`TokensMixin.is_token_revoked`, `src/db/tokens.py`) on every
  authenticated request. `_verify_jti_not_revoked()` **fails closed** — if the database is
  unreachable and the token was not verified in the last 60 seconds, the request is refused
  with 401 rather than let through. The residual risk is the grace window itself: a token
  revoked during an outage stays usable for up to 60 seconds after its last successful check.
- **"Every authenticated request" became true on 2026-09-16.** This entry said it before it
  was: the check lived in `require_auth()` alone, while `check_workspace_access()` — every
  document, chat, memory, feedback, annotation and connector route — and `require_admin_dep()`
  — 31 admin routes — each decoded the token themselves and never asked. A revoked token kept
  working on all of them until it expired. All three now resolve the caller through one
  function, which is where the check lives (audit H1).
- **Why this is accepted**: without the cache, any database blip becomes an authentication
  outage for every logged-in user. The window is bounded, in-process (correct under
  [ADR-1](docs/ADR.md), which fixes this at one node and one process), and the cache is
  capped at 4096 entries with stale-first eviction so a stream of distinct tokens cannot grow
  it without limit. A live check always wins over a cached entry, so revocation while the
  database is healthy takes effect immediately rather than after up to 60 seconds.
- **Compensating factor**: JWTs are short-lived (`JWT_ACCESS_TOKEN_EXPIRES`, default 7200s),
  so the exposure from a missed revocation is bounded by the token's own expiry regardless of
  database state.
- **Re-review trigger**: multi-tenant hosting (different trust domain per workspace), where
  60 seconds of stale authorisation crosses a tenant boundary rather than staying inside one
  operator's deployment.

> **Corrected 2026-08-20.** Until this revision, this entry described the *opposite* behaviour
> — fail-open, quoting a comment (`# DB unavailable — fail open rather than locking out
> users`) that no longer exists in the source. `13cd503` (2026-08-07, SEC-2) made revocation
> fail closed, and the entry's own "re-review trigger" had come to prescribe as future work
> exactly what had already shipped. It survived two later edits to this file because nothing
> re-checked it against the code. The stated `JWT_ACCESS_TOKEN_EXPIRES` default was also wrong
> — 3600s, against 7200s in `src/config.py` — which understated by half the very bound this
> entry leans on. Found by the 2026-08-19 external audit.

### 4. Plugins execute with full application privileges — no sandboxing

- **What**: `PluginLoader.load_file()` (`src/tools/plugin_loader.py`) loads every `.py` file under `plugins/` via `importlib.util.spec_from_file_location` + `exec_module` — genuine Python module execution, not a restricted or sandboxed interpreter. A plugin's top-level code runs with the same OS privileges as the main app: full filesystem access, network access, and (via the services it can import) the same database connection pool.
- **Why this is accepted**: nothing in the loader constrains a plugin, and nothing is claimed to. The plugin contract in `.claude/rules/plugins.md` (service/hook boundary, no core imports) is a *design, not built* — its own status banner says so — and even built it would only describe what a *well-behaved* plugin does; it could not constrain what an *adversarial* file placed in `plugins/` does, because Python has no built-in code sandbox. What ships is `plugins/README.md`'s loader: any `.py` in the directory runs. The trust boundary is therefore the filesystem, not the plugin loader: whoever can write to the `plugins/` directory already has the same privileges as the app process, with or without the plugin system.
- **Compensating factor**: `plugins/` is not writable by any unauthenticated or lower-privilege actor in the shipped deployment — it ships as part of the repo/image, not as a runtime-uploadable directory. There is no HTTP endpoint that writes files into `plugins/`.
- **Re-review trigger**: if LocalChat ever adds a feature that writes an uploaded or admin-submitted file into `plugins/` at runtime (e.g. a "install plugin from URL" admin action), that feature is the point where real sandboxing (subprocess isolation, restricted `__builtins__`, or a plugin marketplace review step) becomes necessary — the current design is safe only because plugin code is deployment-time, not runtime, content.

### 5. `onnxruntime` is pinned past a release that segfaults on the hardened base

- **What**: `requirements.txt` pins `onnxruntime==1.30.0`; it was held at 1.28.0 until
  Dependabot #371 (2026-09-14) moved it and `docker-smoke` proved the image still boots.
  1.29.0 imports cleanly on `python:3.12-slim`, but **segfaults** (SIGSEGV, exit 139, no
  traceback) on `dhi.io/python:3.12`. The dependency arrives transitively via
  `pymupdf-layout`; nothing in this codebase imports it directly.
- **Why this is accepted**: the root cause is not identified. `ldd` on the native module
  is clean, every library it declares is present, and the shared-library diff between the
  two bases shows nothing it links against. The pin is a workaround with a recorded reason,
  not a fix.
- **Compensating factor**: `docker-smoke` builds and boots the image on every PR, so a
  Dependabot bump back to 1.29.x turns the PR red rather than shipping a container that
  will not start.
- **Re-review trigger**: a security advisory against the pinned version, or a bump that
  turns `docker-smoke` red — test by building the image and importing it, since neither
  `pip install` nor `docker build` will reveal the problem. The root cause of 1.29.0 is
  still unidentified, so a later release regressing the same way is not ruled out.

### 6. Document text is not encrypted at rest

- **What**: `ENCRYPTION_KEY` field-encrypts OAuth tokens (`src/db/oauth_tokens.py`), message
  content (`src/db/conversations.py`) and long-term memories (`src/db/memories.py`). It does
  **not** cover document text. `document_chunks.chunk_text` — the column retrieval reads and
  feeds to the model — is stored in plain text, as is `documents.content`.
- **Why this is accepted**: it cannot be fixed at the field level. `chunk_tsv` is
  `GENERATED ALWAYS AS (to_tsvector('simple', chunk_text)) STORED` (`src/db/connection.py`), so
  encrypting `chunk_text` removes the lexical arm of hybrid search entirely — the ciphertext
  tokenises to nothing. Encryption and full-text search over the same column are mutually
  exclusive without a searchable-encryption scheme this project has no reason to carry.
- **Corrected in SEC-4**: `documents.content` *was* passed through `encrypt()` on write, and
  never decrypted — nothing reads that column back. It protected nothing, because the same
  text sat in plain text in `chunk_text` beside it, and it made the schema read as though
  document content was encrypted. The call was removed rather than the claim left standing.
- **Compensating control**: disk/volume encryption on the Postgres data directory, which is
  where document text at rest is actually defended. The Postgres port binds to `127.0.0.1` by
  default, so the database is not reachable off-host.
- **Re-review trigger**: any move to hosted or multi-tenant deployment, where the disk is not
  the operator's own — at which point the question is whether retrieval can move to a design
  that does not need plaintext in the database, not whether to encrypt this column.

### 7. The env-var admin remains available while the database cannot be read

- **What**: `ADMIN_PASSWORD` authenticates a built-in `admin` account that has no user row.
  Since decision D6 it is a **bootstrap credential**: it works only while the database holds
  no live administrator, and an open session stops being administrative the moment one
  exists. A normal boot seeds a database admin from the same password, so in practice it is
  withdrawn from the first start.
- **The residual**: when the database cannot answer, whether a real administrator exists is
  unknown, and this account is treated as available — which is what it has always been, and
  is the documented way back in when the database is empty or unreachable. So an outage
  restores a credential that a healthy installation has withdrawn.
- **Why accepted**: D6 asked for a credential that a real administrator supersedes, not for
  the recovery path to be removed, and the two are separable. The exposure is also narrow:
  reaching it needs `ADMIN_PASSWORD` itself, and with the database down every
  workspace-scoped route answers 503 regardless, so there is very little to reach.
- **Before this**: the account could not be demoted or disabled by anyone, had no strength
  check — the `.env.example` placeholder passed production validation — and kept working
  beside a *changed* database admin password (audit M1).
- **Re-review trigger**: any deployment where the database is not the operator's own, or the
  first time this account is wanted as a true break-glass path — at which point the question
  is option D6-B (keep it, with a strength check and every use logged), not this middle
  ground.

### 8. Connectors read data the application is trusted to reach

- **What**: a connector ingests documents from a source the application can reach, and
  everything it ingests becomes answerable through retrieval. The configuration therefore
  decides what the application can read, which makes *who may configure one* the control,
  not what the connector does afterwards.
- **`local_folder` — global administrator, plus an allowlist.** Its path names the server's
  own filesystem. Both conditions are enforced independently in
  `src/routes_fastapi/connector_routes.py`: creating or reconfiguring one requires a global
  administrator, and the path must resolve inside `CONNECTOR_LOCAL_ROOTS`
  ([CONFIGURATION.md](docs/CONFIGURATION.md)), which is **empty by default and so disables
  the type**. Paths are resolved with `realpath` and compared by whole components, so `..`
  and a symlink pointing out of an allowed root both fail.
  - This entry exists because the controls did not. A September 2026 external audit
    reproduced the whole of it: any user could create a workspace, become its owner, create
    a `local_folder` connector on `/etc`, and read it back. `ws:owner` was the only check,
    and it is not a barrier when any user may create a workspace. Fixed 2026-09-16.
- **`webhook`** is a public receiver by design — the connector id plus its secret is the
  whole credential. **Closed 2026-09-16 (P1-2)**: the secret is mandatory, at creation as
  well as at delivery, must be at least 16 characters, and is compared with
  `hmac.compare_digest`. The fetch goes through `safe_fetch` (§9), so it is capped and
  cannot be pointed at an internal address.
- **`s3`** — **removed 2026-09-16** (audit M5, decision D5). It accepted an owner-supplied
  `endpoint_url` and could fall back to the server's own AWS credentials, and it could not
  run in the shipped image at all, because `boto3` is deliberately not there
  ([ADR-4](docs/ADR.md)). A connector that cannot run is not a feature worth guarding.
- **Re-review trigger**: any new connector type whose configuration names something outside
  the workspace — a path, a host, a credential — belongs in `_ADMIN_ONLY_TYPES` and in this
  list, and the question to answer first is what a workspace owner could reach with it.

### 9. Outbound fetches resolve before they decide, but do not pin the address

- **What**: `src/utils/safe_fetch.py` is the one path by which this application retrieves a
  URL it was handed — a web-search result, or a webhook's `fetch_url`. It resolves the
  hostname, refuses the fetch if **any** address the name answers with is private, loopback,
  link-local, reserved, multicast or unspecified, re-validates every redirect hop, and caps
  the body and the time.
- **The residual**: the connection is then made by name. A DNS entry that answers
  differently between the check and the connection — rebinding — is not defeated. Closing it
  means pinning the connection to the validated address, which over HTTPS means taking over
  certificate verification for every outbound fetch.
- **Why accepted**: the attacker has to control a DNS zone *and* win a race measured in
  milliseconds, to reach a network where the interesting services already require
  credentials. The check that is in place closes the finding that was actually reported: a
  name that simply resolves to `10.0.0.5` used to be fetched.
- **Before this**: both call sites inspected the hostname *string*. An IP literal in a
  private range was refused; a DNS name was waved through, with a comment in the source
  saying the check could not resolve it. Redirects were followed without a second look, and
  neither path capped the response (audit M4).
- **Re-review trigger**: any deployment where the internal network holds something reachable
  without credentials, or the first time an outbound fetch is made on behalf of an untrusted
  tenant rather than an operator.

### 10. The MCP servers authenticate with one shared token, not per-user

- **What**: the domain MCP servers (`mcp_servers/`, `--profile mcp`, off by default)
  authenticate callers with a single shared secret, `MCP_AUTH_TOKEN`, presented as a bearer
  token and compared with `hmac.compare_digest`. They hold no session and no user, so that
  token is the whole of their access control. Workspace scoping is passed *by the caller*:
  `search` requires a `workspace_id` and refuses without one.
- **The residual**: anything holding the token can name any workspace. The servers trust the
  application to pass the workspace it authorised, because they have no way to check — there
  is no user identity in an MCP call to check it against.
- **Why accepted**: the servers are off by default, run on the internal `backend` network
  with their ports bound to loopback, and the only intended caller is the application
  itself. Decision D4 chose to authorise them rather than remove them.
- **Before this**: there was no check at all, and `search` could not accept a workspace —
  so with `MCP_ENABLED=true`, every answer was drawn from every workspace regardless of who
  asked, and anything that could reach the port got the whole corpus (audit C3).
- **Re-review trigger**: any caller other than this application, or any deployment where the
  servers are reachable beyond the compose network — at which point the token should become
  per-caller, and the workspace should be derived from an identity the server can verify
  rather than accepted from the request.

## Supply chain

- Base images are **digest-pinned** (`dhi.io/python:3.12` and `:3.12-dev`). A bare tag
  makes the image's CVE posture unverifiable after the fact — see [ADR-3](docs/ADR.md).
- `requirements.txt` is **pip-compile output** from `requirements.in`, pinning the full
  transitive closure, and is installed by both CI and Docker on every run — so the pins
  are continuously exercised rather than asserted. It carries no hashes; the reasoning,
  which is a measurement rather than an oversight, is in `requirements.in`'s header.
- `pip-audit` runs in `unit-tests`; `gitleaks`, CodeQL and SonarCloud run on every PR.
- The runtime image ships no shell and no package manager, so nothing can install itself
  into a running container.
- Test tooling is confined to `requirements-dev.in`, which the image never installs. The
  runtime image no longer contains `pytest`, `playwright`, `faker`, `coverage`,
  `responses` or `freezegun` (closed 2026-08-26, OPS-1).
