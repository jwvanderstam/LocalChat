# Changelog

Notable changes to LocalChat. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file starts at v3.0.0-beta.1. Earlier work is in the commit history and, with the
reasoning attached, in [docs/LESSONS_LEARNED.md](docs/LESSONS_LEARNED.md).

## [Unreleased]

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

[Unreleased]: https://github.com/jwvanderstam/LocalChat/compare/v3.0.0...HEAD
[3.0.0]: https://github.com/jwvanderstam/LocalChat/compare/v3.0.0-beta.1...v3.0.0
[3.0.0-beta.1]: https://github.com/jwvanderstam/LocalChat/releases/tag/v3.0.0-beta.1
