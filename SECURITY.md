# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in LocalChat, please report it privately rather than opening a public issue.

- **Contact**: jw.vander.stam@gmail.com
- Include a description of the issue, steps to reproduce, and the affected commit/version.
- LocalChat is developed on a rolling `main` branch; only the latest commit on `main` is supported — there are no maintained release branches.

## Known & Accepted Risks

The items below are known, deliberately **not remediated via the usual route** (credential rotation / git history rewrite), and are documented here so a reviewer can establish their status from the repo alone. Reviewed as of 2026-07-12.

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
  - `docker-compose.yml`'s `db` service publishes port 5432 as `"${BIND_HOST:-127.0.0.1}:5432:5432"`, so by default Postgres is bound to localhost only and is **not reachable from outside the host**, even on a machine with a public IP and no firewall — matching the pattern already used by the `app`, `ollama`, `mcp-local-docs`, `mcp-web-search`, and `mcp-cloud-connectors` services in the same file. (`ollama` publishes `"${BIND_HOST:-127.0.0.1}:${OLLAMA_BIND_PORT:-11434}:11434"` so the host-run dev path can reach it; containers use the `backend` network and do not need it.) (The separate, profile-gated `mcp` service intentionally binds `0.0.0.0:3001` for GitHub Copilot SSE access — that is a deliberate, unrelated exception.)
