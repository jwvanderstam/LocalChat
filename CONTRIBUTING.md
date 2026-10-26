# Contributing

The coding rules are in [CLAUDE.md](CLAUDE.md) and [`.claude/rules/`](.claude/rules/), and
the quality gates every commit must pass are listed there. This file covers what those do
not: who reviews a change before it merges.

## Review of security-critical changes

LocalChat has one maintainer, and most changes are written by an agent working for them.
Green checks show that the tests passed. They do not show that the tests ask the right
question. So a change to the paths below gets a second look before it merges, from a reviewer
that did not write it.

| Path | Why |
|---|---|
| `src/security_fastapi.py` | Who the caller is: tokens, revocation, the role read from the database |
| `src/services/` | Every rule that depends on the caller, and the scope each repository call gets |
| `src/db/connection.py` | The switch into `localchat_scoped` and the all-workspaces flag |
| `migrations/` | Row-level security policies, roles and grants |
| `Dockerfile` | The base image, the user the application runs as |

**The reviewer is a separate agent session**, not the session that wrote the change. It gets
the diff and the checklist below and nothing else. It does not get the author's conversation,
because a reviewer that has read the author's reasoning tends to agree with it. Nobody else
is required: the maintainer decided against a human reviewer (2026-10-25).

That has two consequences, and this file states them so nobody reads more into a review than
it gives:

- **The review is a PR comment, not an approval.** The reviewer posts under the maintainer's
  account, and GitHub does not count an author's approval. So nothing enforces it and there
  is no `CODEOWNERS`. The maintainer reads the review before merging, as they read the checks.
- **It is not a second maintainer.** The reviewer is the same kind of model as the author and
  can miss the same things. It catches what a fresh reading catches. The bus factor is still
  one.

### Checklist

The reviewer answers each question for the diff, citing file and line, or writes "not
touched".

1. **Identity.** Is every caller resolved through `resolve_principal()`? Does any code read
   the role from the token's claims instead of from the database?
2. **Authorisation.** Does every route that names a workspace or an object pass through
   `deny()` (or the guard for that route) before it reads anything? Is another workspace's
   object refused (403 or 404) rather than returned?
3. **Scope.** Does every repository call get the scope the guard authorised (`get_scope()`),
   not one built from request input? Is each use of `ALL_WORKSPACES` needed, and would it
   still be reasonable if the caller were not an admin?
4. **Row-level security.** Does a migration keep `FORCE ROW LEVEL SECURITY` on the ten
   tables? Does a new table that holds workspace data get a policy and a grant to
   `localchat_scoped`? Does a migration that writes those tables as the owner set the
   all-workspaces flag first? Is it additive?
5. **Data integrity.** Does a delete set `deleted_at` instead of issuing `DELETE FROM`? Is
   any hard purge a separate, admin-only action that refuses while references exist?
6. **Input.** Does external input enter through a Pydantic model? Is SQL built only with
   parameters, never with string formatting?
7. **Secrets.** Is any secret, token or password logged, returned in a response, or written
   to an error message? Is new configuration read in `src/config.py` only?
8. **Image.** Is the base image pinned by digest? Does the image still run as uid 65532, with
   exec-form `CMD` and `HEALTHCHECK`?
9. **Tests.** Does each fix carry a test that fails on the code before it? Does a test of a
   refusal prove it would pass for the permitted caller, so that an empty fixture cannot make
   it pass?

### Findings

Each finding gets a severity (Critical, High, Medium, Low). Medium and above are fixed
before the merge or recorded in [SECURITY.md](SECURITY.md) with their status, as the
October 2026 audit's findings are. Lower findings are answered in the PR.
