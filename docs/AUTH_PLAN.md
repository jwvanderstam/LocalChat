# AUTH_PLAN — building authentication, and user management for admins

> **Status:** planned, not started. Written 2026-08-06.
> **Why this document exists outside PRODUCTION_PLAN.md:** that plan assumed authentication
> worked and only authorisation was missing. It does not. This is the missing dependency
> underneath SEC-1 and TQ-1, and it blocks normal use of the application today.

---

## The problem, verified

LocalChat has a complete authorisation system and **no way to authenticate**.

Verified against `main` @ `5b011d8` and a running instance, not inferred:

- Nothing outside `security_fastapi.py` ever calls `create_access_token` or
  `verify_credentials_db`. **No token is ever issued.**
- No `fetch` in `static/js/` sends an `Authorization` header.
- There is a `POST /api/logout` and no login. There never has been — not in the FastAPI
  routes, and not in the Flask routes that preceded them.

This was invisible while most routes were unguarded. RBAC-1 (#220, 33 routes) and RBAC-2
(#229, 49 routes) closed that, and the result on a running instance is:

```
/api/health          200
/api/workspaces      401
/api/documents/list  401
/api/conversations   401
/api/models          401
/api/status          401
/documents           200   ← the page loads, then every call it makes fails
```

**The browser UI is currently unusable.** `.env.example` ships a non-empty
`ADMIN_PASSWORD` placeholder, so following the documented setup disables the bypass and
produces a dead app; leaving it empty produces a working app with no authorisation at all.
Both outcomes are wrong.

## What already exists

The gap is narrower than it looks. Almost everything is built:

| Piece | State |
|---|---|
| `users` table, PBKDF2 hashing | ✅ `src/db/users.py` |
| Admin account seeded at startup from `ADMIN_PASSWORD` | ✅ `app_bootstrap._seed_admin_user`; an `admin` row exists |
| Password verification | ✅ `verify_credentials_db()`, `verify_user_password()` |
| JWT issuance | ✅ `create_access_token()` |
| Token validation, role checks, workspace checks | ✅ `require_auth`, `require_admin_dep`, `check_workspace_access` |
| Revocation | ✅ `POST /api/logout` + `revoked_tokens` table + `_verify_jti_not_revoked` |
| Admin user CRUD (7 routes) | ✅ `auth_routes.py` — backend complete, **no UI** |
| `GET /api/users/me` | ✅ added in RBAC-1 |

Missing: **one route that connects verification to issuance**, a frontend that carries the
credential, and two screens.

## Decisions taken (2026-08-06)

1. **Local password *and* OIDC (Entra ID + Google), both now.**
2. **httpOnly cookie**, not `localStorage`.
3. **No temporary workaround** — no revert of RBAC-2, no throwaway bypass.

### Why the cookie decision matters more here than usual

The app renders LLM output into the DOM. That is the highest-value XSS surface in the
product, and `localStorage` would put a bearer token within reach of any injection that
gets through `escapeHtml`. An httpOnly cookie is unreadable from JavaScript, so the same
injection yields nothing.

Cost, stated plainly: `_extract_bearer_token()` must also read the cookie, and CSRF becomes
a live concern. `SameSite=Strict` is sufficient here because the UI and API share an origin
and there is no cross-site form posting into this app. `Secure` is set whenever the request
is not loopback.

---

## Phase 1 — AUTH-1: local login (restores the application)

**Deliverable:** you can log in and use the app again.

- `POST /api/auth/login` — takes username/password, calls the existing
  `verify_credentials_db()`, issues a JWT via `create_access_token()`, sets it as an
  httpOnly cookie. Returns the user shape `GET /api/users/me` already returns, so the
  frontend has one representation of "who am I".
- `_extract_bearer_token()` reads the `Authorization` header **or** the cookie. Header
  first, so existing tests and any curl/n8n integration keep working unchanged.
- `POST /api/logout` additionally clears the cookie. Revocation already works.
- Rate-limit the login route with the existing `slowapi` limiter — it is the one endpoint
  where guessing is the attack.
- A minimal login page, and a 401 interceptor in the frontend that redirects to it.

**Tests:** correct credentials issue a working token; wrong password returns 401 and issues
nothing; the cookie is `httpOnly`, `SameSite=Strict`, and `Secure` off-loopback; a request
authenticated by cookie alone passes `require_auth`; a revoked token is rejected even when
presented as a cookie; login is rate-limited.

**Acceptance:** on a fresh `docker compose up`, log in as the seeded admin through the
browser and load every page without a 401.

## Phase 2 — AUTH-2: user management in Settings

The backend is done; this is the screen. A **Users** tab in `templates/settings.html`,
admin-only, using the existing routes: list, create, edit role, deactivate (soft-delete),
purge, reset password.

Two things the UI must get right because the API allows them:

- **Do not offer "purge" as a normal action.** It is a separate, irreversible TP under the
  Clark-Wilson rules and it already refuses when the user holds workspace memberships. The
  UI should surface soft-delete by default and purge behind an explicit confirmation that
  explains why it can fail.
- **Never let an admin remove their own admin role or delete themselves** while they are
  the last admin. The API does not currently prevent this; the ticket includes adding that
  precondition server-side, not only greying out a button.

**Tests:** a non-admin gets 403 on every user route (already true, asserted again through
the UI's calls); demoting the last admin is refused server-side; the screen renders soft-
deleted users distinctly rather than hiding them.

## Phase 3 — AUTH-3: OIDC login (Entra ID + Google)

**Use `authlib`.** Do not hand-roll this. `id_token` validation has requirements that are
easy to get subtly wrong — issuer and audience checks, `nonce` binding, `at_hash`, clock
skew, JWKS key rotation — and hand-written authorisation is exactly what produced BUG-3,
the fail-open membership checks and the 49 unguarded routes this week. One vetted
dependency is cheaper than that class of bug.

**The existing OAuth code does not help.** `_MS_SCOPES = "Files.Read.All Sites.Read.All
offline_access"` requests *data access* for the SharePoint/OneDrive connectors. Login needs
`openid profile email`, a different flow, and `id_token` validation the connector flow never
performs. Keep them separate: one is "act on the user's files", the other is "prove who the
user is". Sharing the app registration is fine; sharing the code path is not.

- Discovery via `.well-known/openid-configuration`; cache the JWKS with respect for its
  rotation, not indefinitely.
- `state` (CSRF) and `nonce` (replay) on every flow, verified on return. PKCE as well —
  it costs nothing here and removes a class of interception attack.
- On success, issue **the same** application JWT as local login. Downstream code must not
  care how you authenticated. This is what makes OIDC a second issuance path rather than a
  second auth system.

### Security decisions this phase forces — open, and they are not details

**(a) Which tenant may log in.** `MICROSOFT_TENANT_ID` currently defaults to `'common'`.
For connector data access that is merely permissive; **as a login path it means any
Microsoft account in the world can authenticate.** Login must be restricted to a named
tenant, and the `tid` claim verified on every `id_token`. Recommendation: require an
explicit `OIDC_MICROSOFT_TENANT_ID`, and refuse to enable Microsoft login if it is
`common`.

**(b) May an unknown user log in at all?** Two models:

- *Invite-only* — OIDC authenticates, but the user must already exist locally. An unknown
  subject is refused. Recommended for ≤ 25 users: it keeps the user list an explicit
  decision, which is what ADR-1's scope implies.
- *Just-in-time provisioning* — first successful OIDC login creates the account, with a
  default role. Convenient at larger scale; here it means anyone in the tenant silently
  becomes a user of your knowledge base.

**(c) How does an OIDC user get a role?** Recommendation: no automatic elevation. JIT or
invited users land as ordinary users; admin is granted in the Users screen by an existing
admin. Group-claim mapping is a v4.0 concern — it needs claim configuration in the IdP that
does not exist yet, and getting it wrong grants admin silently.

**(d) Linking to an existing local account.** If an OIDC identity presents an email that
matches a local user, do **not** link automatically unless `email_verified` is true *and*
the issuer is trusted for that domain. Unverified-email linking is a documented account
takeover path. Recommendation: match on `(issuer, subject)` stored on the user row; treat
email as a display attribute only.

**Schema:** `users` gains `oidc_issuer` and `oidc_subject` (nullable, unique together), so
an account can have a password, an external identity, or both. Additive migration; follows
the existing `ADD COLUMN IF NOT EXISTS` rule.

## Phase 4 — AUTH-4: close the loop with the existing plan

Once login exists, two already-written tickets become implementable as intended:

- **SEC-1** can delete `DEMO_MODE` and the `not _ADMIN_PASSWORD_RAW` bypass, because there
  is now a real way in. Its seed-and-start decision stands unchanged.
- **TQ-1** can delete `app.state.testing`, because route tests can authenticate for real
  instead of bypassing.

`_is_rbac_bypassed()` disappears entirely at that point. That was always the objective; it
was not reachable while the only way to use the app was through a bypass.

---

## Sequencing

| Phase | Ticket | Unblocks | Est. |
|---|---|---|---|
| 1 | AUTH-1 local login + cookie + frontend | the application itself | 1–2 days |
| 2 | AUTH-2 Users screen in Settings | admin self-service | 1–2 days |
| 3 | AUTH-3 OIDC (Entra + Google) | SSO | 3–5 days |
| 4 | AUTH-4 delete the bypasses | SEC-1, TQ-1 | folded into those |

Phase 1 first because the app is unusable until it lands. Phase 3 is deliberately after
Phase 2: the Users screen is where an OIDC user's role gets granted, so building it first
means Phase 3 has somewhere to land.

## What this changes in PRODUCTION_PLAN.md

SEC-1 and TQ-1 both assume a way to authenticate. Neither is implementable before AUTH-1.
Recorded here rather than silently reordering that plan — and worth noting that the plan's
header claims all code-level claims were re-verified, while this dependency went unnoticed
in it, in RBAC-1, and in RBAC-2.
