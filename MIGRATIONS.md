# Database Migrations

LocalChat uses [Alembic](https://alembic.sqlalchemy.org/) for versioned schema migrations.

## How it works

On every startup, after the initial schema is verified by `_init_schema()`, the app
automatically runs `alembic upgrade head`. This is idempotent — already-applied
migrations are skipped.

| Layer | Responsibility |
|-------|---------------|
| `_init_schema()` | Creates all tables (`CREATE TABLE IF NOT EXISTS`) on first boot |
| Alembic migrations | Adds columns and indexes to existing tables (`ALTER TABLE IF NOT EXISTS`) |

## Migration files

```
migrations/
  env.py                    Alembic environment — connects via src.config
  script.py.mako            Template for new migration scripts
  versions/
    0001_baseline.py        Baseline marker (initial schema)
    0002_early_additive_columns.py   conversations/documents early columns
    0003_workspace_columns.py        workspace_id FK on all tables + backfill
    0004_documents_language_ingest_source.py  v1.1/v1.5 document columns
```

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
- Update [`file-map.md`](.claude/rules/file-map.md) when adding a new migration file.

## Upgrade path for existing installations

1. Pull the new code.
2. Restart the app — migrations run automatically on startup.

No manual steps required. If the app cannot connect to the database, migrations
are skipped and a warning is logged. Fix the DB connection and restart.
