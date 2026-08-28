# Database Migrations

LocalChat uses [Alembic](https://alembic.sqlalchemy.org/) for versioned schema migrations.

## How it works

On every startup, after the initial schema is verified by `_ensure_extensions_and_tables()`, the app
automatically runs `alembic upgrade head`. This is idempotent — already-applied
migrations are skipped.

| Layer | Responsibility |
|-------|---------------|
| `_ensure_extensions_and_tables()` | Creates all tables (`CREATE TABLE IF NOT EXISTS`) on first boot |
| Alembic migrations | Adds columns and indexes to existing tables (`ALTER TABLE IF NOT EXISTS`) |

## Migration files

```
migrations/
  env.py                    Alembic environment — connects via src.config
  script.py.mako            Template for new migration scripts
  versions/
    0001_baseline.py                          Baseline marker (initial schema)
    0002_early_additive_columns.py            conversations/documents early columns
    0003_workspace_columns.py                 workspace_id FK on all tables + backfill
    0004_documents_language_ingest_source.py  v1.1/v1.5 document columns
    0005_document_soft_delete.py              CW-1: documents.deleted_at/_by, chunks.deleted_at
    0006_cw2a_conversations_soft_delete.py    CW-2a: conversations.deleted_at/_by
    0007_cw2b_users_soft_delete.py            CW-2b: users.deleted_at/_by
    0008_cw2c_workspaces_soft_delete.py       CW-2c: workspaces.deleted_at/_by
    0009_cw2d_memories_soft_delete.py         CW-2d: memories.deleted_at/_by
    0010_cw2e_annotations_soft_delete.py      CW-2e: annotations.deleted_at/_by
    0011_cw2f_connectors_soft_delete.py       CW-2f: connectors.deleted_at/_by
    0012_hybrid_search_tsvector.py            tsvector column + GIN index (lexical arm)
    0013_documents_unique_filename_workspace.py  one live document per (filename, workspace)
    0014_rbac1_backfill_workspace_members.py  RBAC-1: backfill workspace_members
    0015_workspace_api_keys.py                workspace_api_keys table
    0016_connectors_created_by.py             BUG-4: connectors.created_by  ← current head
```

> **This listing stopped at `0004` until 2026-08-27**, while twelve more migrations had
> landed. A reader counting migrations here would have found four and the chain had
> sixteen. `.claude/rules/file-map.md` carried all sixteen throughout — two catalogues of
> the same directory, one maintained and one not, which is the argument for having one.

## Running migrations manually

From the project root:

```bash
# Apply all pending migrations
alembic upgrade head

# Check current version
alembic current

# Show migration history
alembic history --verbose

# Roll back one step (dev only — not for production)
alembic downgrade -1
```

## Writing a new migration

```bash
alembic revision -m "add_foo_column_to_bar"
```

This creates `migrations/versions/<rev>_add_foo_column_to_bar.py`. Fill in the
`upgrade()` and `downgrade()` functions using `op.execute()` with raw SQL or
Alembic's `op.add_column()` helpers.

**Rules:**
- Always use `IF NOT EXISTS` / `IF EXISTS` in DDL — migrations must be idempotent.
- Never use destructive DDL in `upgrade()` (no `DROP COLUMN`, `DROP TABLE`).
  Use a follow-up migration after confirming all instances are on the new schema.
- Data backfills belong in the same migration as the column that requires them.
- Update [`file-map.md`](../.claude/rules/file-map.md) when adding a new migration file.

### Getting the revision number right

`revision` / `down_revision` are hand-written in this repo, so a wrong number is
easy to introduce and hard to see. **Read the number from the directory, never from
a doc:**

```bash
ls migrations/versions/          # the only authority on what exists
alembic heads                    # must print exactly one head
```

`file-map.md` is a convenience index and has been out of date before. In August 2026
a backfill migration was numbered from that table while the table was missing two
existing migrations; the new file collided with an existing `0012`.

**Two revisions sharing an id do not fail loudly.** Alembic emits a
`UserWarning: Revision NNNN is present more than once` through Python's `warnings`
module — not the app logger — and then `upgrade head` aborts with:

```
alembic.script.revision.MultipleHeads: Multiple heads are present for given argument 'head'
```

`_run_alembic_migrations()` catches that and logs it, so the app still starts and
**no migration is applied at all** — including every previously pending one. Verify a
new migration by running it, not by reading it:

```bash
alembic heads                    # exactly one line
alembic upgrade head             # expect "Running upgrade X -> Y"
alembic current                  # expect your new revision
```

No CI job executes migrations (see "How it works"), so this check is manual and it is
the only thing that catches a broken chain before a deployment does.

## Upgrade path for existing installations

1. Pull the new code.
2. Restart the app — migrations run automatically on startup.

No manual steps required. If the app cannot connect to the database, migrations
are skipped and a warning is logged. Fix the DB connection and restart.