- **Forward-looking control**: gitleaks secret scanning now runs in CI (`.github/workflows/gitleaks.yml`) and as a local pre-commit hook (`.pre-commit-config.yaml`) to prevent any *new* credential leak. Both only scan the push/PR diff or staged changes — never full history — so they never re-encounter this historical leak; `.gitleaks.toml` deliberately has no allowlist entry for it (see that file's header comment for why) and only allowlists CI's own non-secret placeholder test credentials.

### 2. `ecdsa` timing side-channel — PYSEC-2026-1325

- **What**: `ecdsa` (a transitive dependency of `python-jose[cryptography]`, used for JWT auth) has a known timing side-channel in its ECDSA sign/verify implementation, tracked as PYSEC-2026-1325. The `ecdsa` maintainers treat timing side-channel attacks as out of scope for the library; no fix is planned.
- **Why it doesn't affect LocalChat**: `src/security_fastapi.py` hardcodes `_ALGORITHM = "HS256"` for both signing and verification:
  - `jwt.encode(payload, config.JWT_SECRET_KEY, algorithm=_ALGORITHM)`
  - `jwt.decode(token, config.JWT_SECRET_KEY, algorithms=[_ALGORITHM])`

  HS256 is HMAC-based and never touches `ecdsa`'s ECDSA code path. The `algorithms=[_ALGORITHM]` allowlist passed to `jwt.decode()` also means python-jose *rejects* any token claiming a different algorithm (e.g. ES256) — an attacker cannot force the app into the vulnerable code path via a crafted token either. The vulnerable code is present on disk as a transitive dependency but is provably unreachable through this app's own JWT usage.
- **Disposition**: Risk accepted; no upstream fix exists to remediate to. Suppressed in CI with a documented reason so it doesn't perpetually flag red without context, while every *other* vulnerability still fails the build:
  ```
  pip-audit -r requirements.txt --ignore-vuln PYSEC-2026-1325
  ```
  See `.github/workflows/tests.yml` (`unit-tests` job → "Dependency vulnerability scan (pip-audit)" step).
- **Re-review trigger**: revisit if LocalChat ever adds an ECDSA-based JWT algorithm (e.g. ES256), or if `ecdsa`/`python-jose` ships a fix and the pin can be bumped.

### 3. JWT revocation fails open when the database is unreachable

- **What**: `require_auth()` (`src/security_fastapi.py`) checks a token's `jti` against the `revoked_tokens` deny-list (`TokensMixin.is_token_revoked`, `src/db/tokens.py`) on every authenticated request. `_verify_jti_not_revoked()` catches any exception from that check — including the database being down — and **lets the request through** rather than rejecting it, with the comment `# DB unavailable — fail open rather than locking out users`.
- **Why this is a deliberate tradeoff, not an oversight**: the alternative (fail closed) turns any database outage into a full authentication outage for every logged-in user, for a self-hosted single-tenant app where the operator and the deployer are the same trust domain. A still-valid (non-expired, correctly-signed) JWT is honored during the outage window; only *revocation* — the ability to kill a specific already-issued token early (e.g. after a password change) — is what silently stops working, and only for the duration of the outage.
- **Compensating factors**: JWTs are short-lived (`JWT_ACCESS_TOKEN_EXPIRES`, default 3600s), so the exposure window from a missed revocation is bounded by the token's own expiry regardless of database state. The check itself (`db.is_connected`) means this path only ever engages when the DB is already known-down — it is not a routine code path.
- **Re-review trigger**: if LocalChat moves to multi-tenant hosting (different trust domain per workspace), fail-open on auth becomes a cross-tenant risk and this decision should be revisited — likely toward fail-closed with a short in-memory revocation cache as the fallback, rather than skipping the check outright.

### 4. Plugins execute with full application privileges — no sandboxing

- **What**: `PluginLoader.load_file()` (`src/tools/plugin_loader.py`) loads every `.py` file under `plugins/` via `importlib.util.spec_from_file_location` + `exec_module` — genuine Python module execution, not a restricted or sandboxed interpreter. A plugin's top-level code runs with the same OS privileges as the main app: full filesystem access, network access, and (via the services it can import) the same database connection pool.
- **Why this is accepted**: the plugin contract (`.claude/rules/plugins.md`, `CLAUDE.md`'s "Plugin Contract" section) constrains what a *well-behaved* plugin does architecturally (service/hook boundary, no core imports) — it does not and cannot constrain what an *adversarial* file placed in `plugins/` could do, because Python has no built-in code sandbox. The trust boundary is therefore the filesystem, not the plugin loader: whoever can write to the `plugins/` directory already has the same privileges as the app process, with or without the plugin system.
- **Compensating factor**: `plugins/` is not writable by any unauthenticated or lower-privilege actor in the shipped deployment — it ships as part of the repo/image, not as a runtime-uploadable directory. There is no HTTP endpoint that writes files into `plugins/`.
- **Re-review trigger**: if LocalChat ever adds a feature that writes an uploaded or admin-submitted file into `plugins/` at runtime (e.g. a "install plugin from URL" admin action), that feature is the point where real sandboxing (subprocess isolation, restricted `__builtins__`, or a plugin marketplace review step) becomes necessary — the current design is safe only because plugin code is deployment-time, not runtime, content.

### 5. `onnxruntime` is pinned to 1.28.0 to avoid a segfault on the hardened base

- **What**: `requirements.txt` pins `onnxruntime==1.28.0`. 1.29.0 imports cleanly on
  `python:3.12-slim` and on the hardened base at 1.28.0, but **segfaults** (SIGSEGV, exit
  139, no traceback) when 1.29.0 runs on `dhi.io/python:3.12`. The dependency arrives
  transitively via `pymupdf-layout`; nothing in this codebase imports it directly.
- **Why this is accepted**: the root cause is not identified. `ldd` on the native module
  is clean, every library it declares is present, and the shared-library diff between the
  two bases shows nothing it links against. The pin is a workaround with a recorded reason,
  not a fix.
- **Compensating factor**: `docker-smoke` builds and boots the image on every PR, so a
  Dependabot bump back to 1.29.x turns the PR red rather than shipping a container that
  will not start.
- **Re-review trigger**: a security advisory against 1.28.0, or an onnxruntime release that
  resolves the crash — test by building the image and importing it, since neither `pip
  install` nor `docker build` will reveal the problem.

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

## Supply chain

- Base images are **digest-pinned** (`dhi.io/python:3.12` and `:3.12-dev`). A bare tag
  makes the image's CVE posture unverifiable after the fact — see [ADR-3](docs/ADR.md).
- `requirements.txt` is fully pinned and installed by both CI and Docker on every run, so
  the pins are continuously exercised rather than asserted.
- `pip-audit` runs in `unit-tests`; `gitleaks`, CodeQL and SonarCloud run on every PR.
- The runtime image ships no shell and no package manager, so nothing can install itself
  into a running container.
- **Known gap**: `requirements.txt` has no dev/prod split, so the runtime image also
  contains `pytest`, `playwright`, `faker`, `coverage`, `responses` and `freezegun`. Test
  code is excluded from the image; the test *frameworks* are not. Tracked in
  [ROADMAP.md](docs/ROADMAP.md).
