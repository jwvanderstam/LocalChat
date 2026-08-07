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

1. **Local password now; OIDC (Entra ID + Google) designed now, built on a trigger.**
   The original decision was "both now"; revised the same day on the advice that AUTH-1 plus
   AUTH-2 already yield a working, authorised application for this user count, and that the
   four OIDC security decisions are better taken with real users in view. The design is
   complete and the decisions are recorded — only the build waits. See Phase 3.
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

## Phase 1 — AUTH-1: local login ✅ (done)

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

## Phase 1b — AUTH-5: workspace API keys ✅ (done)

Added out of sequence because a real consumer was broken by RBAC-2: a Discord bridge
(n8n → LocalChat → Discord) had been calling the API unauthenticated, and the guarded
routes stopped it.

The first framing was a *service user* — a flagged non-human account. The better one, and
the one built, is that **a workspace is an endpoint**: the credential belongs to the
workspace, not to a person standing in for a machine. That removes the objections rather
than accommodating them — there is no password to reset because there is no password, no
session to expire because keys are revoked, and the audit trail names the key.

Per the plugin contract, this is a **core capability, not a plugin**. The contract's own
test — *would this be reasonable if the requesting consumer vanished?* — passes: Slack,
Teams, cron and n8n all want the same thing. A `discord_bridge` service would have been a
leak. When PC-1..PC-4 land, a chatbot plugin consumes this rather than replacing it.

Design decisions worth keeping:

- **The key's workspace is authoritative.** A client-supplied workspace is only ever
  compared against it, never substituted. The scope is pinned onto the request so a call
  omitting `X-Workspace-ID` cannot drift to the *default* workspace downstream after
  authorising against the key's — that path would have been silently wrong rather than
  refused.
- **A key is never a global admin**, and cannot be issued at `owner` — a key that mints
  keys turns one leak into permanent control.
- **sha256, not PBKDF2.** Slow hashing exists because passwords are low-entropy; a
  32-byte random key is not brute-forced, and a slow hash would tax every request.
- **Revocation is soft-delete**, so the audit trail outlives the credential.

See [WORKSPACE_API_KEYS.md](WORKSPACE_API_KEYS.md).

## Phase 2 — AUTH-2: user management in Settings ✅ (done)

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

> **Outcome.** Both preconditions landed server-side, in `src/db/users.py`, raising
> `LastAdminError` which the routes translate to 409 — the request is well-formed, the
> current state forbids it. Enforced there and not in the UI because a greyed-out button is
> a courtesy, not a precondition: curl has to hit the same wall. `test_refusal_writes_nothing`
> pins that the guard runs *before* the UPDATE, and five tests cover the negative space,
> since a guard that also blocks ordinary administration is a different bug.
>
> Three defects surfaced in my own work while checking it, each invisible to a mocked test:
> `list_users()` filtered `deleted_at IS NULL`, so the purge button rendered for data that
> never arrived; `_row_to_user` maps positionally and silently dropped the new eighth column,
> so every retired user came back looking live; and `users.js` resolved its DOM elements
> before optionally waiting for `DOMContentLoaded`, which would have left them `null`. The
> first two are now covered by tests that construct a real row rather than mocking one.

## Phase 3 — AUTH-3: OIDC login (Entra ID + Google) ⏸️ built on a trigger, not on a date

> **Sequenced behind a condition, decided 2026-08-06.** After AUTH-1 and AUTH-2 you have a
> working, authorised application with user management, on local passwords — which is
> appropriate for the user count ADR-1 describes. AUTH-3 is a further 3–5 days, four security
> decisions that can grant access silently if taken carelessly, and an external dependency in
> the login path of an application that otherwise runs local and offline.
>
> The real argument for OIDC is not convenience, it is **offboarding**: when someone leaves,
> their access disappears with their IdP account instead of depending on someone remembering.
> That argument strengthens with headcount and is weak at one user.
>
> **Trigger:** build it when there is a second and third real user, or when someone whose
> access must be revocable centrally needs an account. Take the four decisions below with
> those actual people in mind rather than hypothetical ones. The design below stays valid;
> only the timing is conditional.

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

### Security decisions — decided 2026-08-06

All four take the restrictive option. The asymmetry is the reason: loosening any of these
later is a config change, while tightening one after people rely on it means revoking access
someone already has.

**(a) Only a named tenant may log in.** `MICROSOFT_TENANT_ID` defaults to `'common'`. For
connector data access that merely lets a user link their own OneDrive. **As a login path it
means authentication succeeds for any Microsoft account in existence**, personal Outlook
addresses included — the "Log in with Microsoft" button becomes an open registration form.

Requires a separate `OIDC_MICROSOFT_TENANT_ID`, verifies the `tid` claim on every
`id_token`, and **refuses to start** if it is set to `common`. Refusing rather than warning:
a logged warning on a fail-open default is exactly the pattern removed this week.

**(b) Invite-only. An unknown subject is refused.** At ≤ 25 users, inviting costs one action
per person per engagement, and it keeps the user list a decision rather than a by-product of
tenant membership. With JIT provisioning, everyone in the tenant becomes a user of the
knowledge base as soon as they learn the URL — and that knowledge base is the reason the
application exists. JIT becomes reasonable in the hundreds; that is a different product from
the one ADR-1 describes.

**(c) Roles are never granted automatically.** No group-claim mapping. Admin is granted by
an admin in the Users screen (AUTH-2).

Group mapping is not wrong in principle; it has a *silent* failure mode. A misconfigured
group in the IdP grants admin with nothing changing visibly inside this application, so it
surfaces at audit time rather than at grant time. Manual granting is visible, attributable,
and trivial at this size. Revisit when the user list is too large to maintain by hand.

**(d) Identities link on `(issuer, subject)`, never on email alone.** Email in an `id_token`
is a claim, and whether it was verified depends on the provider. An IdP that issues
unverified addresses lets someone register with an existing admin's email and take the
account over — a known, exploited path.

`oidc_issuer` + `oidc_subject` are stable and unique per IdP; email is a display attribute.
Deliberate linking is still possible and is explicit: an admin invites by email, and the
first successful OIDC login carrying `email_verified: true` binds that identity to the row.

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
| 1 | AUTH-1 local login + cookie + frontend ✅ done | the application itself | — |
| 2 | AUTH-2 Users screen in Settings ✅ done | admin self-service | — |
| 4 | AUTH-4 delete the bypasses | SEC-1, TQ-1 | folded into those |
| 3 | AUTH-3 OIDC ⏸️ | SSO, central offboarding | 3–5 days, **on trigger** |

AUTH-4 moves ahead of AUTH-3: deleting `DEMO_MODE` and `app.state.testing` only needs a way
to authenticate, which AUTH-1 provides. Waiting for OIDC would leave the bypasses in place
for no reason.

Phase 1 first because the app is unusable until it lands. AUTH-3, when its trigger fires,
still comes after AUTH-2: the Users screen is where an OIDC user's role gets granted and
where invitations are issued, so it must exist before an external identity has anywhere to
land.

## What this changes in PRODUCTION_PLAN.md

SEC-1 and TQ-1 both assume a way to authenticate. Neither is implementable before AUTH-1.
Recorded here rather than silently reordering that plan — and worth noting that the plan's
header claims all code-level claims were re-verified, while this dependency went unnoticed
in it, in RBAC-1, and in RBAC-2.
