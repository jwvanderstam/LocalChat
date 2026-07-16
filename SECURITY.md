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
  - `docker-compose.yml`'s `db` service publishes port 5432 as `"${BIND_HOST:-127.0.0.1}:5432:5432"`, so by default Postgres is bound to localhost only and is **not reachable from outside the host**, even on a machine with a public IP and no firewall — matching the pattern already used by the `app`, `mcp-local-docs`, `mcp-web-search`, and `mcp-cloud-connectors` services in the same file. (The separate, profile-gated `mcp` service intentionally binds `0.0.0.0:3001` for GitHub Copilot SSE access — that is a deliberate, unrelated exception.)
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
